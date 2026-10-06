# -*- coding: utf-8 -*-
"""stage54: op-90 전체 회귀 — base vs pool20 vs dual vs two_call (2026-10-06)

stage53에서 noans hard FP가 3구조 모두 개선(13→5~8)됐으나 op-90 회귀 미확인.
op-90 전체에 4구조 적용해 hit@1/3·abstain·err 비교. (90쿼리 × 4구조 ≈ 360콜, 2콜 포함)
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
ABSTAIN_TOPIC = "No candidate contains the specific information the question asks for — some candidates discuss the topic, but none answers it directly"
ABSTAIN_NONE = "No candidate is relevant to the question at all"

def recall_raw_factory(q):
    def recall_raw(kind, arg, kk):
        if kind == "fts": return beam_mod._fts_search_working(s, arg, k=kk)
        if kind == "vec":
            qemb = emb_mod.embed([arg])
            if qemb is None or not len(qemb): return []
            return beam_mod._wm_vec_search(s, qemb[0], k=kk)
        if kind == "imp": return j1p._imp_search(s, k=kk)
        if kind == "graph": return j1p._graph_lane_search(s, arg, k=kk)
        if kind == "get":
            r = s.execute("SELECT id, content, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
            if not r:
                r = s.execute("SELECT id, content, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
            return dict(r) if r else None
        return []
    return recall_raw

def build_pool(q, cap):
    pool = j1p.build_lane_pool(recall_raw_factory(q), q)
    pool = [p for p in pool if ((p.get("created_at") or "")[:10] < "2026-10-05")]
    return j1p._filter_and_rank(pool, q)[:cap]

CLIENT = _jev_client()
assert CLIENT
_API = getattr(CLIENT, "_jev_api", None)
# 시작 키: 키2 우선 (키1 일일 한도 소진 가능성)
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
                        sys.stderr.write(f"[daily] {str(rot.last_key)[:8]}...\n")
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

def fmt_labels(rows, q):
    return [j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150) or "n/a" for c in rows[:60]]

def chunk_choice(state, rows, q, idx_min, idx_max):
    """choice call 공용 — criteria 인덱스 그대로"""
    return None  # 미사용

def run_base(q, rows):
    labels = fmt_labels(rows, q)
    jl = labels + [ABSTAIN_CUR]
    st = j1p.build_state(q, rows)
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

def run_pool20(q, rows):
    rows20 = rows[:20]
    labels = fmt_labels(rows20, q)
    jl = labels + [ABSTAIN_CUR]
    st = j1p.build_state(q, rows20)
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

def run_dual(q, rows):
    labels = fmt_labels(rows, q)
    jl = labels + [ABSTAIN_TOPIC, ABSTAIN_NONE]
    st = j1p.build_state(q, rows)
    qs = {"best": {"type": "choice", "instructions": m48.INSTR,
                   "criteria": {f"c{i}": jl[i] for i in range(len(jl))}}}
    resp = post(st, qs)
    if resp is None or resp.status_code != 200: return None, None, f"http{getattr(resp,'status_code',None)}"
    ans = (resp.json().get("answers") or {}).get("best") or {}
    probs = ans.get("probabilities") or {}
    n = len(jl)
    ap = float(probs.get(f"c{n-2}", 0.0) or 0.0) + float(probs.get(f"c{n-1}", 0.0) or 0.0)
    try: idx = int(str(ans.get("choice")).lstrip("c"))
    except Exception: idx = None
    abstain = (idx in (n-2, n-1)) or (ap > 0.3)
    return idx, abstain, None

def run_two_call(q, rows):
    labels = fmt_labels(rows, q)
    jl = labels + [ABSTAIN_CUR]
    st = j1p.build_state(q, rows)
    qs = {"best": {"type": "choice", "instructions": m48.INSTR,
                   "criteria": {f"c{i}": jl[i] for i in range(len(jl))}}}
    resp = post(st, qs)
    if resp is None or resp.status_code != 200: return None, None, f"http{getattr(resp,'status_code',None)}"
    ans = (resp.json().get("answers") or {}).get("best") or {}
    probs = ans.get("probabilities") or {}
    ap = float(probs.get(f"c{len(jl)-1}", 0.0) or 0.0)
    try: idx = int(str(ans.get("choice")).lstrip("c"))
    except Exception: idx = None
    if idx is None or idx >= len(labels) or ap > 0.3:
        return idx, True, None
    # 2콜: winner noul
    qs2 = {"w": {"type": "noul", "instructions": {
        "question": "Does this candidate memory directly state or entail the answer to the question? Output a 0-1 score.",
        "candidate": labels[idx]}}}
    resp2 = post(st, qs2)
    if resp2 is None or resp2.status_code != 200:
        return idx, False, f"http2{getattr(resp2,'status_code',None)}"
    nv = float(((resp2.json().get("answers") or {}).get("w") or {}).get("noul", 0.0) or 0.0)
    return idx, (nv < 0.5), None

# ---- op-90 셋 ----
d45 = json.load(open(os.path.join(DATA, "stage45_abstain_label_snapshot.json"), encoding="utf-8"))
op = [(r["query"], r["gold_id"]) for r in d45["runs"][0]["records"] if r.get("grp") == "op"]
print(f"op-90: {len(op)}건", flush=True)

pools = {}
for k, (q, g) in enumerate(op):
    pools[k] = build_pool(q, 60)
print("pool 구성 완료", flush=True)

RUNNERS = {"base": run_base, "pool20": run_pool20, "dual": run_dual, "two_call": run_two_call}
all_res = {name: [] for name in RUNNERS}
t0 = time.time()
for k, (q, g) in enumerate(op):
    rows = pools[k]
    for name, fn in RUNNERS.items():
        idx, abst, err = fn(q, rows)
        # gold_rank: pool에서 gold 위치 (lift 전) — abstain이면 None
        gold_rank = None
        if not abst and err is None:
            gold_idx = next((i for i, p in enumerate(rows) if (p.get("id") or "")[:16] == (g or "")[:16]), None)
            if gold_idx is not None:
                gold_rank = gold_idx + 1
        all_res[name].append({"q": q, "gold": g, "choice_idx": idx, "abstain": abst,
                              "gold_rank_pool": gold_rank, "err": err})
    if (k+1) % 15 == 0:
        print(f"{k+1}/{len(op)} {time.time()-t0:.0f}s", flush=True)

# hit@1/3: choice lift 반영 (choice가 고른 후보를 1위로, gold_rank = lift 후 순위)
for name, res in all_res.items():
    errs = sum(1 for r in res if r["err"])
    absts = sum(1 for r in res if r["abstain"])
    h1 = h3 = 0
    for r in res:
        if r["err"] or r["abstain"] or r["gold_rank_pool"] is None: continue
        ci = r["choice_idx"]
        # lift 후 gold 순위: gold가 choice 선택과 같으면 1위, 아니면 (pool순위가 choice 앞이면 그대로, 아니면 +1)
        if ci is not None and isinstance(ci, int):
            gold_after = 1 if (ci == r["gold_rank_pool"] - 1) else (
                r["gold_rank_pool"] if r["gold_rank_pool"] <= ci else r["gold_rank_pool"] + 1)
            # (ci는 0-index, gold_rank_pool은 1-index)
        else:
            gold_after = r["gold_rank_pool"]
        if gold_after == 1: h1 += 1
        if gold_after <= 3: h3 += 1
    print(f"{name:9}: hit@1={h1}/90 hit@3={h3}/90 abstain={absts} err={errs}", flush=True)

json.dump(all_res, open(os.path.join(DATA, "stage54_op90_regress.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("\n저장: stage54_op90_regress.json")