"""Deep-dive on the 4 Jev-miss queries: q110, q148, q149, q150.

For each: query text, gold memory content, what Jev picked (candidate content),
pool rank of gold vs picked, and candidate excerpts for manual comparison.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")

from backends.mnemosyne import MnemosyneBackend
from experiments.lane_pool import LanePool
from gateway.excerpts import build_excerpt

SNAP = r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\snapshots\snap-20260927.db"
Q = json.loads(Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\dataset_curated.json").read_text(encoding="utf-8"))
RES = json.load(open(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\results\phase1v2_picks3.json", encoding="utf-8"))

b = MnemosyneBackend(db_path=SNAP)
beam = b._ensure_beam()
pool = LanePool(beam, fts_budget=60, vec_budget=60, rrf_k=30)

by_id = {q["qid"]: q for q in Q}
MISS = {"q110", "q148", "q149", "q150"}

for r in RES["per_query"]:
    if r["query_id"] not in MISS:
        continue
    q = by_id[r["query_id"]]
    gold = set(r["gold_ids"])
    print("=" * 70)
    print(f"{r['query_id']} [{r['query_type']}] QUERY: {q['query']}")
    # gold content
    for gid in gold:
        row = beam.get(gid)
        content = row.get("content", "") if row else "(not found)"
        print(f"  GOLD {gid[:12]}: {content[:150]}")
    # pool order top 10 with rank
    cands = pool.retrieve(q["query"], budget=100)
    for c in cands:
        row = beam.get(c.id)
        content = row.get("content", "") if isinstance(row, dict) and row else ""
        c.short_excerpt = build_excerpt(content, c.memory_type)
    print("  POOL top10 (rank: excerpt):")
    for i, c in enumerate(cands[:10]):
        mark = " <== GOLD" if c.id in gold else ""
        print(f"    {i}: {c.short_excerpt[:80]}{mark}")
    # what Jev picked
    picks = r["jev_picks"]
    print(f"  JEV picks: {picks} ->", end=" ")
    for p in picks:
        if p < len(cands):
            c = cands[p]
            mark = " <== GOLD" if c.id in gold else ""
            print(f"  rank{p}={c.short_excerpt[:60]}{mark}")