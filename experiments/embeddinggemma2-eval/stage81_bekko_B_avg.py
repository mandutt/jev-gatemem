# -*- coding: utf-8 -*-
"""stage81: B 정책(평균 순위)(게이트 통과 후 RRF 순서 보존) JEV choice 실측 (bekko, 90콜)

stage79 시뮬레이션에서 A가 gold rank1 10→44 (4.4배) — 실질 hit@1을 JEV choice로 확정.
- SNAP: 원본 스냅샷 (bekko 384d, 운영 모델)
- 임베딩: fastembed bekko-a8m (384d, vec lane live)
- 게이트: _filter_and_rank와 동일한 통과 조건이지만 정렬 없이 RRF 순서 유지
- 측정: hit@1/3 (choice lift 반영), abstain, err — stage54(base)와 1:1 대조
"""
import os, sys, json, sqlite3, time

REPO = r"C:/Users/mandu/hermes-made/jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)
import stage48_live60_cross as m48
import gateway.j1_pipeline as j1p
from mnemosyne.core import beam as beam_mod
from jev_mem_core.pipeline import _jev_client

# bekko 임베딩 (fastembed, 운영 모델)
B93 = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20260930")
os.environ["HF_HOME"] = os.path.join(B93, "model-cache")
os.environ["HF_HUB_OFFLINE"] = "1"
sys.path.insert(0, B93)
from fastembed import TextEmbedding
from register_custom import register
register("bench/bekko-a8m")
_mb = TextEmbedding(model_name="bench/bekko-a8m", cache_dir=os.path.join(B93, "fe-cache"))
_obj = getattr(_mb, "model", _mb)
_tok = getattr(_obj, "tokenizer", None)
if _tok is not None and hasattr(_tok, "enable_truncation"):
    _tok.enable_truncation(max_length=512)
def _embed_fn(texts):
    if isinstance(texts, str):
        texts = [texts]
    return __import__("numpy").array(list(_mb.embed(list(texts))), dtype="float32")
import numpy as np
beam_mod._embeddings.embed = _embed_fn

SNAP = m48.SNAP  # 원본 스냅샷 (384d)
DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
s = sqlite3.connect(SNAP); s.row_factory = sqlite3.Row

ABSTAIN_CUR = m48.ABSTAIN_CURRENT
INSTR = m48.INSTR

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

def build_pool_B(q, cap):
    """B 정책: 게이트 통과 행에 대해 (RRF rank + adjusted rank) 평균으로 정렬."""
    pool = j1p.build_lane_pool(recall_raw_factory(q), q)
    pool = [p for p in pool if ((p.get("created_at") or "")[:10] < "2026-10-05")]
    q_tokens = j1p._tokenize(q) - j1p._STOPWORDS
    if not q_tokens:
        return []
    passed = []
    for p in pool:  # RRF 순서 유지
        r = j1p._synthesize_histories(p)
        content = (r.get("content") or "").strip()
        if not content or len(content.split()) <= 1:
            continue
        if content.upper().startswith(j1p._PREFETCH_EXCLUDED_PREFIXES):
            continue
        overlap = q_tokens & j1p._tokenize(content)
        if len(overlap) < 1:
            lane_ranks = r.get("_lane_ranks") or {}
            vr = lane_ranks.get("vec_rank")
            if not (vr is not None and vr <= j1p.VEC_RANK_EXEMPT and len(overlap) >= 1):
                continue
        passed.append(p)
    # B: RRF rank(현재 순서)와 adjusted rank(현행 정렬) 평균
    cur_sorted = j1p._filter_and_rank(pool, q)  # 현행 정렬 (adjusted score)
    adj_pos = {str(r.get("id") or "")[:16]: i for i, r in enumerate(cur_sorted)}
    combo = []
    for rank_rrf, p in enumerate(passed):
        key = str(p.get("id") or "")[:16]
        if key in adj_pos:
            combo.append((p, rank_rrf, adj_pos[key]))
    combo.sort(key=lambda x: (x[1] + x[2]) / 2.0)
    return [c[0] for c in combo[:cap]]

# JEV client (stage54와 동일)
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

def run_choice(q, rows):
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

# op-90 셋
d45 = json.load(open(os.path.join(DATA, "stage45_abstain_label_snapshot.json"), encoding="utf-8"))
op = [(r["query"], r["gold_id"]) for r in d45["runs"][0]["records"] if r.get("grp") == "op"]
print(f"op-90: {len(op)}건 | 정책: A(RRF 순서 보존) | 임베딩: bekko", flush=True)

pools = {}
for k, (q, g) in enumerate(op):
    pools[k] = build_pool_B(q, 60)
print("pool 구성 완료", flush=True)

all_res = []
t0 = time.time()
for k, (q, g) in enumerate(op):
    rows = pools[k]
    idx, abst, err = run_choice(q, rows)
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
for r in all_res:
    if r["err"] or r["abstain"] or r["gold_rank_pool"] is None:
        continue
    ci = r["choice_idx"]
    if ci is not None and isinstance(ci, int):
        gold_after = 1 if (ci == r["gold_rank_pool"] - 1) else (
            r["gold_rank_pool"] if r["gold_rank_pool"] <= ci else r["gold_rank_pool"] + 1)
    else:
        gold_after = r["gold_rank_pool"]
    if gold_after == 1: h1 += 1
    if gold_after <= 3: h3 += 1
print(f"bekko+A: hit@1={h1}/90 hit@3={h3}/90 abstain={absts} err={errs}", flush=True)

out = {"policy": "B_avg_rank", "model": "bekko", "results": all_res,
       "summary": {"hit@1": h1, "hit@3": h3, "abstain": absts, "err": errs, "n": len(op)}}
with open(os.path.join(DATA, "stage81_bekko_B_avg.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("저장: stage81_bekko_B_avg.json")