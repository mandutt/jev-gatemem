# -*- coding: utf-8 -*-
"""stage90: k=2 + IDF v2 조합 실측 (2026-10-07, ~300콜)

사안 A(k=2) + 사안 B(IDF v2) 병행 검증. JEV 입력 60개 동일, 노출만 조작.

IDF v2 규칙 (stage57 top5-any, 0콜 결과 12구제·0오차단 기반):
- 쿼리에서 식별자 추출: [a-zA-Z0-9_]+_[a-zA-Z0-9_]+ | [a-zA-Z0-9]+\.[a-zA-Z0-9]+ | \b[A-Z][A-Z0-9_]{2,}\b
- 쿼리에 식별자가 있고, 노출(2개) 원문 전부에 해당 식별자가 없으면 → [LOW_SPEC] 경고 (노출 유지, 메타만)
- (반영: 노출 유지 + 경고 = soft warning — a-ai 설계)

조건: base(k5) vs k2 vs k2+idf
지표: op hit@1/3, noans FP, live block 노출 행 수, IDF 발동 횟수, 오차단
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
INSTR = m48.INSTR

# IDF v2: 형태 기반 식별자 정규식
IDF_RE = re.compile(r"([a-zA-Z0-9_]+_[a-zA-Z0-9_]+|[a-zA-Z0-9]+\.[a-zA-Z0-9]+)")

def query_identifiers(q):
    return set(m.group(1).lower() for m in IDF_RE.finditer(q))

def exposure_ids(exposure):
    return " ".join((c.get("content") or "") for c in exposure).lower()

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
    if pick_idx is None or pick_idx >= len(pool):
        return []
    picked = pool[pick_idx]
    rest = [p for i, p in enumerate(pool) if i != pick_idx]
    return [picked] + rest

def idf_flag(q, exposure):
    """IDF v2: 쿼리 식별자가 노출 원문 전부에 없으면 True (soft warning)"""
    ids = query_identifiers(q)
    if not ids: return False
    blob = exposure_ids(exposure)
    return not any(i in blob for i in ids)

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

# ---- 실행: JEV 1회 호출 (60 후보), 노출/IDF는 해석 ----
CONDS = ["k5", "k2", "k2+idf"]
out = {c: {"op": [], "noans": [], "live": []} for c in CONDS}
t0 = time.time()

for i, (q, g) in enumerate(op):
    idx, abst, ap, err = run_choice(q, op_pool[i])
    gr = op_gold_rank[i]
    exposed5 = lift_order(op_pool[i], idx)
    for c in CONDS:
        if c == "k5":
            exp = exposed5[:5]
            flag = False
        elif c == "k2":
            exp = exposed5[:2]
            flag = False
        else:  # k2+idf
            exp = exposed5[:2]
            flag = idf_flag(q, exp)
        gold_vis = None
        if not abst and err is None and gr is not None:
            ci = idx
            gold_vis = 1 if (ci == gr - 1) else (gr if gr <= ci else gr + 1)
            # 노출 k 안에 gold가 있는지 (hit@k)
            exp_ids = [(p.get("id") or "")[:16] for p in exp]
            if (g or "")[:16] not in exp_ids:
                gold_vis = None  # 노출 밖 — miss
        out[c]["op"].append({"i": i, "gold_rank": gr, "abstain": abst, "gold_vis": gold_vis,
                              "idf_flag": flag, "err": err})

for n in no:
    q = n["query"]
    idx, abst, ap, err = run_choice(q, no_pool[q])
    exposed5 = lift_order(no_pool[q], idx)
    for c in CONDS:
        if c == "k5":
            exp = exposed5[:5]; flag = False
        elif c == "k2":
            exp = exposed5[:2]; flag = False
        else:
            exp = exposed5[:2]; flag = idf_flag(q, exp)
        out[c]["noans"].append({"qid": n["qid"], "abstain": abst, "exposed": 0 if abst else len(exp),
                                 "idf_flag": flag, "err": err})

for q in live_q:
    idx, abst, ap, err = run_choice(q, live_pool[q])
    exposed5 = lift_order(live_pool[q], idx)
    for c in CONDS:
        if c == "k5":
            exp = exposed5[:5]; flag = False
        elif c == "k2":
            exp = exposed5[:2]; flag = False
        else:
            exp = exposed5[:2]; flag = idf_flag(q, exp)
        out[c]["live"].append({"query": q, "cls": q_cls.get(q), "abstain": abst,
                                "exposed": 0 if abst else len(exp), "idf_flag": flag, "err": err})

json.dump(out, open(os.path.join(DATA, "stage90_k2_idf.json"), "w", encoding="utf-8"), ensure_ascii=False)

# ---- 요약 ----
print("\n=== 요약 ===")
for c in CONDS:
    o = out[c]
    h1 = sum(1 for r in o["op"] if not r["err"] and not r["abstain"] and r["gold_vis"] == 1)
    h3 = sum(1 for r in o["op"] if not r["err"] and not r["abstain"] and r["gold_vis"] is not None and r["gold_vis"] <= 3)
    op_abst = sum(1 for r in o["op"] if r["abstain"])
    no_fp = sum(1 for r in o["noans"] if not r["err"] and not r["abstain"])
    no_exposed = sum(r["exposed"] for r in o["noans"])
    blk = [r for r in o["live"] if r["cls"] == "block"]
    blk_abst = sum(1 for r in blk if r["abstain"])
    blk_exposed = sum(r["exposed"] for r in blk)
    idf_n = sum(1 for r in o["live"] if r["idf_flag"])
    val = [r for r in o["live"] if r["cls"] in ("valid", "yes")]
    val_abst = sum(1 for r in val if r["abstain"])
    print(f"{c:7}: op hit@1 {h1}/90 hit@3 {h3}/90 abstain {op_abst} · noans FP {no_fp}/50 (노출 {no_exposed}) · "
          f"live block abstain {blk_abst}/38 노출 {blk_exposed}행 · IDF 발동 {idf_n}/60 · valid 오차단 {val_abst}/22")
print(f"\n완료 {time.time()-t0:.0f}s — 저장: stage90_k2_idf.json")