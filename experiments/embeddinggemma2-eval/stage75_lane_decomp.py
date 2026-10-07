# -*- coding: utf-8 -*-
"""stage75: gemma2 pool 손실 원인 분해 (0콜)

stage74에서 gemma2(q8/q4f16)가 bekko 대비 pool 내 gold 83→71 (12건 손실) + abstain 3배.
이 12건(및 abstain 증가 쿼리)에 대해 lane 단독 순위를 분해:
  - fts_rank  : FTS 단독 (BM25 아님, mnemosyne _fts_search_working)
  - vec_rank  : gemma2 임베딩 단독 (cosine)
  - imp_rank  : importance 단독
  - graph_rank: graph lane 단독
  - rrf_rank  : build_lane_pool RRF 병합 후
  - gate_rank : _filter_and_rank(어휘 게이트) 후
→ 어느 단계에서 gold가 떨어지는지 쿼리별 분류. 0콜 (JEV 호출 없음).
"""
import os, sys, json, sqlite3, re

REPO = r"C:/Users/mandu/hermes-made/jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)
import stage48_live60_cross as m48
import gateway.j1_pipeline as j1p
from mnemosyne.core import beam as beam_mod
import numpy as np

sys.path.insert(0, os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20261006-embedgemma2"))
from embgemma2_runner import EmbGemma2Runner

_g2 = EmbGemma2Runner(os.path.join(os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20261006-embedgemma2"), "model-src"), model_file="model_q4f16.onnx")
def gemma2_embed(texts):
    if isinstance(texts, str):
        texts = [texts]
    return np.array(_g2.embed(list(texts), doc=False), dtype=np.float32)

beam_mod._embeddings.embed = gemma2_embed

SNAP = m48.SNAP
DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
s = sqlite3.connect(SNAP); s.row_factory = sqlite3.Row

# stage74에서 gemma2-q4f16이 gold를 pool에서 놓친 쿼리 + bekko abstain이었던 쿼리
d45 = json.load(open(os.path.join(DATA, "stage45_abstain_label_snapshot.json"), encoding="utf-8"))
op = [(r["query"], r["gold_id"]) for r in d45["runs"][0]["records"] if r.get("grp") == "op"]

gq4 = json.load(open(os.path.join(DATA, "stage74_gemma2_q4f16.json"), encoding="utf-8"))["results"]
gq8 = json.load(open(os.path.join(DATA, "stage74_gemma2_q8.json"), encoding="utf-8"))["results"]
base = json.load(open(os.path.join(DATA, "stage54_op90_regress.json"), encoding="utf-8"))["base"]

# 대상: gemma2 q4f16에서 gold가 pool 밖이거나 abstain인 쿼리
targets = []
for i, r in enumerate(gq4):
    if r["gold_rank_pool"] is None or r["abstain"]:
        targets.append(i)
print(f"대상 쿼리: {len(targets)}건 (gemma2 q4f16 gold miss/abstain)", flush=True)

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

def lane_rank_of(q, gold, kind):
    """해당 lane 단독 검색에서 gold의 순위 (1-indexed)."""
    recall_raw = recall_raw_factory(q)
    rows = recall_raw(kind, q, 200)
    for ri, r in enumerate(rows):
        if (str(r.get("id") or "")[:16] == (gold or "")[:16]):
            return ri + 1
    return None

# RRF/게이트에서 gold 위치 계산
def rrf_gate_rank(q, gold):
    pool = j1p.build_lane_pool(recall_raw_factory(q), q)
    pool = [p for p in pool if ((p.get("created_at") or "")[:10] < "2026-10-05")]
    # RRF 후 (게이트 전)
    rrf_rank = next((i+1 for i, p in enumerate(pool) if (str(p.get("id") or "")[:16] == (gold or "")[:16])), None)
    # 게이트 후
    filtered = j1p._filter_and_rank(pool, q)
    gate_rank = next((i+1 for i, p in enumerate(filtered) if (str(p.get("id") or "")[:16] == (gold or "")[:16])), None)
    return rrf_rank, gate_rank

out = []
for i in targets:
    q, gold = op[i]
    rec = {"idx": i, "q": q[:60], "gold": gold[:16]}
    # bekko/gemma2 상태
    rec["bekko_pool_rank"] = base[i]["gold_rank_pool"]
    rec["bekko_abstain"] = base[i]["abstain"]
    rec["g4_pool_rank"] = gq4[i]["gold_rank_pool"]
    rec["g4_abstain"] = gq4[i]["abstain"]
    rec["g8_pool_rank"] = gq8[i]["gold_rank_pool"]
    # lane 단독 순위 (gemma2)
    for lane in ("fts", "vec", "imp", "graph"):
        rec[f"{lane}_rank"] = lane_rank_of(q, gold, lane)
    rrf_rank, gate_rank = rrf_gate_rank(q, gold)
    rec["rrf_rank"] = rrf_rank
    rec["gate_rank"] = gate_rank
    # 분류: 어느 단계에서 떨어졌나
    if rec["fts_rank"] is not None and rec["fts_rank"] <= 10:
        rec["loss_stage"] = "fts는 상위인데 rrf에서 밀림" if (rrf_rank is None or rrf_rank > 60) else "fts 상위, rrf 유지"
    elif rec["vec_rank"] is not None and rec["vec_rank"] <= 10:
        rec["loss_stage"] = "vec는 상위인데 rrf에서 밀림" if (rrf_rank is None or rrf_rank > 60) else "vec 상위, rrf 유지"
    elif rrf_rank is not None and rrf_rank <= 60 and gate_rank is None:
        rec["loss_stage"] = "rrf 유지, 게이트에서 탈락"
    elif rrf_rank is None:
        rec["loss_stage"] = "rrf 60 밖 (전체 lane 모두 하위)"
    else:
        rec["loss_stage"] = f"rrf {rrf_rank}위 유지 (게이트 통과)"
    out.append(rec)
    print(f"[{i}] {q[:40]} | fts={rec['fts_rank']} vec={rec['vec_rank']} imp={rec['imp_rank']} graph={rec['graph_rank']} rrf={rrf_rank} gate={gate_rank} | {rec['loss_stage']}", flush=True)

# 분류 집계
from collections import Counter
print("\n=== 손실 단계 분류 ===")
print(Counter(r["loss_stage"] for r in out))

json.dump(out, open(os.path.join(DATA, "stage75_lane_decomp.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\n저장: stage75_lane_decomp.json ({len(out)}건)")