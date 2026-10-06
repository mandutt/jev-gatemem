# -*- coding: utf-8 -*-
"""stage55: pool20 3-run majority 검증 (2026-10-06, 270콜)

stage54 1-run: pool20 hit@1 78/79 vs base 79/80 — -1 차이가 비결정성인지 확인.
pool20만 3-run 반복, majority(2/3 일치)로 hit@1/3 확정 후 base 1-run과 비교.
3-run 각 run의 hit@1/3 + abstain + err + gold_rank 분포.
"""
import os, sys, json, sqlite3, time, re

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)
import stage48_live60_cross as m48
import gateway.j1_pipeline as j1p
from mnemosyne.core import beam as beam_mod
from mnemosyne.core import embeddings as emb_mod
from jev_mem_core.pipeline import _jev_client

SNAP = m48.SNAP
DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
s = sqlite3.connect(SNAP); s.row_factory = sqlite3.Row

ABSTAIN_CUR = m48.ABSTAIN_CURRENT

def recall_raw_factory(q):
    def recall_raw(kind, arg, kk):
        if kind == "fts": return beam_mod._fts_search_working(s, arg, k=kk)
        if kind == "vec":
            qemb = emb_mod.embed([arg])
            if qemb is None or not len(qemb): return []
            return beam_mod._wm_vec_search(s, qemb[0], k=kk)
        if kind == "imp": return j1p._imp_search(s, k=kk)
        if kind == "graph": return j1p._graph_lane_search(s, arg, kk)
        if kind == "get":
            r = s.execute("SELECT id, content, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
            if not r:
                r = s.execute("SELECT id, content, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
            return dict(r) if r else None
        return []
    return recall_raw

def build_pool(q, cap):
    pool = j1p.build_lane_pool(recall_raw_factory(q), q)
    pool = [p for p in pool if ((p.get("created_at") or "")[:10] < "2026-10-05")]
    return j1p._filter_and_rank(pool, q)[:cap]

CLIENT = _jev_client()
assert CLIENT
_API = getattr(CLIENT, "_jev_api", None)
_rot_i = getattr(CLIENT, "_jev_rotator", None)
if _rot_i is not None and hasattr(_rot_i, "_active"):
    _act = _rot_i._active()
    if len(_act) >= 2:
        CLIENT.headers["Authorization"] = f"Bearer {_act[1][1]}"
        sys.stderr.write(f"[start] {_act[1][0]}\n")

_LAST_CALL = [0.0]
def throttle():
    while True:
        now = time.time()
        if now - _LAST_CALL[0] >= 0.34:
            _LAST_CALL[0] = now
            return
        time.sleep(0.05)

def post(state, questions):
    rot = getattr(CLIENT, "_jev_rotator", None)
    for attempt in range(10):
        throttle()
        try:
            resp = CLIENT.post(_API, json={"state": state, "questions": questions, "model": "jev-latest"}, timeout=25)
            if resp.status_code == 429:
                body = resp.text or ""
                if "daily free allowance" in body or "resets at" in body:
                    try:
                        rot.exhausted_until[rot.last_key] = time.monotonic() + 3600
                    except Exception: pass
                if rot is not None and hasattr(rot, "on_429"):
                    try:
                        nk = rot.on_429()
                    except Exception:
                        nk = None
                    if nk:
                        CLIENT.headers["Authorization"] = f"Bearer {nk}"
                time.sleep(2.0)
                continue
            if resp.status_code == 503:
                time.sleep(3.0)
                continue
            return resp
        except Exception:
            time.sleep(2.0)
    return None

def run_pool20(q, rows):
    rows20 = rows[:20]
    labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150) or "n/a" for c in rows20]
    jl = labels + [ABSTAIN_CUR]
    st = j1p.build_state(q, rows20)
    qs = {"best": {"type": "choice", "instructions": m48.INSTR,
                   "criteria": {f"c{i}": jl[i] for i in range(len(jl))}}}
    resp = post(st, qs)
    if resp is None or resp.status_code != 200: return None, None, f"http{getattr(resp,'status_code',None)}"
    ans = (resp.json().get("answers") or {}).get("best") or {}
    probs = ans.get("probabilities") or {}
    ap = float(probs.get(f"c{len(jl)-1}", 0.0) or 0.0)
    try: idx = int(str(ans.get("choice")).lstrip("c"))
    except Exception: idx = None
    abstain = (idx is None) or (idx == len(jl)-1) or (ap > 0.3)
    return idx, abstain, None

# op-90
d45 = json.load(open(os.path.join(DATA, "stage45_abstain_label_snapshot.json"), encoding="utf-8"))
op = [(r["query"], r["gold_id"]) for r in d45["runs"][0]["records"] if r.get("grp") == "op"]
print(f"op-90: {len(op)}건 | pool20 3-run", flush=True)

pools = {k: build_pool(q, 60) for k, (q, g) in enumerate(op)}
print("pool 구성 완료", flush=True)

# gold pool rank (전체 60 기준, choice lift 전)
gold_pool_rank = {}
for k, (q, g) in enumerate(op):
    rk = next((i+1 for i, p in enumerate(pools[k]) if (p.get("id") or "")[:16] == (g or "")[:16]), None)
    gold_pool_rank[k] = rk

RUNS = 3
all_runs = []
t0 = time.time()
for run_i in range(RUNS):
    res = []
    for k, (q, g) in enumerate(op):
        idx, abst, err = run_pool20(q, pools[k])
        # pool20에서 lift 후 gold 순위: rows20 기준 gold 위치
        gold_after = None
        if not abst and err is None and gold_pool_rank[k] is not None:
            gp = gold_pool_rank[k]
            if gp <= 20:
                ci = idx
                gold_after = 1 if (ci == gp - 1) else (gp if gp <= ci else gp + 1)
            else:
                gold_after = None  # pool20 밖이라 회수 불가
        res.append({"q": q, "gold": g, "abstain": abst, "gold_after": gold_after, "err": err})
    all_runs.append(res)
    h1 = sum(1 for r in res if not r["err"] and not r["abstain"] and r["gold_after"] == 1)
    h3 = sum(1 for r in res if not r["err"] and not r["abstain"] and r["gold_after"] is not None and r["gold_after"] <= 3)
    abst_n = sum(1 for r in res if r["abstain"])
    err_n = sum(1 for r in res if r["err"])
    print(f"run{run_i+1}: hit@1={h1}/90 hit@3={h3}/90 abstain={abst_n} err={err_n} {time.time()-t0:.0f}s", flush=True)

# majority: 쿼리별 3-run 중 2회 이상 gold_after==1 (또는 2회 이상 abstain)
maj_h1 = maj_h3 = maj_abst = 0
for k in range(len(op)):
    hits1 = sum(1 for r in all_runs if r[k]["gold_after"] == 1 and not r[k]["err"])
    hits3 = sum(1 for r in all_runs if r[k]["gold_after"] is not None and r[k]["gold_after"] <= 3 and not r[k]["err"])
    absts = sum(1 for r in all_runs if r[k]["abstain"])
    if absts >= 2: maj_abst += 1
    elif hits1 >= 2: maj_h1 += 1; maj_h3 += 1
    elif hits3 >= 2: maj_h3 += 1
print(f"\nmajority(2/3): hit@1={maj_h1}/90 hit@3={maj_h3}/90 abstain={maj_abst}")

json.dump({"runs": all_runs, "majority": {"h1": maj_h1, "h3": maj_h3, "abstain": maj_abst}},
          open(os.path.join(DATA, "stage55_pool20_3run.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("\n저장: stage55_pool20_3run.json")