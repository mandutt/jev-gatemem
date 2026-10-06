# -*- coding: utf-8 -*-
"""stage62: 오늘 모델 abstain 3-run 안정성 (2026-10-07, 180콜)

stage61 1-run: block abstain 36/38, abstain_p 중앙 0.86 — 어제(0.0)와 극단적 차이.
3-run 반복으로:
- abstain 행동이 안정적인지 (일시적 서버 상태 vs 영구)
- 쿼리별 abstain 일치율 (run 간 플립)
- 오차단(valid/yes) 2건이 매 run 재현되는지
"""
import os, sys, json, sqlite3, time, collections

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

def run_choice(q, rows):
    labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150) or "n/a" for c in rows[:5]]
    jl = labels + [ABSTAIN_CUR]
    st = j1p.build_state(q, rows[:5])
    qs = {"best": {"type": "choice", "instructions": INSTR,
                   "criteria": {f"c{i}": jl[i] for i in range(len(jl))}}}
    resp = post(st, qs)
    if resp is None or resp.status_code != 200:
        return None, None, f"http{getattr(resp,'status_code',None)}"
    ans = (resp.json().get("answers") or {}).get("best") or {}
    probs = ans.get("probabilities") or {}
    ap = float(probs.get(f"c{len(jl)-1}", 0.0) or 0.0)
    try: idx = int(str(ans.get("choice")).lstrip("c"))
    except Exception: idx = None
    chose_abstain = (idx == len(jl) - 1)
    abstain = chose_abstain or (ap > 0.3)
    return idx, abstain, ap, chose_abstain

queries = m48.load_queries(s)
d49c = json.load(open(os.path.join(DATA, "stage49c_label_booster_input.json"), encoding="utf-8"))
verdicts = json.load(open(r"C:\Users\mandu\Downloads\stage49c_label_booster_verdicts.json", encoding="utf-8"))
V2 = {"IRREL": "block", "PLAUS": "block", "NO": "block", "VALID": "valid", "YES": "yes"}
q_cls = {r["query"]: V2[verdicts[str(x["idx"])]] for r, x in zip(d49c, d49c)}

pools = {q: build_pool(q) for q in queries}
print(f"라이브 60 | cls { {k: sum(1 for q in queries if q_cls.get(q)==k) for k in ('block','valid','yes')} } | 3-run 시작", flush=True)

RUNS = 3
all_runs = []
t0 = time.time()
for run_i in range(RUNS):
    recs = []
    for q in queries:
        idx, abst, ap, chose = run_choice(q, pools[q])
        recs.append({"query": q, "cls": q_cls.get(q), "abstain": abst, "abstain_p": ap,
                     "choice_idx": idx, "chose_abstain": chose, "err": None})
    all_runs.append(recs)
    blk_abst = sum(1 for r in recs if r["cls"] == "block" and r["abstain"])
    val_abst = sum(1 for r in recs if r["cls"] in ("valid", "yes") and r["abstain"])
    aps = sorted(r["abstain_p"] for r in recs)
    print(f"run{run_i+1}: block abstain {blk_abst}/38 · valid+yes 오차단 {val_abst}/22 · ap med {aps[29]:.3f} ({time.time()-t0:.0f}s)", flush=True)

json.dump(all_runs, open(os.path.join(DATA, "stage62_3run_stability.json"), "w", encoding="utf-8"), ensure_ascii=False)

# 안정성: 쿼리별 abstain 일치도 (3-run 중 몇 번 abstain)
print("\n=== 쿼리별 abstain 일치 (3-run) ===")
flips = 0
for k in range(len(queries)):
    n_abst = sum(1 for r in all_runs if r[k]["abstain"])
    cls = all_runs[0][k]["cls"]
    if n_abst == 0:
        mark = "전부 pick"
    elif n_abst == 3:
        mark = "전부 abstain"
    else:
        mark = f"혼합 {n_abst}/3 (플립)"
        flips += 1
    if n_abst not in (0, 3):
        print(f"  {cls:5} {mark} | {queries[k][:45]}")
print(f"\n플립 쿼리: {flips}/60")

# 블록 차단율·오차단 3-run 평균
blk_absts = [sum(1 for r in run if r["cls"] == "block" and r["abstain"]) for run in all_runs]
val_absts = [sum(1 for r in run if r["cls"] in ("valid", "yes") and r["abstain"]) for run in all_runs]
print(f"block abstain 3-run: {blk_absts} (평균 {sum(blk_absts)/3:.1f}/38 = {sum(blk_absts)/3/38*100:.1f}%)")
print(f"valid+yes 오차단 3-run: {val_absts} (평균 {sum(val_absts)/3:.1f}/22)")

# 어제 대조 유지
aps48_all = []
print("\n저장: stage62_3run_stability.json")