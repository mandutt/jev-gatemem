# -*- coding: utf-8 -*-
"""stage84: 후보 수 곡선 {5,10,20,40,60} (2026-10-07, 1000콜)

b-ai 제안 — abstain-후보수 관계 + pool20 판정을 한 번에.
200쿼리 (op90 + noans50 + live60) × k{5,10,20,40,60} = 1,000콜.
JEV 입력 후보 수만 변경 (production 60 기준). 같은 세션 1-run (곡선 목적 — 결정성은 stage83에서 확인).

지표: k별 op hit@1/hit@3/abstain, noans FP, live block abstain/valid 오차단.
"""
import os, sys, json, sqlite3, time
from collections import Counter

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
    use = rows[:k]
    labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150) or "n/a" for c in use]
    jl = labels + [ABSTAIN_CUR]
    st = j1p.build_state(q, use)
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
    chose_abstain = (idx == len(jl) - 1)
    abstain = chose_abstain or (ap > 0.3)
    return idx, abstain, ap, None

# ---- 셋 구성 ----
d45 = json.load(open(os.path.join(DATA, "stage45_abstain_label_snapshot.json"), encoding="utf-8"))
op = [(r["query"], r["gold_id"]) for r in d45["runs"][0]["records"] if r.get("grp") == "op"]
no = json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))
live_q = m48.load_queries(s)
d49c = json.load(open(os.path.join(DATA, "stage49c_label_booster_input.json"), encoding="utf-8"))
verdicts = json.load(open(r"C:\Users\mandu\Downloads\stage49c_label_booster_verdicts.json", encoding="utf-8"))
V2 = {"IRREL": "block", "PLAUS": "block", "NO": "block", "VALID": "valid", "YES": "yes"}
q_cls = {r["query"]: V2[verdicts[str(x["idx"])]] for r, x in zip(d49c, d49c)}
print(f"셋: op {len(op)} + noans {len(no)} + live {len(live_q)} = {len(op)+len(no)+len(live_q)}쿼리", flush=True)

# gold rank (op) — 전체 60 기준
op_pool = {k: build_pool(q) for k, (q, g) in enumerate(op)}
op_gold_rank = {}
for k, (q, g) in enumerate(op):
    rk = next((i+1 for i, p in enumerate(op_pool[k]) if (p.get("id") or "")[:16] == (g or "")[:16]), None)
    op_gold_rank[k] = rk

no_pool = {k: build_pool(n["query"]) for k, n in enumerate(no)}
live_pool = {q: build_pool(q) for q in live_q}
print("pool 구성 완료", flush=True)

# ---- 실행 ----
KS = [5, 10, 20, 40, 60]
all_res = {k: {"op": [], "noans": [], "live": []} for k in KS}
t0 = time.time()
total = 0
for k in KS:
    # op
    for i, (q, g) in enumerate(op):
        idx, abst, ap, err = run_choice(q, op_pool[i], k)
        gold_after = None
        if not abst and err is None and op_gold_rank[i] is not None:
            gr = op_gold_rank[i]
            if gr <= k:
                ci = idx
                gold_after = 1 if (ci == gr - 1) else (gr if gr <= ci else gr + 1)
        all_res[k]["op"].append({"i": i, "gold_rank": op_gold_rank[i], "abstain": abst, "gold_after": gold_after, "err": err})
    # noans
    for i, n in enumerate(no):
        idx, abst, ap, err = run_choice(n["query"], no_pool[i], k)
        all_res[k]["noans"].append({"abstain": abst, "err": err})
    # live
    for q in live_q:
        idx, abst, ap, err = run_choice(q, live_pool[q], k)
        all_res[k]["live"].append({"query": q, "cls": q_cls.get(q), "abstain": abst, "err": err})
    total += len(op) + len(no) + len(live_q)
    h1 = sum(1 for r in all_res[k]["op"] if not r["err"] and not r["abstain"] and r["gold_after"] == 1)
    h3 = sum(1 for r in all_res[k]["op"] if not r["err"] and not r["abstain"] and r["gold_after"] is not None and r["gold_after"] <= 3)
    op_abst = sum(1 for r in all_res[k]["op"] if r["abstain"])
    no_fp = sum(1 for r in all_res[k]["noans"] if not r["err"] and not r["abstain"])
    blk = [r for r in all_res[k]["live"] if r["cls"] == "block"]
    blk_abst = sum(1 for r in blk if r["abstain"])
    val = [r for r in all_res[k]["live"] if r["cls"] in ("valid", "yes")]
    val_abst = sum(1 for r in val if r["abstain"])
    print(f"k={k:2d}: op hit@1 {h1}/90 hit@3 {h3}/90 abstain {op_abst} · noans FP {no_fp}/50 · live block abstain {blk_abst}/38 · valid 오차단 {val_abst}/22 · {time.time()-t0:.0f}s", flush=True)
    json.dump(all_res, open(os.path.join(DATA, "stage84_candidate_curve.json"), "w", encoding="utf-8"), ensure_ascii=False)

json.dump(all_res, open(os.path.join(DATA, "stage84_candidate_curve.json"), "w", encoding="utf-8"), ensure_ascii=False)
print(f"\n완료 {total}콜, {time.time()-t0:.0f}s — 저장: stage84_candidate_curve.json")