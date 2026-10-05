"""Stage-14: POOL_BUDGET 40 -> 50/60 lift check (0 JEV, live DB read-only).

After [ASSISTANT] lift: gold 19 gate 8/19, with 3 GATE-MISS at rank 44-51
(just over the top-40 cut) and 1 at 66. Test whether raising the post-gate
rank cut to 50/60 recovers them WITHOUT regressing op-90 and noans.

Note: in production the cut is POOL_BUDGET=40 applied AFTER _filter_and_rank
sorting (filtered[:40]). Here we emulate gate -> rank cut at N.
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
from gateway.j1_pipeline import build_lane_pool, _filter_and_rank, _imp_search, _graph_lane_search

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

def gate_rank_for(q, target):
    pool = build_lane_pool(recall_raw, q)
    f = _filter_and_rank(pool, q)
    fids = [r.get("id") for r in f]
    if target in fids:
        return fids.index(target) + 1, len(f), len(pool)
    return None, len(f), len(pool)

gold = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "data", "stage2_final_gold.json"), encoding="utf-8"))
goldset = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "data", "golden_eval_v3.json"), encoding="utf-8"))
gold_qs = [(g["gold"], g["query"]) for g in goldset if g.get("gold")]
noans_qs = [g for g in goldset if not g.get("gold")]

print("=== gold 19: gate rank distribution ===")
rowdata = []
for g in gold:
    gr, nf, npool = gate_rank_for(g["query"], g["row_id"])
    rowdata.append((g["row_id"][:14], gr, nf, npool))
    print(f"  {g['row_id'][:14]} gate_rank={gr} passed={nf} pool={npool}")

for N in (40, 50, 60, 80, 100):
    hits = sum(1 for _, gr, _, _ in rowdata if gr is not None and gr <= N)
    print(f"  gold gate@top-{N}: {hits}/19")

print("\n=== op-90: gate rank regression at cut N ===")
for N in (40, 50, 60, 100):
    hits = 0
    for target, q in gold_qs:
        gr, _, _ = gate_rank_for(q, target)
        if gr is not None and gr <= N:
            hits += 1
    print(f"  op-90 gold gate@top-{N}: {hits}/90")

print("\n=== noans 10: spurious pass at cut N ===")
for N in (40, 50, 60, 100):
    sp = 0
    for g in noans_qs:
        pool = build_lane_pool(recall_raw, g["query"])
        f = _filter_and_rank(pool, g["query"])[:N]
        if len(f) > 0:
            sp += 1
    print(f"  noans ANY pass at top-{N}: {sp}/10")

conn.close()
print("\nDONE")