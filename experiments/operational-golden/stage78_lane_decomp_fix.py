# -*- coding: utf-8 -*-
"""stage78: 교정(768d vec live) 후 bekko-vs-gemma2 차이 4쿼리 lane 분해 (0콜)

stage75는 vec dead 상태에서 측정해 오염. stage77 교정 후 hit 불일치는 4건뿐:
  [36] 사용자 언어 습관이 어때? (bekko hit, gemma2 miss)
  [59] X1 외부 데이터셋 실험에서 bekko 성능? (bekko hit, gemma2 miss)
  [64] bekko랑 koen 벤치 비교 결과? (bekko hit, gemma2 miss)
  [71] CAMOFOX_URL 제거한 이유? (gemma2 hit, bekko miss)

각 쿼리에 대해: fts/vec/imp/graph lane 단독 순위 → RRF → 게이트 후 순위를 gemma2로 측정.
"""
import os, sys, json, sqlite3
import numpy as np

REPO = r"C:/Users/mandu/hermes-made/jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)
import gateway.j1_pipeline as j1p
from mnemosyne.core import beam as beam_mod

sys.path.insert(0, os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20261006-embedgemma2"))
from embgemma2_runner import EmbGemma2Runner

_g2 = EmbGemma2Runner(os.path.join(os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20261006-embedgemma2"), "model-src"), model_file="model_q4f16.onnx")
def gemma2_embed(texts):
    if isinstance(texts, str):
        texts = [texts]
    return np.array(_g2.embed(list(texts), doc=False), dtype=np.float32)

beam_mod._embeddings.embed = gemma2_embed

SNAP = os.path.join(REPO, "experiments", "operational-golden", "snapshots", "mnemosyne_snapshot_20261006_gemma2.db")
s = sqlite3.connect(SNAP); s.row_factory = sqlite3.Row
s.enable_load_extension(True)
import sqlite_vec
sqlite_vec.load(s)

DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
d45 = json.load(open(os.path.join(DATA, "stage45_abstain_label_snapshot.json"), encoding="utf-8"))
op = [(r["query"], r["gold_id"]) for r in d45["runs"][0]["records"] if r.get("grp") == "op"]

TARGETS = [36, 59, 64, 71]

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

def lane_rank(q, gold, kind):
    rows = recall_raw_factory(q)(kind, q, 200)
    for ri, r in enumerate(rows):
        if (str(r.get("id") or "")[:16] == (gold or "")[:16]):
            return ri + 1
    return None

out = []
for i in TARGETS:
    q, gold = op[i]
    rec = {"idx": i, "q": q[:50]}
    for lane in ("fts", "vec", "imp", "graph"):
        rec[f"{lane}_rank"] = lane_rank(q, gold, lane)
    # RRF
    pool = j1p.build_lane_pool(recall_raw_factory(q), q)
    pool = [p for p in pool if ((p.get("created_at") or "")[:10] < "2026-10-05")]
    rec["rrf_rank"] = next((i+1 for i, p in enumerate(pool) if (str(p.get("id") or "")[:16] == (gold or "")[:16])), None)
    # 게이트 후
    filtered = j1p._filter_and_rank(pool, q)
    rec["gate_rank"] = next((i+1 for i, p in enumerate(filtered) if (str(p.get("id") or "")[:16] == (gold or "")[:16])), None)
    # RRF top5 id (무엇이 gold를 밀어내는지)
    rec["rrf_top5"] = [(str(p.get("id") or "")[:12]) for p in pool[:5]]
    out.append(rec)
    print(f"[{i}] {q[:40]}", flush=True)
    print(f"    fts={rec['fts_rank']} vec={rec['vec_rank']} imp={rec['imp_rank']} graph={rec['graph_rank']} | RRF={rec['rrf_rank']} gate={rec['gate_rank']}", flush=True)
    print(f"    RRF top5: {rec['rrf_top5']}", flush=True)

json.dump(out, open(os.path.join(DATA, "stage78_lane_decomp_fix.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("저장: stage78_lane_decomp_fix.json")