"""Jev scorer smoke test — 3 queries, real API call."""
import json, os, sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")

from backends.mnemosyne import MnemosyneBackend
from experiments.lane_pool import LanePool
from gateway.excerpts import build_excerpt
from jev_controller.scorer import JevScorer

SNAP = r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\snapshots\snap-20260927.db"
Q = json.loads(Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\dataset_curated.json").read_text(encoding="utf-8"))

b = MnemosyneBackend(db_path=SNAP)
beam = b._ensure_beam()
pool = LanePool(beam, fts_budget=60, vec_budget=60, rrf_k=30)

key = os.environ.get("TYPESAFE_API_KEY", "") or os.environ.get("OPENROUTER_API_KEY", "")
print("api key set:", bool(key), "| source:", "TYPESAFE" if os.environ.get("TYPESAFE_API_KEY") else "OPENROUTER")
scorer = JevScorer(api_key=key, timeout=20.0, batch_size=20,
                   endpoint="https://api.typesafe.ai/v1/systemone", mode="typesafe",
                   model="jev-latest")


def prepare_candidates_for_pool(cands, beam):
    """Fill short_excerpt from full content for scorer headers."""
    out = []
    for c in cands:
        # LanePool returns MemoryCandidate objects; ensure short_excerpt set
        row = beam.get(c.id)
        content = row.get("content", "") if isinstance(row, dict) and row else ""
        c.short_excerpt = build_excerpt(content, c.memory_type)
        out.append(c)
    return out


for q in Q[:3]:
    cands = pool.retrieve(q["query"], budget=20)
    cands = prepare_candidates_for_pool(cands, beam)
    print(f"\n--- {q['qid']} [{q['type']}] {q['query'][:60]} (n={len(cands)})")
    try:
        scores = scorer.score_candidates(q["query"], cands)
        if scores is None:
            print("  Jev returned None (fallback)")
        else:
            top = sorted(scores.items(), key=lambda x: -x[1])[:5]
            for cid, s in top:
                c = next(c for c in cands if c.id == cid)
                print(f"  {cid[:10]} score={s:.2f} | {c.short_excerpt[:60]}")
    except Exception as e:
        print(f"  Jev ERROR: {type(e).__name__}: {e}")


def prepare_candidates_for_pool(cands, beam):
    """Fill short_excerpt from full content for scorer headers."""
    out = []
    for c in cands:
        # LanePool returns MemoryCandidate objects; ensure short_excerpt set
        row = beam.get(c.id)
        content = row.get("content", "") if isinstance(row, dict) and row else ""
        c.short_excerpt = build_excerpt(content, c.memory_type)
        out.append(c)
    return out