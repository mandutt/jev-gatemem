# -*- coding: utf-8 -*-
"""stage87: 노출 k 실측 (2026-10-07, ~300콜)

b-ai·A AI 권장 — 노출 축소. stage57 0콜에서 hit@k k=2=k=5(80/90) 확인됨.
JEV 입력은 60개 동일, **렌더링 노출(상위 k)만 변경** — production-exact pool.

지표 (k=2 vs k=5):
- op: hit@1/3 (JEV lift는 동일해야 — 노출 k는 hit@1에 무영향 기대)
- live: block abstain / **오주입 노출 행 수** (핵심: k=2면 노출 수 60% 감소)
- noans: FP율 (노출 수 기준) — FP율 자체는 동일할 수 있음 (b-ai 경고)
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

def build_pool_prodex(q):
    pool = j1p.build_lane_pool(recall_raw_factory(q), q)
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

def run_choice(q, rows_all):
    labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150) or "n/a" for c in rows_all]
    jl = labels + [ABSTAIN_CUR]
    st = j1p.build_state(q, rows_all)
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

def lift_order(pool, pick_idx):
    """JEV 선택 후 노출 순서: 선택 1위 + 나머지 원순위 (top k)"""
    if pick_idx is None or pick_idx >= len(pool):
        return []
    picked = pool[pick_idx]
    rest = [p for i, p in enumerate(pool) if i != pick_idx]
    return [picked] + rest

# ---- 셋 ----
d45 = json.load(open(os.path.join(DATA, "stage45_abstain_label_snapshot.json"), encoding="utf-8"))
op = [(r["query"], r["gold_id"]) for r in d45["runs"][0]["records"] if r.get("grp") == "op"]
no = json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))
live_q = m48.load_queries(s)
d49c = json.load(open(os.path.join(DATA, "stage49c_label_booster_input.json"), encoding="utf-8"))
verdicts = json.load(open(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data\stage49c_label_booster_verdicts.json", encoding="utf-8"))
V2 = {"IRREL": "block", "PLAUS": "block", "NO": "block", "VALID": "valid", "YES": "yes"}
q_cls = {r["query"]: V2[verdicts[str(x["idx"])]] for r, x in zip(d49c, d49c)}
print(f"셋: op {len(op)} + noans {len(no)} + live {len(live_q)}", flush=True)

op_pool = {i: build_pool_prodex(q) for i, (q, g) in enumerate(op)}
op_gold_rank = {}
for i, (q, g) in enumerate(op):
    rk = next((j+1 for j, p in enumerate(op_pool[i]) if (p.get("id") or "")[:16] == (g or "")[:16]), None)
    op_gold_rank[i] = rk
no_pool = {n["query"]: build_pool_prodex(n["query"]) for n in no}
live_pool = {q: build_pool_prodex(q) for q in live_q}
print("pool 구성 완료", flush=True)

# ---- JEV 1회 호출, k는 해석만 다르게 (같은 결과 재사용) ----
out = {"k2": {"op": [], "noans": [], "live": []}, "k5": {"op": [], "noans": [], "live": []}}
t0 = time.time()

# op: JEV 호출 1회, gold_after는 lift 후 top-k 안인지
for i, (q, g) in enumerate(op):
    idx, abst, ap, err = run_choice(q, op_pool[i])
    gr = op_gold_rank[i]
    for k in (2, 5):
        gold_vis = None
        if not abst and err is None and gr is not None:
            gold_vis = (1 if idx == gr - 1 else (gr if gr <= idx else gr + 1))
        out[f"k{k}"]["op"].append({"i": i, "gold_rank": gr, "abstain": abst,
                                   "gold_vis": gold_vis, "err": err})

# noans: 노출 행 수 (abstain 아니면 k개 노출)
for n in no:
    q = n["query"]
    idx, abst, ap, err = run_choice(q, no_pool[q])
    for k in (2, 5):
        out[f"k{k}"]["noans"].append({"qid": n["qid"], "abstain": abst,
                                      "exposed": 0 if abst else k, "err": err})

# live: block abstain + 노출 행 수
for q in live_q:
    idx, abst, ap, err = run_choice(q, live_pool[q])
    for k in (2, 5):
        out[f"k{k}"]["live"].append({"query": q, "cls": q_cls.get(q), "abstain": abst,
                                     "exposed": 0 if abst else k, "err": err})

    if len(out["k2"]["live"]) == 30 or len(out["k2"]["live"]) == 60:
        print(f"live {len(out['k2']['live'])}/60 ({time.time()-t0:.0f}s)", flush=True)

json.dump(out, open(os.path.join(DATA, "stage87_exposure_k.json"), "w", encoding="utf-8"), ensure_ascii=False)

# ---- 요약 ----
print("\n=== 요약 ===")
for k in (2, 5):
    o = out[f"k{k}"]
    h1 = sum(1 for r in o["op"] if not r["err"] and not r["abstain"] and r["gold_vis"] == 1)
    h3 = sum(1 for r in o["op"] if not r["err"] and not r["abstain"] and r["gold_vis"] is not None and r["gold_vis"] <= 3)
    op_abst = sum(1 for r in o["op"] if r["abstain"])
    no_fp = sum(1 for r in o["noans"] if not r["err"] and not r["abstain"])
    no_exposed = sum(r["exposed"] for r in o["noans"])
    blk = [r for r in o["live"] if r["cls"] == "block"]
    blk_abst = sum(1 for r in blk if r["abstain"])
    blk_exposed = sum(r["exposed"] for r in blk)
    val = [r for r in o["live"] if r["cls"] in ("valid", "yes")]
    val_abst = sum(1 for r in val if r["abstain"])
    print(f"k={k}: op hit@1 {h1}/90 hit@3 {h3}/90 abstain {op_abst} · noans FP {no_fp}/50 (노출 {no_exposed}행) · "
          f"live block abstain {blk_abst}/38 · block 노출 {blk_exposed}행 · valid 오차단 {val_abst}/22")
print(f"\n완료 {time.time()-t0:.0f}s — 저장: stage87_exposure_k.json")