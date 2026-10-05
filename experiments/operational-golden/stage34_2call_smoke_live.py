"""stage34: 2콜 구조 라이브 스모크 — 데몬 venv, 실제 API (2026-10-06)

j1_pipeline.jev_rerank (TWO_CALL=True)를 실제 client로 호출:
- op gold 2건 (정상 선택 기대)
- noans 2건 (soft gate/abstain 기대)
검증: 라이브 코드 경로 E2E (hybrid → noul top-5 재choice → 게이트)
"""
import sys, os, time, json
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware")

import sqlite3
import sqlite_vec
from gateway import j1_pipeline as j1p
from jev_mem_core.pipeline import _jev_client  # 데몬 venv에서 import

DB = r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
conn.enable_load_extension(True)
sqlite_vec.load(conn)

from mnemosyne.core import beam as beam_mod
from mnemosyne.core import embeddings as emb_mod

def recall_raw(kind, arg, k):
    if kind == "fts": return beam_mod._fts_search_working(conn, arg, k=k)
    if kind == "vec":
        qemb = emb_mod.embed([arg])
        if qemb is None or not len(qemb): return []
        return beam_mod._wm_vec_search(conn, qemb[0], k=k)
    if kind == "imp": return j1p._imp_search(conn, k=k)
    if kind == "graph": return j1p._graph_lane_search(conn, arg, k=k)
    if kind == "get":
        r = conn.execute("SELECT id, content, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
        if not r:
            r = conn.execute("SELECT id, content, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
        if not r: return None
        return {"id": r[0], "content": r[1], "importance": r[2]}
    return []

client = _jev_client()
print("client:", "OK" if client else "NONE", flush=True)

# op gold 쿼리 2건 (정상 선택) + noans 2건
tests = [
    ("op", "웹 추출 백엔드 설정이 뭐야?"),
    ("op", "camelAI 자동 라우팅에서 어려운 과제는 어떤 모델로 보내?"),
    ("noans", "오늘 점심 메뉴 뭐야?"),
    ("noans", "3D 프린터로 뭐 만들었어?"),
]
for grp, q in tests:
    t0 = time.perf_counter()
    try:
        pool = j1p.build_lane_pool(recall_raw, q)
        filtered = j1p._filter_and_rank(pool, q) if pool else []
        rows = filtered[:j1p.POOL_BUDGET]
        ranked, abstained = j1p.jev_rerank(query=q, pool=rows, client=client,
                                           call_jev=True, timeout=10.0)
        lat = (time.perf_counter() - t0) * 1000
        top1 = ranked[0].get("id", "")[:12] if ranked and not abstained else "-"
        print(f"[{grp}] pool={len(rows):2} abstained={abstained} top1={top1} lat={lat:.0f}ms", flush=True)
    except Exception as e:
        print(f"[{grp}] ERROR {type(e).__name__}: {e}", flush=True)
conn.close()