"""Experiment G — lane-based pool expansion: does gold recall improve?

Compares gold-in-pool rate for:
  G0: baseline linear recall top-30 (already known: 8%)
  G1: lane pool (FTS 60 + vec 60, union, RRF) -> top-100
  G2: lane pool with larger budgets (FTS 100 + vec 100) -> top-100

Output: experiments/results/pool_expansion.json + ledger line.
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backends.mnemosyne import MnemosyneBackend
from experiments.lane_pool import LanePool

SNAP = r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\snapshots\snap-20260927.db"
QUERIES = r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\dataset_curated.json"
OUT = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\results\pool_expansion.json"


def main():
    Q = json.loads(Path(QUERIES).read_text(encoding="utf-8"))
    b = MnemosyneBackend(db_path=SNAP)
    beam = b._ensure_beam()

    results = {"n_queries": len(Q), "configs": {}}

    # G1: lane pool 60+60 -> top-100
    pool = LanePool(beam, fts_budget=60, vec_budget=60, rrf_k=30)
    g1_hits = 0
    g1_gold_ranks = []
    g1_detail = []
    for q in Q:
        cands = pool.retrieve(q["query"], budget=100)
        gold_ids = set(q["gold_ids"])
        ids = [c.id for c in cands]
        found = gold_ids & set(ids)
        if found:
            g1_hits += 1
            g1_gold_ranks.append(min(ids.index(g) + 1 for g in found))
        g1_detail.append({"qid": q["qid"], "gold_in_pool": bool(found),
                          "best_rank": min(ids.index(g) + 1 for g in found) if found else None,
                          "n_cands": len(ids)})
    results["configs"]["G1_lane60_60"] = {
        "gold_in_pool": g1_hits, "rate": g1_hits / len(Q),
        "best_rank_median": sorted(g1_gold_ranks)[len(g1_gold_ranks) // 2] if g1_gold_ranks else None,
    }
    results["detail"] = g1_detail
    print(f"G1 lane60+60: gold in pool {g1_hits}/{len(Q)} ({g1_hits/len(Q)*100:.0f}%)")

    # G2: lane pool 100+100 -> top-100
    pool2 = LanePool(beam, fts_budget=100, vec_budget=100, rrf_k=30)
    g2_hits = 0
    for q in Q:
        cands = pool2.retrieve(q["query"], budget=100)
        if set(q["gold_ids"]) & set(c.id for c in cands):
            g2_hits += 1
    results["configs"]["G2_lane100_100"] = {"gold_in_pool": g2_hits, "rate": g2_hits / len(Q)}
    print(f"G2 lane100+100: gold in pool {g2_hits}/{len(Q)} ({g2_hits/len(Q)*100:.0f}%)")

    Path(OUT).parent.mkdir(parents=True, exist_ok=True)
    Path(OUT).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved", OUT)


if __name__ == "__main__":
    main()