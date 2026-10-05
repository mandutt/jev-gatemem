"""Stage-16: base rate — of real query_log queries, how many would need a LONG
row (>1350 chars) as their answer source?

Context: b-ai #12 — if the base rate is <=5%, the long-memory problem barely
matters in practice and follow-up shrinks. Also compute: how many queries
already hit a long row in their gate-passed top-60 (answer-providing rows).

0 JEV calls. query_log (core_state.db) + live DB read-only.
"""
import os, re, sqlite3, json, sys
import numpy as np
sys.path.insert(0, r"C:/Users/mandu/hermes-made/jev-memory-middleware")
os.environ.setdefault("MNEMOSYNE_EMBEDDING_MODEL", "bench/bekko-a8m")

import sqlite_vec
DB = r"C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
conn.enable_load_extension(True)
sqlite_vec.load(conn)

import mnemosyne.core.beam as beam_mod
from gateway.j1_pipeline import build_lane_pool, _filter_and_rank, _imp_search, _graph_lane_search, POOL_BUDGET

CORE = r"C:/Users/mandu/AppData/Local/jev-mem/core_state.db"
qc = sqlite3.connect(f"file:{CORE}?mode=ro", uri=True)
qc.row_factory = sqlite3.Row

# query_log rows
qrows = qc.execute("SELECT query, received_at, pool_n FROM query_log ORDER BY received_at").fetchall()
print(f"query_log total: {len(qrows)}")

# mechanical queries
def is_mech(q):
    return (q or "").startswith("[IMPORTANT:") or (q or "").startswith("[ASYNC")

# long rows set (plain >1350)
def cls(c):
    h = c[:400]
    if '@file:' in h or '@url:' in h: return 'attach'
    if 'COMPACTION' in h or 'REFERENCE ONLY' in h: return 'compaction'
    if c.startswith('[opencode') or c.startswith('[codex'): return 'session'
    return 'plain'

long_ids = set()
for t in ("working_memory", "episodic_memory"):
    for r in conn.execute(f"SELECT id, content FROM {t}"):
        c = r["content"]
        if c and len(c) > 1350 and cls(c) == 'plain':
            long_ids.add(r["id"])
print(f"plain long rows (>1350): {len(long_ids)}")

def recall_raw(kind, arg, k):
    if kind == "fts": return beam_mod._fts_search_working(conn, arg, k=k)
    if kind == "vec":
        qemb = beam_mod._embeddings.embed([arg])
        if qemb is None or not len(qemb): return []
        return beam_mod._wm_vec_search(conn, qemb[0], k=k)
    if kind == "imp": return _imp_search(conn, k=k)
    if kind == "graph": return _graph_lane_search(conn, arg, k=k)
    if kind == "get":
        r = conn.execute("SELECT id, content, source, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
        if not r:
            r = conn.execute("SELECT id, content, source, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
        if not r: return None
        return {"id": r[0], "content": r[1], "source": r[2], "importance": r[3]}
    return []

# ---- measure ---------------------------------------------------------------
n_real = 0
n_with_long_in_gate = 0
n_with_long_pool = 0
n_long_as_top1 = 0
details = []
for qr in qrows:
    q = (qr["query"] or "").strip()
    if not q or len(q) < 8 or is_mech(q):
        continue
    n_real += 1
    pool = build_lane_pool(recall_raw, q)
    f = _filter_and_rank(pool, q)[:POOL_BUDGET]
    pool_long = [r["id"] for r in pool if r["id"] in long_ids]
    gate_long = [r.get("id") for r in f if r.get("id") in long_ids]
    if pool_long:
        n_with_long_pool += 1
    if gate_long:
        n_with_long_in_gate += 1
    if f and f[0].get("id") in long_ids:
        n_long_as_top1 += 1
    details.append((q[:40], len(pool), len(f), len(pool_long), len(gate_long)))

print(f"\n실제 쿼리 수(비기계): {n_real}")
print(f"long 행이 pool에 있는 쿼리: {n_with_long_pool}/{n_real} ({n_with_long_pool/n_real*100:.0f}%)")
print(f"long 행이 gate 통과 top-60에 있는 쿼리: {n_with_long_in_gate}/{n_real} ({n_with_long_in_gate/n_real*100:.0f}%)")
print(f"long 행이 top-1인 쿼리: {n_long_as_top1}/{n_real} ({n_long_as_top1/n_real*100:.0f}%)")

# subset: 2026-10-04/05 (recent, after [ASSISTANT] stored rows accumulated)
recent = [d for d in details]
print("\n최근 20건 상세 (query / pool / gate / long_in_pool / long_in_gate):")
for d in details[-20:]:
    print(f"  {d[0]!r} pool={d[1]} gate={d[2]} longP={d[3]} longG={d[4]}")

conn.close(); qc.close()
print("\nDONE")