# -*- coding: utf-8 -*-
"""stage92: 사안 G 검증 — rule_q abstain 3-run 안정성 + 규칙 노출 제거 결합 (2026-10-07, ~600콜)

v5 사안 G의 검증 필요 항목:
1. rule_q abstain 판정 3-run 안정성 (live60, 같은 세션)
2. production-exact 라이브 paired (dual2 vs base) — 규칙 노출 제거 결합의 최종 지표

구조: rule_q(6) + fact_q(60) 1콜 2질문.
결합: rule_q abstain → 규칙 노출 제거 (fact 1개만 노출) / rule_q pick → 규칙 포함 (기존)
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

def run_dual2(q, pool):
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
        return None, None, None, f"http{getattr(resp,'status_code',None)}"
    ans = (resp.json().get("answers") or {})
    r_idx, r_abst, _ = parse_choice(ans.get("rule_q") or {}, len(rl))
    f_idx, f_abst, _ = parse_choice(ans.get("fact_q") or {}, len(fl))
    return r_idx, r_abst, f_idx, None

live_q = m48.load_queries(s)
d49c = json.load(open(os.path.join(DATA, "stage49c_label_booster_input.json"), encoding="utf-8"))
verdicts = json.load(open(r"C:\Users\mandu\Downloads\stage49c_label_booster_verdicts.json", encoding="utf-8"))
V2 = {"IRREL": "block", "PLAUS": "block", "NO": "block", "VALID": "valid", "YES": "yes"}
q_cls = {r["query"]: V2[verdicts[str(x["idx"])]] for r, x in zip(d49c, d49c)}
print(f"live60 | cls { {k: sum(1 for q in live_q if q_cls.get(q)==k) for k in ('block','valid','yes')} }", flush=True)

live_pool = {q: build_pool_prodex(q) for q in live_q}
print("pool 구성 완료", flush=True)

# 3-run
out = {"runs": []}
t0 = time.time()
for run_i in range(3):
    recs = []
    for q in live_q:
        r_idx, r_abst, f_idx, err = run_dual2(q, live_pool[q])
        recs.append({"query": q, "cls": q_cls.get(q), "r_abstain": r_abst,
                      "f_abstain": f_idx is None and err is None, "err": err})
    out["runs"].append(recs)
    blk = [r for r in recs if r["cls"] == "block"]
    blk_r = sum(1 for r in blk if r["r_abstain"])
    val = [r for r in recs if r["cls"] in ("valid", "yes")]
    val_r = sum(1 for r in val if r["r_abstain"])  # rule 오차단 (중요!)
    print(f"run{run_i+1}: block rule_q abstain {blk_r}/38 · valid/yes rule 오차단 {val_r}/22 · {time.time()-t0:.0f}s", flush=True)
    json.dump(out, open(os.path.join(DATA, "stage92_dual2_3run.json"), "w", encoding="utf-8"), ensure_ascii=False)

json.dump(out, open(os.path.join(DATA, "stage92_dual2_3run.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("\n완료 — 저장: stage92_dual2_3run.json")

# 안정성 분석
print("\n=== 3-run 안정성 ===")
blk_flip = 0
for i, q in enumerate(live_q):
    if q_cls.get(q) != "block": continue
    pat = [r[i]["r_abstain"] for r in out["runs"]]
    if len(set(pat)) > 1: blk_flip += 1
print(f"block rule abstain 플립 쿼리: {blk_flip}/38")
r_abst_avgs = [sum(1 for r in out["runs"][i] if r["cls"]=="block" and r["r_abstain"]) for i in range(3)]
print(f"block rule abstain: {r_abst_avgs} (평균 {sum(r_abst_avgs)/3:.1f}/38 = {100*sum(r_abst_avgs)/3/38:.0f}%)")
val_abst = [sum(1 for r in out["runs"][i] if r["cls"] in ("valid","yes") and r["r_abstain"]) for i in range(3)]
print(f"valid/yes rule 오차단: {val_abst} (평균 {sum(val_abst)/3:.1f}/22)")