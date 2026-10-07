# -*- coding: utf-8 -*-
"""stage74: op-90 회귀 — 임베딩 모델 교체 (bekko → gemma2) 시 pool/JEV 판정 변화 실측

stage54와 동일한 90쿼리·스냅샷·라벨·choice 구조를 유지하고, vec lane 임베딩만
gemma2-q8/q4f16으로 교체한다.

- 베이스라인(현행 bekko) : stage54_op90_regress.json (기존 raw 재사용, 0콜)
- gemma2-q8 (text-only)  : 본 러너 1회 실행 (90콜)
- gemma2-q4f16          : 본 러너 1회 실행 (90콜)

측정: hit@1/3 (choice lift 반영), abstain 수, err, gold_rank_pool 분포.
"""
import os, sys, json, sqlite3, time, re

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)
import stage48_live60_cross as m48
import gateway.j1_pipeline as j1p
from mnemosyne.core import beam as beam_mod
from jev_mem_core.pipeline import _jev_client

MODEL_FILE = sys.argv[1] if len(sys.argv) > 1 else "model_q4f16.onnx"  # or model_quantized.onnx
LABEL = sys.argv[2] if len(sys.argv) > 2 else "q4f16"

SNAP = os.path.join(REPO, "experiments", "operational-golden", "snapshots", "mnemosyne_snapshot_20261006_gemma2.db")  # stage77: work DB (768d, vec lane live)
DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
s = sqlite3.connect(SNAP); s.row_factory = sqlite3.Row

ABSTAIN_CUR = m48.ABSTAIN_CURRENT
INSTR = m48.INSTR

# ---- gemma2 임베딩을 vec lane에 공급 ----
BENCH = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20261006-embedgemma2")
sys.path.insert(0, BENCH)
from embgemma2_runner import EmbGemma2Runner

_g2 = EmbGemma2Runner(os.path.join(BENCH, "model-src"), model_file=MODEL_FILE)

def gemma2_embed(texts):
    if isinstance(texts, str):
        texts = [texts]
    # fastembed-style: (n, dim) ndarray or None
    import numpy as np
    out = np.array(_g2.embed(list(texts), doc=False), dtype=np.float32)
    return out

# beam_mod._embeddings.embed 대체 (doc prefix 없이 — 쿼리역할이므로 SearchQuery 프롬프트가 맞다)
_orig_embed = beam_mod._embeddings.embed
def patched_embed(texts):
    return gemma2_embed(texts)
beam_mod._embeddings.embed = patched_embed

# recall_raw의 vec 경로가 beam_mod._wm_vec_search까지 그대로 쓰도록 유지
def recall_raw_factory(q):
    def recall_raw(kind, arg, kk):
        if kind == "fts":
            return beam_mod._fts_search_working(s, arg, k=kk)
        if kind == "vec":
            qemb = beam_mod._embeddings.embed([arg])
            if qemb is None or not len(qemb):
                return []
            return beam_mod._wm_vec_search(s, qemb[0], k=kk)
        if kind == "imp":
            return j1p._imp_search(s, k=kk)
        if kind == "graph":
            return j1p._graph_lane_search(s, arg, k=kk)
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

def run_base(q, rows):
    labels = fmt_labels(rows, q)
    jl = labels + [ABSTAIN_CUR]
    st = j1p.build_state(q, rows)
    qs = {"best": {"type": "choice", "instructions": INSTR,
                   "criteria": {f"c{i}": jl[i] for i in range(len(jl))}}}
    resp = post(st, qs)
    if resp is None or resp.status_code != 200:
        return None, None, f"http{getattr(resp,'status_code',None)}"
    ans = (resp.json().get("answers") or {}).get("best") or {}
    probs = ans.get("probabilities") or {}
    ap = float(probs.get(f"c{len(jl)-1}", 0.0) or 0.0)
    try:
        idx = int(str(ans.get("choice")).lstrip("c"))
    except Exception:
        idx = None
    abstain = (idx is None) or (idx == len(jl)-1) or (ap > 0.3)
    return idx, abstain, None

# ---- op-90 셋 (stage54와 동일) ----
d45 = json.load(open(os.path.join(DATA, "stage45_abstain_label_snapshot.json"), encoding="utf-8"))
op = [(r["query"], r["gold_id"]) for r in d45["runs"][0]["records"] if r.get("grp") == "op"]
print(f"op-90: {len(op)}건 | 임베딩: gemma2-{LABEL}", flush=True)

pools = {}
for k, (q, g) in enumerate(op):
    pools[k] = build_pool(q, 60)
print("pool 구성 완료", flush=True)

all_res = []
t0 = time.time()
for k, (q, g) in enumerate(op):
    rows = pools[k]
    idx, abst, err = run_base(q, rows)
    gold_rank = None
    if not abst and err is None:
        gold_idx = next((i for i, p in enumerate(rows) if (p.get("id") or "")[:16] == (g or "")[:16]), None)
        if gold_idx is not None:
            gold_rank = gold_idx + 1
    all_res.append({"q": q, "gold": g, "choice_idx": idx, "abstain": abst,
                    "gold_rank_pool": gold_rank, "err": err})
    if (k+1) % 15 == 0:
        print(f"{k+1}/{len(op)} {time.time()-t0:.0f}s", flush=True)

errs = sum(1 for r in all_res if r["err"])
absts = sum(1 for r in all_res if r["abstain"])
h1 = h3 = 0
pool_ranks = []
for r in all_res:
    if r["err"] or r["abstain"] or r["gold_rank_pool"] is None:
        continue
    pool_ranks.append(r["gold_rank_pool"])
    ci = r["choice_idx"]
    if ci is not None and isinstance(ci, int):
        gold_after = 1 if (ci == r["gold_rank_pool"] - 1) else (
            r["gold_rank_pool"] if r["gold_rank_pool"] <= ci else r["gold_rank_pool"] + 1)
    else:
        gold_after = r["gold_rank_pool"]
    if gold_after == 1: h1 += 1
    if gold_after <= 3: h3 += 1
print(f"gemma2-{LABEL}: hit@1={h1}/90 hit@3={h3}/90 abstain={absts} err={errs}", flush=True)

out = {"label": LABEL, "model_file": MODEL_FILE, "results": all_res,
       "summary": {"hit@1": h1, "hit@3": h3, "abstain": absts, "err": errs, "n": len(op)}}
with open(os.path.join(DATA, f"stage74_gemma2_{LABEL}.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print(f"저장: stage74_gemma2_{LABEL}.json")