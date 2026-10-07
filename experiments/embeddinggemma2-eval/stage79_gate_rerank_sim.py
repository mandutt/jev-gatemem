# -*- coding: utf-8 -*-
"""stage79: _filter_and_rank 재정렬 개선 시뮬레이션 (0콜, gemma2-q8 vec live work DB)

문제 (stage78): RRF 1위 gold를 gate 재정렬이 8~9위로 강등 — 파이프라인 정책 문제.
대안 A/B를 90쿼리 전체에 0콜 시뮬레이션:
  cur  : _filter_and_rank 현행 (adjusted score)
  A    : 게이트 통과 후 RRF 순서 보존 (정렬 제거)
  B    : RRF 순위와 adjusted score의 rank 결합 (평균 순위)
  C    : quality 승수 제거한 adjusted score
측정: 게이트 통과 gold의 rank 분포 + rank==1 비율 (choice가 gold를 고를 확률의 상한).
stage77 raw에서 gold_rank_pool==1일 때 choice==gold인 비율로 보정해 hit@1을 추정.
"""
import os, sys, json, sqlite3
from collections import Counter
import numpy as np

REPO = r"C:/Users/mandu/hermes-made/jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)
import gateway.j1_pipeline as j1p
from mnemosyne.core import beam as beam_mod

MODEL = os.environ.get("SIM_MODEL", "gemma2")
if MODEL == "gemma2":
    sys.path.insert(0, os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20261006-embedgemma2"))
    from embgemma2_runner import EmbGemma2Runner
    _g2 = EmbGemma2Runner(os.path.join(os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20261006-embedgemma2"), "model-src"), model_file="model_q4f16.onnx")
    def _embed_fn(texts):
        if isinstance(texts, str):
            texts = [texts]
        return np.array(_g2.embed(list(texts), doc=False), dtype=np.float32)
    SNAP = os.path.join(REPO, "experiments", "operational-golden", "snapshots", "mnemosyne_snapshot_20261006_gemma2.db")
else:  # bekko
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
        return np.array(list(_mb.embed(list(texts))), dtype=np.float32)
    SNAP = os.path.join(REPO, "experiments", "operational-golden", "snapshots", "mnemosyne_snapshot_20261006.db")

beam_mod._embeddings.embed = _embed_fn
s = sqlite3.connect(SNAP); s.row_factory = sqlite3.Row
s.enable_load_extension(True)
import sqlite_vec
sqlite_vec.load(s)

DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
d45 = json.load(open(os.path.join(DATA, "stage45_abstain_label_snapshot.json"), encoding="utf-8"))
op = [(r["query"], r["gold_id"]) for r in d45["runs"][0]["records"] if r.get("grp") == "op"]

# stage77 raw (gemma2-q8 vec live): 보정 계수용
st77 = json.load(open(os.path.join(DATA, "stage74_gemma2_q8_vec768.json"), encoding="utf-8"))["results"]

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

def gold_rank_in(rows, gold):
    for i, p in enumerate(rows):
        if (str(p.get("id") or "")[:16] == (gold or "")[:16]):
            return i + 1
    return None

# -- 0콜: 각 쿼리 RRF pool + 게이트 -- 
# 주의: _filter_and_rank는 내부에서 재정렬하므로, RRF 순서 보존 버전은 직접 구현
cur_ranks, a_ranks, b_ranks, c_ranks = [], [], [], []
stats = {"n": 0, "rrf_top1_gold": 0, "cur_demote": 0}

_qpos = {r["q"]: r for r in st77}  # raw 대조용

for i, (q, gold) in enumerate(op):
    pool = j1p.build_lane_pool(recall_raw_factory(q), q)
    pool = [p for p in pool if ((p.get("created_at") or "")[:10] < "2026-10-05")]
    gold_rrf = gold_rank_in(pool, gold)
    if gold_rrf is None:
        cur_ranks.append(None); a_ranks.append(None); b_ranks.append(None); c_ranks.append(None)
        continue
    stats["n"] += 1
    if gold_rrf == 1:
        stats["rrf_top1_gold"] += 1

    # 현재 _filter_and_rank (정렬 포함)
    filtered_cur = j1p._filter_and_rank(pool, q)
    cur_r = gold_rank_in(filtered_cur, gold)
    cur_ranks.append(cur_r)

    # A: 게이트 통과만, RRF 순서 유지 — 게이트에서 통과한 행만 RRF 순서로
    q_tokens = j1p._tokenize(q) - j1p._STOPWORDS
    passed_a = []
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
        passed_a.append(p)
    a_ranks.append(gold_rank_in(passed_a, gold))

    # B: RRF rank와 adjusted rank 평균 (게이트 통과 행 대상)
    passed_b = j1p._filter_and_rank(pool, q)  # 현행 정렬 사용 (adjusted score)
    adj_pos = {str(r.get("id") or "")[:16]: i for i, r in enumerate(passed_b)}
    combo = []
    for rank_rrf, p in enumerate(pool):
        key = str(p.get("id") or "")[:16]
        if key in adj_pos:
            combo.append((p, rank_rrf, adj_pos[key]))
    combo.sort(key=lambda x: (x[1] + x[2]) / 2.0)
    b_ranks.append(gold_rank_in([c[0] for c in combo], gold))

    # C: quality 승수 제거 (adjusted score에서 quality 곱만 없애고 재정렬)
    passed_c = list(passed_b)
    for p in passed_c:
        # _adjusted 재계산에서 quality 제거 — 간단히 기존 _adjusted / quality
        src = str(p.get("source") or "").lower()
        quality = j1p._SOURCE_QUALITY.get(src, 1.0)
        if src in j1p._RAW_SOURCES:
            quality *= 0.72
        content = (p.get("content") or "").upper()
        if content.startswith("[USER]"):
            quality *= 0.68
        elif content.startswith("[IDENTITY]"):
            quality *= 0.80
        p["_adjusted_nq"] = (p["_adjusted"] / quality) if quality else p["_adjusted"]
    passed_c.sort(key=lambda r: r["_adjusted_nq"], reverse=True)
    c_ranks.append(gold_rank_in(passed_c, gold))

# -- 집계 --
def summ(ranks):
    ranks = [r for r in ranks if r is not None]
    r1 = sum(1 for r in ranks if r == 1)
    r3 = sum(1 for r in ranks if r <= 3)
    r10 = sum(1 for r in ranks if r <= 10)
    med = sorted(ranks)[len(ranks)//2]
    return {"n": len(ranks), "rank1": r1, "rank<=3": r3, "rank<=10": r10, "median": med}

print("=== 0콜 시뮬레이션 (gemma2-q8 vec live, 90쿼리) ===")
print(f"RRF pool에 gold 존재: {stats['n']}/90, RRF 1위 gold: {stats['rrf_top1_gold']}")
for name, ranks in (("현행(cur adjusted)", cur_ranks), ("A: RRF 순서 보존", a_ranks), ("B: 평균 순위", b_ranks), ("C: quality 제거", c_ranks)):
    print(f"  {name:24s}", summ(ranks))

# 보정: stage77에서 gold_rank_pool==1일 때 choice==gold 비율
n_gr1 = sum(1 for r in st77 if r["gold_rank_pool"] == 1)
n_gr1_hit = sum(1 for r in st77 if r["gold_rank_pool"] == 1 and not r["abstain"] and r["err"] is None and r["choice_idx"] == 0)
cal = n_gr1_hit / n_gr1 if n_gr1 else 0.0
print(f"\n보정 계수: gold_rank_pool==1일 때 choice==gold(c0) 비율 = {n_gr1_hit}/{n_gr1} = {cal:.2f}")
for name, ranks in (("현행", cur_ranks), ("A: RRF 보존", a_ranks), ("B: 평균 순위", b_ranks), ("C: quality 제거", c_ranks)):
    r1 = summ(ranks)["rank1"]
    print(f"  {name:20s} rank1={r1} → 추정 hit@1 ≈ {r1 * cal:.0f}/90")

out = {"stats": stats, "calibration": {"n_gr1": n_gr1, "n_hit": n_gr1_hit, "rate": cal},
       "ranks": {"cur": cur_ranks, "A_rrf_preserve": a_ranks, "B_avg_rank": b_ranks, "C_no_quality": c_ranks}}
json.dump(out, open(os.path.join(DATA, f"stage79_gate_rerank_sim_{MODEL}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"저장: stage79_gate_rerank_sim_{MODEL}.json")