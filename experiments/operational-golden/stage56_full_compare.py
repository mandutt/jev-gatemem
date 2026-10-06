# -*- coding: utf-8 -*-
"""stage56: base vs pool20 풀 비교 (같은 세션 3-run each, paired, 2026-10-06, 540콜)

stage54(base 1-run 79/80) vs stage55(pool20 3-run 78/79)는 세션이 달라 비결정성 혼재.
같은 세션에서 두 구조를 각각 3-run으로 돌려 paired 비교:
- 쿼리별 base/pool20 hit 여부 직접 대조 (체계적 손실 vs 임의 손실)
- noans FP도 같은 세션 3-run으로 비교
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

def build_pool(q):
    pool = j1p.build_lane_pool(recall_raw_factory(q), q)
    pool = [p for p in pool if ((p.get("created_at") or "")[:10] < "2026-10-05")]
    return j1p._filter_and_rank(pool, q)[:j1p.POOL_BUDGET]

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

def run_choice(q, rows, cap):
    use = rows[:cap] if cap else rows
    labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150) or "n/a" for c in use]
    jl = labels + [ABSTAIN_CUR]
    st = j1p.build_state(q, use)
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

# ---- op-90 + noans ----
d45 = json.load(open(os.path.join(DATA, "stage45_abstain_label_snapshot.json"), encoding="utf-8"))
op = [(r["query"], r["gold_id"]) for r in d45["runs"][0]["records"] if r.get("grp") == "op"]
no = json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))
print(f"op-90 + noans-50 = {len(op)}+{len(no)}", flush=True)

op_pools = {k: build_pool(q) for k, (q, g) in enumerate(op)}
no_pools = {k: build_pool(n["query"]) for k, n in enumerate(no)}
print("pool 구성 완료", flush=True)

# op gold pool rank (전체 60)
gold_pool_rank = {}
for k, (q, g) in enumerate(op):
    rk = next((i+1 for i, p in enumerate(op_pools[k]) if (p.get("id") or "")[:16] == (g or "")[:16]), None)
    gold_pool_rank[k] = rk

RUNS = 3
out = {"op": [], "noans": []}
t0 = time.time()

# 구조별 3-run을 교차(interleaved)로 돌리는 대신 구조별 연속 — 세션 동일
for cond, cap in (("base", 60), ("pool20", 20)):
    for run_i in range(RUNS):
        op_recs = []
        for k, (q, g) in enumerate(op):
            idx, abst, err = run_choice(q, op_pools[k], cap)
            gold_after = None
            if not abst and err is None and gold_pool_rank[k] is not None:
                gp = gold_pool_rank[k]
                if cap == 60 or gp <= cap:
                    ci = idx
                    gold_after = 1 if (ci == gp - 1) else (gp if gp <= ci else gp + 1)
            op_recs.append({"q": q, "gold": g, "abstain": abst, "gold_after": gold_after, "err": err})
        h1 = sum(1 for r in op_recs if not r["err"] and not r["abstain"] and r["gold_after"] == 1)
        h3 = sum(1 for r in op_recs if not r["err"] and not r["abstain"] and r["gold_after"] is not None and r["gold_after"] <= 3)
        abst_n = sum(1 for r in op_recs if r["abstain"])
        # noans
        no_recs = []
        for k, n in enumerate(no):
            idx, abst, err = run_choice(n["query"], no_pools[k], cap)
            no_recs.append({"qid": n["qid"], "abstain": abst, "err": err})
        no_fp = sum(1 for r in no_recs if not r["err"] and not r["abstain"])
        out["op"].append({"cond": cond, "run": run_i+1, "h1": h1, "h3": h3, "abstain": abst_n, "records": op_recs})
        out["noans"].append({"cond": cond, "run": run_i+1, "fp": no_fp, "records": no_recs})
        print(f"{cond} run{run_i+1}: hit@1={h1}/90 hit@3={h3}/90 abstain={abst_n} noansFP={no_fp}/50 {time.time()-t0:.0f}s", flush=True)

json.dump(out, open(os.path.join(DATA, "stage56_full_compare.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("\n저장: stage56_full_compare.json")

# ---- paired 쿼리별 손실 집계 ----
base_runs = [r for r in out["op"] if r["cond"] == "base"]
p20_runs = [r for r in out["op"] if r["cond"] == "pool20"]
print("\n=== 쿼리별 대조 (3-run majority) ===")
base_maj = {}
for k in range(len(op)):
    hs = [r["records"][k] for r in base_runs]
    base_maj[k] = "H" if sum(1 for r in hs if r["gold_after"] == 1) >= 2 else ("A" if sum(1 for r in hs if r["abstain"]) >= 2 else "M")
p20_maj = {}
for k in range(len(op)):
    hs = [r["records"][k] for r in p20_runs]
    p20_maj[k] = "H" if sum(1 for r in hs if r["gold_after"] == 1) >= 2 else ("A" if sum(1 for r in hs if r["abstain"]) >= 2 else "M")
flip = {k: (base_maj[k], p20_maj[k]) for k in range(len(op)) if base_maj[k] != p20_maj[k]}
print(f"base와 다른 쿼리: {len(flip)}건")
for k, (b, p) in flip.items():
    print(f"  op#{k:02d} base={b} pool20={p} | {op[k][0][:40]}")
# noans paired
print("\n=== noans FP 쿼리별 ===")
no_base = sum(r["fp"] for r in out["noans"] if r["cond"] == "base") / 3
no_p20 = sum(r["fp"] for r in out["noans"] if r["cond"] == "pool20") / 3
print(f"base 평균 FP {no_base:.1f} vs pool20 평균 FP {no_p20:.1f}")