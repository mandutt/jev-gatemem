"""Check actual gold rank within FULL pool for the 4 Jev-miss queries."""
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

MISS = {"q110", "q148", "q149", "q150"}
for r in RES["per_query"]:
    if r["query_id"] not in MISS:
        continue
    q = next(x for x in Q if x["qid"] == r["query_id"])
    gold = set(r["gold_ids"])
    cands = pool.retrieve(q["query"], budget=100)
    ranks = [i for i, c in enumerate(cands) if c.id in gold]
    print(f"{r['query_id']}: pool_size={len(cands)} gold_ranks={ranks} jev_picks={r['jev_picks']}")
    # what's at lane rank 0,1 for these
    for i in range(min(3, len(cands))):
        c = cands[i]
        row = beam.get(c.id)
        content = row.get("content", "") if isinstance(row, dict) and row else ""
        excerpt = build_excerpt(content, c.memory_type)
        mark = " <== GOLD" if c.id in gold else ""
        print(f"    lane rank {i}: {excerpt[:70]}{mark}")