# -*- coding: utf-8 -*-
"""stage85: production-exact pool20 게이트 (2026-10-07, 360콜 + 0콜 체크)

C AI 최종 게이트:
1. production-exact pool (시간 필터 제거 — created_at<10-05 없음, 데몬과 동일)
2. op90 gold rank>20 1건 이상 → pool20 전면 채택 금지 (0콜 체크)
3. live60 × {k=60, k=20} × 3-run paired (360콜) — answer-protect 추가 희생 0 확인

지표: k별 live block abstain / valid+yes 오차단 / yes회수(gold top5 노출) / noans FP(별도 50)
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

def build_pool_prodex(q):
    """production-exact: 시간 필터 없음 (데몬과 동일)"""
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

# ==== 0콜 체크: op90 gold rank (production-exact pool) ====
print("=== 0콜: op90 gold rank (production-exact) ===", flush=True)
d45 = json.load(open(os.path.join(DATA, "stage45_abstain_label_snapshot.json"), encoding="utf-8"))
op = [(r["query"], r["gold_id"]) for r in d45["runs"][0]["records"] if r.get("grp") == "op"]
gt20 = []
for q, g in op:
    pool = build_pool_prodex(q)
    rk = next((i+1 for i, p in enumerate(pool) if (p.get("id") or "")[:16] == (g or "")[:16]), None)
    if rk is not None and rk > 20:
        gt20.append((q, rk))
    elif rk is None:
        gt20.append((q, "MISS"))
print(f"op90: rank>20 또는 MISS {len(gt20)}건:")
for q, rk in gt20:
    print(f"  rank={rk} | {q[:60]}")
print(flush=True)

# ==== live60 + noans50 셋 ====
live_q = m48.load_queries(s)
d49c = json.load(open(os.path.join(DATA, "stage49c_label_booster_input.json"), encoding="utf-8"))
verdicts = json.load(open(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data\stage49c_label_booster_verdicts.json", encoding="utf-8"))
V2 = {"IRREL": "block", "PLAUS": "block", "NO": "block", "VALID": "valid", "YES": "yes"}
q_cls = {r["query"]: V2[verdicts[str(x["idx"])]] for r, x in zip(d49c, d49c)}
no = json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))
print(f"셋: live {len(live_q)} + noans {len(no)}", flush=True)

live_pool = {q: build_pool_prodex(q) for q in live_q}
no_pool = {n["query"]: build_pool_prodex(n["query"]) for n in no}
print("pool 구성 완료 (production-exact)", flush=True)

# ==== 360콜: live60 × {60,20} × 3-run paired ====
out = {"runs": []}
t0 = time.time()
for run_i in range(3):
    row = {"run": run_i + 1}
    for cond, k in (("k60", 60), ("k20", 20)):
        recs = []
        for q in live_q:
            idx, abst, ap, err = run_choice(q, live_pool[q], k)
            recs.append({"query": q, "cls": q_cls.get(q), "k": k, "abstain": abst, "abstain_p": ap, "err": err})
        blk = [r for r in recs if r["cls"] == "block"]
        val = [r for r in recs if r["cls"] in ("valid", "yes")]
        blk_abst = sum(1 for r in blk if r["abstain"])
        val_abst = sum(1 for r in val if r["abstain"])
        row[cond] = {"block_abstain": blk_abst, "block_n": len(blk),
                     "valid_abstain": val_abst, "valid_n": len(val),
                     "err": sum(1 for r in recs if r["err"]), "records": recs}
        print(f"run{run_i+1} {cond}: block abstain {blk_abst}/38 · valid+yes 오차단 {val_abst}/22 · {time.time()-t0:.0f}s", flush=True)
    out["runs"].append(row)
    json.dump(out, open(os.path.join(DATA, "stage85_pool20_gate.json"), "w", encoding="utf-8"), ensure_ascii=False)

# ==== noans FP (40콜, k20/k60 각 1-run) ====
no_res = {"k60": [], "k20": []}
for cond, k in (("k60", 60), ("k20", 20)):
    for n in no:
        idx, abst, ap, err = run_choice(n["query"], no_pool[n["query"]], k)
        no_res[cond].append({"qid": n["qid"], "abstain": abst, "err": err})
    fp = sum(1 for r in no_res[cond] if not r["err"] and not r["abstain"])
    print(f"noans {cond}: FP {fp}/50", flush=True)
out["noans"] = no_res

json.dump(out, open(os.path.join(DATA, "stage85_pool20_gate.json"), "w", encoding="utf-8"), ensure_ascii=False)
print(f"\n완료 {time.time()-t0:.0f}s — 저장: stage85_pool20_gate.json")

# ==== 판정 요약 ====
print("\n=== 게이트 판정 ===")
gt20_n = sum(1 for _, rk in gt20 if isinstance(rk, int))
miss_n = sum(1 for _, rk in gt20 if rk == "MISS")
print(f"op90 gold rank>20: {gt20_n}건 / MISS: {miss_n}건")
for cond in ("k60", "k20"):
    rows = [r[cond] for r in out["runs"]]
    ba = [r["block_abstain"] for r in rows]; va = [r["valid_abstain"] for r in rows]
    print(f"{cond}: block abstain {ba} (avg {sum(ba)/3:.1f}/38) · valid+yes 오차단 {va}")