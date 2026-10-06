# -*- coding: utf-8 -*-
"""stage63: 오늘 모델 op-90 + noans-50 회귀 (2026-10-07, 140콜)

stage61/62: 오늘 모델에서 abstain 강화 (block 94.7% 차단, 3-run 결정적).
이제 op-90(정답 셋)과 noans-50(하드 무답)에 적용해:
- op: WHY·원인 질문이 abstain으로 오차단되는지 (hit@1/3)
- noans hard: FP가 abstain으로 더 줄어드는지
어제 stage54/56과 동일 조건 (base k5, current 라벨, 시간 필터, 스냅샷).
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
        return None, None, None, f"http{getattr(resp,'status_code',None)}"
    ans = (resp.json().get("answers") or {}).get("best") or {}
    probs = ans.get("probabilities") or {}
    ap = float(probs.get(f"c{len(jl)-1}", 0.0) or 0.0)
    try: idx = int(str(ans.get("choice")).lstrip("c"))
    except Exception: idx = None
    abstain = (idx == len(jl)-1) or (ap > 0.3)
    return idx, abstain, ap, None

# op-90
d45 = json.load(open(os.path.join(DATA, "stage45_abstain_label_snapshot.json"), encoding="utf-8"))
op = [(r["query"], r["gold_id"]) for r in d45["runs"][0]["records"] if r.get("grp") == "op"]
no = json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))
print(f"op-90 + noans-50 = {len(op)}+{len(no)}", flush=True)

op_pools = {k: build_pool(q) for k, (q, g) in enumerate(op)}
no_pools = {k: build_pool(n["query"]) for k, n in enumerate(no)}
print("pool 구성 완료", flush=True)

gold_pool_rank = {}
for k, (q, g) in enumerate(op):
    rk = next((i+1 for i, p in enumerate(op_pools[k]) if (p.get("id") or "")[:16] == (g or "")[:16]), None)
    gold_pool_rank[k] = rk

def gold_after(gp, idx):
    if gp is None: return None
    if idx is None or not isinstance(idx, int): return gp
    return 1 if idx == gp - 1 else (gp if gp <= idx else gp + 1)

t0 = time.time()
op_recs = []
for k, (q, g) in enumerate(op):
    idx, abst, ap, err = run_choice(q, op_pools[k])
    ga = gold_after(gold_pool_rank[k], idx) if not abst and err is None else None
    op_recs.append({"query": q, "gold": g, "abstain": abst, "abstain_p": ap, "gold_after": ga, "err": err})
h1 = sum(1 for r in op_recs if r["gold_after"] == 1)
h3 = sum(1 for r in op_recs if r["gold_after"] is not None and r["gold_after"] <= 3)
abst_n = sum(1 for r in op_recs if r["abstain"] and not r["err"])
err_n = sum(1 for r in op_recs if r["err"])
print(f"op-90: hit@1 {h1} · hit@3 {h3} · abstain {abst_n} · err {err_n} ({time.time()-t0:.0f}s)", flush=True)

no_recs = []
for k, n in enumerate(no):
    idx, abst, ap, err = run_choice(n["query"], no_pools[k])
    no_recs.append({"qid": n["qid"], "abstain": abst, "abstain_p": ap, "err": err})
no_fp = sum(1 for r in no_recs if not r["err"] and not r["abstain"])
no_abst = sum(1 for r in no_recs if r["abstain"] and not r["err"])
print(f"noans-50: FP {no_fp}/50 · abstain {no_abst}/50 · err {err_n}", flush=True)

json.dump({"op": op_recs, "noans": no_recs}, open(os.path.join(DATA, "stage63_op_noans_regress.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("\n저장: stage63_op_noans_regress.json")

# abstain된 op 쿼리 (핵심 — WHY 오차단 여부)
print("\n=== op에서 abstain된 쿼리 ===")
for r in op_recs:
    if r["abstain"] and not r["err"]:
        print(f"  ap={r['abstain_p']:.2f} | {r['query'][:55]}")

# 어제와 대조
print("\n=== 어제(10-06) 대조 ===")
print("op: base 78/79/abstain2-3 (stage56) · noans FP 21.3 (stage56)")