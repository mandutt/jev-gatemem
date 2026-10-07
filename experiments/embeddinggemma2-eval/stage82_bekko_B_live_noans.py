# -*- coding: utf-8 -*-
"""stage82: B 정책(평균 순위) 3셋 회귀 — 라이브 60 + noans 50 (bekko, 0콜·choice 110콜)

- 라이브: stage48_live60_cross.load_queries() 고정 시트 (사람 라벨 60건)
- noans: golden_noanswer_hard_queries.json (하드 50건)
- 정책: B(평균 순위) — stage81과 동일 build_pool_B
- 대조: 라이브는 stage48 cur(현행), noans는 stage52 기준 (raw 조회)
- 측정: abstain 수(라이브는 '정답 없음' 인식률, noans는 FP=추가 오주입 방어)
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

# bekko 임베딩
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
import numpy as np
def _embed_fn(texts):
    if isinstance(texts, str):
        texts = [texts]
    return np.array(list(_mb.embed(list(texts))), dtype=np.float32)
beam_mod._embeddings.embed = _embed_fn

SNAP = m48.SNAP
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
            return dict(r) if r else None
        return []
    return recall_raw

def build_pool_B(q, cap):
    pool = j1p.build_lane_pool(recall_raw_factory(q), q)
    pool = [p for p in pool if ((p.get("created_at") or "")[:10] < "2026-10-05")]
    q_tokens = j1p._tokenize(q) - j1p._STOPWORDS
    if not q_tokens:
        return []
    passed = []
    for p in pool:
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
    cur_sorted = j1p._filter_and_rank(pool, q)
    adj_pos = {str(r.get("id") or "")[:16]: i for i, r in enumerate(cur_sorted)}
    combo = []
    for rank_rrf, p in enumerate(passed):
        key = str(p.get("id") or "")[:16]
        if key in adj_pos:
            combo.append((p, rank_rrf, adj_pos[key]))
    combo.sort(key=lambda x: (x[1] + x[2]) / 2.0)
    return [c[0] for c in combo[:cap]]

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

def run_choice(q, rows):
    labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150) or "n/a" for c in rows[:60]]
    jl = labels + [ABSTAIN_CUR]
    st = j1p.build_state(q, rows)
    qs = {"best": {"type": "choice", "instructions": INSTR,
                   "criteria": {f"c{i}": jl[i] for i in range(len(jl))}}}
    resp = post(st, qs)
    if resp is None or resp.status_code != 200:
        return None, 0.0, f"http{getattr(resp,'status_code',None)}"
    ans = (resp.json().get("answers") or {}).get("best") or {}
    probs = ans.get("probabilities") or {}
    ap = float(probs.get(f"c{len(jl)-1}", 0.0) or 0.0)
    try:
        idx = int(str(ans.get("choice")).lstrip("c"))
    except Exception:
        idx = None
    if idx is None or idx == len(jl)-1 or ap > 0.3:
        return None, ap, None
    return idx, ap, None

# ---- 1) 라이브 60 (고정 시트) ----
queries_live = m48.load_queries(s)
print(f"라이브: {len(queries_live)}건", flush=True)
live_recs = []
for qi, q in enumerate(queries_live, 1):
    rows = build_pool_B(q, 60)
    if not rows:
        live_recs.append({"query": q, "pool_n": 0, "abstained": False, "abstain_p": 0.0, "err": "empty-pool"})
        continue
    idx, ap, err = run_choice(q, rows)
    live_recs.append({"query": q, "pool_n": len(rows), "abstained": idx is None and err is None,
                      "abstain_p": round(ap, 3), "err": err})
    if qi % 10 == 0:
        print(f"  live {qi}/{len(queries_live)}", flush=True)
na = sum(1 for r in live_recs if r["abstained"])
fp = sum(1 for r in live_recs if not r["abstained"] and not r["err"])
err = sum(1 for r in live_recs if r["err"])
print(f"live(B): abstain={na}/60 pick={fp}/60 err={err}", flush=True)

# ---- 2) noans 하드 50 ----
noans = json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))
print(f"noans: {len(noans)}건", flush=True)
na_recs = []
for qi, item in enumerate(noans, 1):
    q = item["query"]
    rows = build_pool_B(q, 60)
    if not rows:
        na_recs.append({"query": q, "pool_n": 0, "abstained": False, "abstain_p": 0.0, "err": "empty-pool"})
        continue
    idx, ap, err = run_choice(q, rows)
    na_recs.append({"query": q, "pool_n": len(rows), "abstained": idx is None and err is None,
                    "abstain_p": round(ap, 3), "err": err})
    if qi % 10 == 0:
        print(f"  noans {qi}/{len(noans)}", flush=True)
na2 = sum(1 for r in na_recs if r["abstained"])
fp2 = sum(1 for r in na_recs if not r["abstained"] and not r["err"])
err2 = sum(1 for r in na_recs if r["err"])
print(f"noans(B): abstain={na2}/{len(noans)} pick(FP)={fp2}/50 err={err2}", flush=True)

out = {"policy": "B_avg_rank", "model": "bekko",
       "live": {"records": live_recs, "summary": {"abstain": na, "pick": fp, "err": err, "n": len(queries_live)}},
       "noans": {"records": na_recs, "summary": {"abstain": na2, "pick": fp2, "err": err2, "n": len(noans)}}}
with open(os.path.join(DATA, "stage82_bekko_B_live_noans.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("저장: stage82_bekko_B_live_noans.json")