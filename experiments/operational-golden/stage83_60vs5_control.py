# -*- coding: utf-8 -*-
"""stage83: 60-candidate vs 5-candidate control, live60, 같은 세션 3-run (2026-10-07, 360콜)

3종 AI v4 검토(c-ai 필수) — 10-06(abstain 0/60, 60 후보) vs 10-07(abstain 36/38, 5 후보)의
confound를 분리한다. 같은 스냅샷·같은 쿼리·같은 프롬프트·같은 세션에서 JEV 입력 후보 수만 60/5로 변경.

결과 해석:
- 60도 abstain 많으면 → 모델/서버 변경이 진짜 (모델 버전 고정 선행)
- 60=0/5=36이면 → 후보 수 효과가 abstain 유발 (candidate composition 레버 확정)
"""
import os, sys, json, sqlite3, time

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
INSTR = m48.INSTR

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

def build_pool(q):
    pool = j1p.build_lane_pool(recall_raw_factory(q), q)
    pool = [p for p in pool if ((p.get("created_at") or "")[:10] < "2026-10-05")]
    return j1p._filter_and_rank(pool, q)[:60]

CLIENT = _jev_client(); assert CLIENT
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
            _LAST_CALL[0] = now; return
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
                    try: nk = rot.on_429()
                    except Exception: nk = None
                    if nk: CLIENT.headers["Authorization"] = f"Bearer {nk}"
                time.sleep(2.0); continue
            if resp.status_code == 503:
                time.sleep(3.0); continue
            return resp
        except Exception:
            time.sleep(2.0)
    return None

def run_choice(q, rows, k):
    use = rows[:k]  # ★ confound 변수: k=60 (production) vs k=5 (실험)
    labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150) or "n/a" for c in use]
    jl = labels + [ABSTAIN_CUR]
    st = j1p.build_state(q, use)
    qs = {"best": {"type": "choice", "instructions": INSTR,
                   "criteria": {f"c{i}": jl[i] for i in range(len(jl))}}}
    resp = post(st, qs)
    if resp is None or resp.status_code != 200:
        return None, None, None, None, f"http{getattr(resp,'status_code',None)}"
    ans = (resp.json().get("answers") or {}).get("best") or {}
    probs = ans.get("probabilities") or {}
    ap = float(probs.get(f"c{len(jl)-1}", 0.0) or 0.0)
    try: idx = int(str(ans.get("choice")).lstrip("c"))
    except Exception: idx = None
    chose_abstain = (idx == len(jl) - 1)
    abstain = chose_abstain or (ap > 0.3)
    return idx, abstain, ap, chose_abstain, None

queries = m48.load_queries(s)
d49c = json.load(open(os.path.join(DATA, "stage49c_label_booster_input.json"), encoding="utf-8"))
verdicts = json.load(open(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data\stage49c_label_booster_verdicts.json", encoding="utf-8"))
V2 = {"IRREL": "block", "PLAUS": "block", "NO": "block", "VALID": "valid", "YES": "yes"}
q_cls = {r["query"]: V2[verdicts[str(x["idx"])]] for r, x in zip(d49c, d49c)}
from collections import Counter
print(f"라이브 60 | cls {dict(Counter(q_cls.get(q) for q in queries))}", flush=True)

pools = {q: build_pool(q) for q in queries}
print("pool 구성 완료 (60)", flush=True)

RUNS = 3
out = {"conditions": ["k60", "k5"], "runs": []}
t0 = time.time()
for run_i in range(RUNS):
    row = {"run": run_i + 1}
    for cond, k in (("k60", 60), ("k5", 5)):
        recs = []
        for q in queries:
            idx, abst, ap, chose, err = run_choice(q, pools[q], k)
            recs.append({"query": q, "cls": q_cls.get(q), "k": k, "abstain": abst,
                         "abstain_p": ap, "choice_idx": idx, "chose_abstain": chose, "err": err})
        blk_abst = sum(1 for r in recs if r["cls"] == "block" and r["abstain"])
        blk_n = sum(1 for r in recs if r["cls"] == "block")
        val_abst = sum(1 for r in recs if r["cls"] in ("valid", "yes") and r["abstain"])
        val_n = sum(1 for r in recs if r["cls"] in ("valid", "yes"))
        aps = sorted(r["abstain_p"] or 0 for r in recs)
        row[cond] = {"block_abstain": blk_abst, "block_n": blk_n,
                     "valid_abstain": val_abst, "valid_n": val_n,
                     "ap_med": aps[len(aps)//2], "chose_abstain": sum(1 for r in recs if r["chose_abstain"]),
                     "err": sum(1 for r in recs if r["err"]), "records": recs}
        print(f"run{run_i+1} {cond}: block abstain {blk_abst}/{blk_n} · valid+yes 오차단 {val_abst}/{val_n} · ap med {aps[len(aps)//2]:.2f} ({time.time()-t0:.0f}s)", flush=True)
    out["runs"].append(row)
    json.dump(out, open(os.path.join(DATA, "stage83_60vs5_control.json"), "w", encoding="utf-8"), ensure_ascii=False)

json.dump(out, open(os.path.join(DATA, "stage83_60vs5_control.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("\n저장: stage83_60vs5_control.json")
print("\n=== 최종 요약 (3-run 평균) ===")
for cond in ("k60", "k5"):
    rows = [r[cond] for r in out["runs"]]
    ba = [r["block_abstain"] for r in rows]; va = [r["valid_abstain"] for r in rows]
    print(f"{cond}: block abstain {ba} (평균 {sum(ba)/3:.1f}/{rows[0]['block_n']}) · valid+yes 오차단 {va}")
print("\n해석: k60 abstain 많으면 모델 변경 / k60=0·k5=36이면 후보 수 효과")