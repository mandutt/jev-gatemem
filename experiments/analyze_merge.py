"""Accurate merge simulation: Jev pick + lane top-2, over full pool order.

Uses stored jev_picks (indices into sub pool of size=budget) mapped to real
candidate ids by re-running the lane pool per query.
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


def recall_at_k(ranked, gold, k):
    return 1.0 if any(c in gold for c in ranked[:k]) else 0.0


def mrr(ranked, gold):
    for i, cid in enumerate(ranked, start=1):
        if cid in gold:
            return 1.0 / i
    return 0.0


# per query: build full pool order, map jev picks to ids, compute variants
stats = {"A": [0, 0.0], "J1": [0, 0.0], "M2": [0, 0.0], "M3": [0, 0.0]}  # recall@1 count, mrr sum
per = []
for r in RES["per_query"]:
    q = next(x for x in Q if x["qid"] == r["query_id"])
    gold = set(r["gold_ids"])
    cands = pool.retrieve(q["query"], budget=100)
    for c in cands:
        row = beam.get(c.id)
        content = row.get("content", "") if isinstance(row, dict) and row else ""
        c.short_excerpt = build_excerpt(content, c.memory_type)
    a_ranked = [c.id for c in cands]
    budget = 40  # matches run budget
    sub_ids = [c.id for c in cands[:budget]]
    picks = r["jev_picks"]
    pick_ids = [sub_ids[p] for p in picks if p < len(sub_ids)]

    # J1: first pick to front
    j1 = list(a_ranked)
    if pick_ids:
        p0 = pick_ids[0]
        j1 = [p0] + [cid for cid in a_ranked if cid != p0]

    # M2: [jev_pick] + [lane top2] + rest
    m2 = []
    seen = set()
    for cid in ([pick_ids[0]] if pick_ids else []) + a_ranked[:2] + a_ranked:
        if cid not in seen:
            seen.add(cid)
            m2.append(cid)

    # M3: [jev_pick] + [lane top3] + rest
    m3 = []
    seen = set()
    for cid in ([pick_ids[0]] if pick_ids else []) + a_ranked[:3] + a_ranked:
        if cid not in seen:
            seen.add(cid)
            m3.append(cid)

    for name, ranked in [("A", a_ranked), ("J1", j1), ("M2", m2), ("M3", m3)]:
        stats[name][0] += recall_at_k(ranked, gold, 1)
        stats[name][1] += mrr(ranked, gold)
    per.append({"qid": r["query_id"], "type": r["query_type"], "A@1": recall_at_k(a_ranked, gold, 1),
                "J1@1": recall_at_k(j1, gold, 1), "M2@1": recall_at_k(m2, gold, 1),
                "M3@1": recall_at_k(m3, gold, 1)})

n = len(RES["per_query"])
print(f"{'system':<6}{'recall@1':>10}{'mrr':>10}")
for name in ["A", "J1", "M2", "M3"]:
    print(f"{name:<6}{stats[name][0]/n:>10.3f}{stats[name][1]/n:>10.3f}")

# per-type M2 vs A vs J1
from collections import defaultdict
agg = defaultdict(lambda: [0, 0, 0, 0])
for p in per:
    t = p["type"]
    agg[t][0] += p["A@1"]
    agg[t][1] += p["J1@1"]
    agg[t][2] += p["M2@1"]
    agg[t][3] += 1
print(f"\n{'type':<12}{'n':>4}{'A@1':>8}{'J1@1':>8}{'M2@1':>8}")
for t, v in sorted(agg.items()):
    a, j, m, nq = v
    print(f"{t:<12}{nq:>4}{a/nq:>8.3f}{j/nq:>8.3f}{m/nq:>8.3f}")

# which queries does M2 fix vs J1?
print("\nM2 fixes J1 miss:")
for p in per:
    if not p["J1@1"] and p["M2@1"]:
        print(f"  {p['qid']} [{p['type']}]")
print("\nM2 still misses:")
for p in per:
    if not p["M2@1"]:
        print(f"  {p['qid']} [{p['type']}]")