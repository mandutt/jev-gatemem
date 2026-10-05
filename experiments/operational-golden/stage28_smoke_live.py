"""회귀 스모크: win-300 + soft abstain gate 반영 후 파이프라인 E2E 1건."""
import json, os, sys, time, sqlite3
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden")
os.environ["MNEMOSYNE_EMBEDDING_MODEL"] = "bench/bekko-a8m"

import sqlite_vec
DB = r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
conn.enable_load_extension(True)
sqlite_vec.load(conn)
import mnemosyne.core.beam as beam_mod
from mnemosyne.core import embeddings as emb_mod
from gateway.j1_pipeline import (build_lane_pool, _filter_and_rank, _imp_search,
                                 _graph_lane_search, POOL_BUDGET, jev_rerank,
                                 _SOFT_ABSTAIN_TAU)

# 라이브 데몬 client (Explabs 키) 재사용
from jev_mem_core.pipeline import _jev_client

def recall_raw(kind, arg, k):
    if kind == "fts": return beam_mod._fts_search_working(conn, arg, k=k)
    if kind == "vec":
        qemb = emb_mod.embed([arg])
        if qemb is None or not len(qemb): return []
        return beam_mod._wm_vec_search(conn, qemb[0], k=k)
    if kind == "imp": return _imp_search(conn, k=k)
    if kind == "graph": return _graph_lane_search(conn, arg, k=k)
    if kind == "get":
        r = conn.execute("SELECT id, content, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
        if not r:
            r = conn.execute("SELECT id, content, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
        if not r: return None
        return {"id": r[0], "content": r[1], "importance": r[2]}
    return []

# 1) gold 있는 쿼리 (stage26에서 win-300으로 회복된 것)
q = "S8 시나리오 실패 원인?"
pool = build_lane_pool(recall_raw, q)
filtered = _filter_and_rank(pool, q) if pool else []
rows = filtered[:POOL_BUDGET]
print(f"query: {q} | pool: {len(rows)}", flush=True)
client = _jev_client()
ranked, abstained = jev_rerank(query=q, pool=rows, client=client, call_jev=True, timeout=10.0)
print(f"  jev_rerank: ranked={len(ranked)} abstained={abstained}", flush=True)
print(f"  top1: {(ranked[0].get('content') or '')[:60] if ranked else '(abstain → empty)'}", flush=True)

# 2) noans 쿼리 (soft gate 확인)
q2 = "주말에 영화 보러 갈까?"
pool2 = build_lane_pool(recall_raw, q2)
filtered2 = _filter_and_rank(pool2, q2) if pool2 else []
rows2 = filtered2[:POOL_BUDGET]
print(f"\nquery: {q2} | pool: {len(rows2)}", flush=True)
ranked2, abstained2 = jev_rerank(query=q2, pool=rows2, client=client, call_jev=True, timeout=10.0)
print(f"  jev_rerank: ranked={len(ranked2)} abstained={abstained2} (expected True — soft gate)", flush=True)
print(f"  top1: {(ranked2[0].get('content') or '')[:60] if ranked2 else '(abstain → empty)'}", flush=True)

print("\nSMOKE DONE", flush=True)
conn.close()