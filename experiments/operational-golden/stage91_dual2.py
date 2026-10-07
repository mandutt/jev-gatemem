# -*- coding: utf-8 -*-
"""stage91: 2질문 2단 구조 실측 (2026-10-07, ~200콜)

stage89 후속 변형 (a): rule_q abstain 가능 + fact_q에 60개 전체 제공.

결합 규칙:
- rule_q abstain AND fact_q abstain → 빈 컨텍스트 (무답)
- rule_q abstain + fact_q pick → fact winner (rule abstain = 규칙 무관, 사실로만)
- rule_q pick + fact_q 아무거나 → rule winner (기존 base와 유사 — 규칙 답 우선)
- (노출: winner 1개 + 상위 4 보조 — k2/k5는 해석만)

비교: base(현행 1콜 60) vs dual2(1콜 2질문: rule6 + fact60)
지표: op hit@1/3 (fact_q winner 기준), live block abstain(rule_q), noans FP
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

def parse_choice(ans, n):
    probs = ans.get("probabilities") or {}
    try: idx = int(str(ans.get("choice")).lstrip("c"))
    except Exception: idx = None
    ap = float(probs.get(f"c{n-1}", 0.0) or 0.0)
    chose_abstain = (idx == n - 1)
    abstain = chose_abstain or (ap > 0.3)
    return idx, abstain, ap

def run_base(q, pool):
    labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150) or "n/a" for c in pool]
    jl = labels + [ABSTAIN_CUR]
    st = j1p.build_state(q, pool)
    qs = {"best": {"type": "choice", "instructions": INSTR,
                   "criteria": {f"c{i}": jl[i] for i in range(len(jl))}}}
    resp = post(st, qs)
    if resp is None or resp.status_code != 200:
        return None, None, f"http{getattr(resp,'status_code',None)}"
    ans = (resp.json().get("answers") or {}).get("best") or {}
    idx, abst, _ = parse_choice(ans, len(jl))
    return idx, abst, None

def run_dual2(q, pool):
    """2단: rule_q(6) + fact_q(60) — 사실에 전체를 줌"""
    rules = [p for p in pool if (p.get("id") or "")[:16] in RULE_IDS][:6]
    rl = [j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150) or "n/a" for c in rules] + [ABSTAIN_CUR]
    fl = [j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150) or "n/a" for c in pool] + [ABSTAIN_CUR]
    st = j1p.build_state(q, pool)
    qs = {
        "rule_q": {"type": "choice", "instructions": "규칙/지침 질문: 아래 후보 중 가장 관련 있는 규칙을 고르세요.",
                   "criteria": {f"c{i}": rl[i] for i in range(len(rl))}},
        "fact_q": {"type": "choice", "instructions": INSTR,
                   "criteria": {f"c{i}": fl[i] for i in range(len(fl))}},
    }
    resp = post(st, qs)
    if resp is None or resp.status_code != 200:
        return None, None, None, None, None, f"http{getattr(resp,'status_code',None)}"
    ans = (resp.json().get("answers") or {})
    r_ans = ans.get("rule_q") or {}
    f_ans = ans.get("fact_q") or {}
    r_idx, r_abst, r_ap = parse_choice(r_ans, len(rl))
    f_idx, f_abst, f_ap = parse_choice(f_ans, len(fl))
    return r_idx, r_abst, f_idx, f_abst, {"r_ap": r_ap, "f_ap": f_ap}, None

# ---- 셋 ----
d45 = json.load(open(os.path.join(DATA, "stage45_abstain_label_snapshot.json"), encoding="utf-8"))
op = [(r["query"], r["gold_id"]) for r in d45["runs"][0]["records"] if r.get("grp") == "op"]
no = json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))
live_q = m48.load_queries(s)
d49c = json.load(open(os.path.join(DATA, "stage49c_label_booster_input.json"), encoding="utf-8"))
verdicts = json.load(open(r"C:\Users\mandu\Downloads\stage49c_label_booster_verdicts.json", encoding="utf-8"))
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

out = {"base": {"op": [], "noans": [], "live": []},
       "dual2": {"op": [], "noans": [], "live": []}}
t0 = time.time()

for i, (q, g) in enumerate(op):
    idx, abst, err = run_base(q, op_pool[i])
    gr = op_gold_rank[i]
    gold_after = None
    if not abst and err is None and gr is not None:
        ci = idx
        gold_after = 1 if (ci == gr - 1) else (gr if gr <= ci else gr + 1)
    out["base"]["op"].append({"i": i, "abstain": abst, "gold_after": gold_after, "err": err})
    r_idx, r_abst, f_idx, f_abst, extra, err2 = run_dual2(q, op_pool[i])
    f_gold_hit = None
    if not f_abst and err2 is None and gr is not None:
        ci = f_idx
        f_gold_hit = 1 if (ci == gr - 1) else (gr if gr <= ci else gr + 1)
    # 결합: rule abstain + fact pick → fact 기준 / rule pick → rule 기준 (f_gold_hit 유지하되 abstain_all만 체크)
    abstain_all = r_abst and f_abst
    out["dual2"]["op"].append({"i": i, "r_abstain": r_abst, "f_abstain": f_abst,
                                "f_gold_hit": f_gold_hit, "abstain_all": abstain_all, "err": err2})
    if (i+1) % 20 == 0:
        print(f"op {i+1}/90 ({time.time()-t0:.0f}s)", flush=True)

for n in no:
    q = n["query"]
    idx, abst, err = run_base(q, no_pool[q])
    out["base"]["noans"].append({"qid": n["qid"], "abstain": abst, "err": err})
    r_idx, r_abst, f_idx, f_abst, extra, err2 = run_dual2(q, no_pool[q])
    out["dual2"]["noans"].append({"qid": n["qid"], "r_abstain": r_abst, "f_abstain": f_abst,
                                   "abstain_all": r_abst and f_abst, "err": err2})

for q in live_q:
    idx, abst, err = run_base(q, live_pool[q])
    out["base"]["live"].append({"query": q, "cls": q_cls.get(q), "abstain": abst, "err": err})
    r_idx, r_abst, f_idx, f_abst, extra, err2 = run_dual2(q, live_pool[q])
    out["dual2"]["live"].append({"query": q, "cls": q_cls.get(q), "r_abstain": r_abst,
                                  "f_abstain": f_abst, "abstain_all": r_abst and f_abst, "err": err2})

json.dump(out, open(os.path.join(DATA, "stage91_dual2.json"), "w", encoding="utf-8"), ensure_ascii=False)

# ---- 요약 ----
print("\n=== 요약 ===")
b_op = out["base"]["op"]
b_h1 = sum(1 for r in b_op if not r["err"] and not r["abstain"] and r["gold_after"] == 1)
b_abst = sum(1 for r in b_op if r["abstain"])
b_no_fp = sum(1 for r in out["base"]["noans"] if not r["err"] and not r["abstain"])
b_blk = [r for r in out["base"]["live"] if r["cls"] == "block"]
b_blk_abst = sum(1 for r in b_blk if r["abstain"])
print(f"base: op hit@1 {b_h1}/90 abstain {b_abst} · noans FP {b_no_fp}/50 · live block abstain {b_blk_abst}/38")
d_op = out["dual2"]["op"]
d_h1 = sum(1 for r in d_op if not r["err"] and not r["abstain_all"] and r["f_gold_hit"] == 1)
d_abst_all = sum(1 for r in d_op if r["abstain_all"])
d_no_fp = sum(1 for r in out["dual2"]["noans"] if not r["err"] and not r["abstain_all"])
d_blk = [r for r in out["dual2"]["live"] if r["cls"] == "block"]
d_blk_abst = sum(1 for r in d_blk if r["abstain_all"])
d_blk_r = sum(1 for r in d_blk if r["r_abstain"])
d_blk_f = sum(1 for r in d_blk if r["f_abstain"])
print(f"dual2: op hit@1 {d_h1}/90 abstain_all {d_abst_all} · noans FP {d_no_fp}/50 · live block abstain {d_blk_abst}/38")
print(f"dual2 live block: rule_q abstain {d_blk_r}/38 · fact_q abstain {d_blk_f}/38")
print(f"\n완료 {time.time()-t0:.0f}s — 저장: stage91_dual2.json")