# -*- coding: utf-8 -*-
"""stage86: candidate diversification JEV 검증 (2026-10-07, ~450콜)

c-ai·a-ai 제안 — 규칙/사실 슬롯 분리. 0콜 시뮬 결과:
- rule_cap=1: gold top5 70/90 · cap=2: 61 · cap=3: 47 · cap=5(현행): 19
- live60: 54/60 쿼리가 규칙 4개+ 도배

JEV 검증: rule cap {1,2,3} × (live60 + op90) — base(현행, cap 무제한) 포함.
같은 세션 1-run. production-exact pool (시간 필터 없음). JEV 입력은 상위 5개 (슬롯 구성 후).

지표: op hit@1/3/abstain · live block abstain/valid 오차단
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
RULE_IDS = {"d1c90516d9870c95", "2ecef73164830638", "9f04ed2c8e14f11b",
            "5a3ebc06a87940da", "a13019e1f438960c", "1cef4743165b7707"}

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

def build_slot_exposure(pool, rule_cap):
    """노출 상위 5개만 슬롯 구성 (규칙 cap) — JEV 입력은 pool 60 전체 유지"""
    exposed = []
    rule_cnt = 0
    for p in pool:
        if (p.get("id") or "")[:16] in RULE_IDS:
            if rule_cnt >= rule_cap: continue
            rule_cnt += 1
        exposed.append(p)
        if len(exposed) >= 5: break
    return exposed

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

def run_choice(q, rows_all, exposure):
    """JEV에는 rows_all(60) 전체 전달, 노출/선택 해석은 exposure(5) 기준"""
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

# ---- 셋 ----
d45 = json.load(open(os.path.join(DATA, "stage45_abstain_label_snapshot.json"), encoding="utf-8"))
op = [(r["query"], r["gold_id"]) for r in d45["runs"][0]["records"] if r.get("grp") == "op"]
live_q = m48.load_queries(s)
d49c = json.load(open(os.path.join(DATA, "stage49c_label_booster_input.json"), encoding="utf-8"))
verdicts = json.load(open(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data\stage49c_label_booster_verdicts.json", encoding="utf-8"))
V2 = {"IRREL": "block", "PLAUS": "block", "NO": "block", "VALID": "valid", "YES": "yes"}
q_cls = {r["query"]: V2[verdicts[str(x["idx"])]] for r, x in zip(d49c, d49c)}
print(f"셋: op {len(op)} + live {len(live_q)}", flush=True)

op_pool = {i: build_pool_prodex(q) for i, (q, g) in enumerate(op)}
op_gold_rank = {}
for i, (q, g) in enumerate(op):
    rk = next((j+1 for j, p in enumerate(op_pool[i]) if (p.get("id") or "")[:16] == (g or "")[:16]), None)
    op_gold_rank[i] = rk
live_pool = {q: build_pool_prodex(q) for q in live_q}
print("pool 구성 완료", flush=True)

# ---- 실행: base(cap=99) + cap{1,2,3} ----
CONDS = [("base", 99), ("cap1", 1), ("cap2", 2), ("cap3", 3)]
out = {}
t0 = time.time()
for cname, cap in CONDS:
    op_recs = []
    for i, (q, g) in enumerate(op):
        exposure = build_slot_exposure(op_pool[i], cap)
        idx, abst, ap, err = run_choice(q, op_pool[i], exposure)
        gr = op_gold_rank[i]
        gold_after = None
        if not abst and err is None and gr is not None:
            # ★ stage56 표준 lift 로직: 60-pool 기준, JEV가 gold를 고르면 1위
            ci = idx
            if ci == gr - 1:
                gold_after = 1
            else:
                gold_after = gr if gr <= ci else gr + 1
        op_recs.append({"i": i, "gold_rank": gr, "choice_idx": idx, "abstain": abst, "gold_after": gold_after, "err": err})
    live_recs = []
    for q in live_q:
        exposure = build_slot_exposure(live_pool[q], cap)
        idx, abst, ap, err = run_choice(q, live_pool[q], exposure)
        live_recs.append({"query": q, "cls": q_cls.get(q), "abstain": abst, "err": err})
    h1 = sum(1 for r in op_recs if not r["err"] and not r["abstain"] and r["gold_after"] == 1)
    h3 = sum(1 for r in op_recs if not r["err"] and not r["abstain"] and r["gold_after"] is not None and r["gold_after"] <= 3)
    op_abst = sum(1 for r in op_recs if r["abstain"])
    blk = [r for r in live_recs if r["cls"] == "block"]
    blk_abst = sum(1 for r in blk if r["abstain"])
    val = [r for r in live_recs if r["cls"] in ("valid", "yes")]
    val_abst = sum(1 for r in val if r["abstain"])
    out[cname] = {"op": op_recs, "live": live_recs}
    print(f"{cname}: op hit@1 {h1}/90 hit@3 {h3}/90 abstain {op_abst} · live block abstain {blk_abst}/38 · valid 오차단 {val_abst}/22 · {time.time()-t0:.0f}s", flush=True)
    json.dump(out, open(os.path.join(DATA, "stage86_diversification.json"), "w", encoding="utf-8"), ensure_ascii=False)

json.dump(out, open(os.path.join(DATA, "stage86_diversification.json"), "w", encoding="utf-8"), ensure_ascii=False)
print(f"\n완료 {time.time()-t0:.0f}s — 저장: stage86_diversification.json")