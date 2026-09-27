"""Correct merge simulation:
L2J: top = [lane rank0] + [jev pick] + [lane rank1..2] + rest  (lane-first)
J2L: top = [jev pick] + [lane rank0..1] + rest  (jev-first, previous M2)
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


def merge(prefix_ids, a_ranked):
    out, seen = [], set()
    for cid in prefix_ids + a_ranked:
        if cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


stats = {k: [0, 0.0] for k in ["A", "J1", "L2J", "L3J", "J1L1"]}
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
    budget = 40
    sub_ids = [c.id for c in cands[:budget]]
    picks = r["jev_picks"]
    pick_ids = [sub_ids[p] for p in picks if p < len(sub_ids)]

    j1 = [pick_ids[0]] + [cid for cid in a_ranked if cid != pick_ids[0]] if pick_ids else a_ranked

    # L2J: lane rank0 first, then jev pick, then lane rank1-2, then rest
    l2j = merge([a_ranked[0]] + ([pick_ids[0]] if pick_ids else []) + a_ranked[1:3], a_ranked)
    # L3J: lane rank0-2 first, then jev pick
    l3j = merge(a_ranked[:3] + ([pick_ids[0]] if pick_ids else []), a_ranked)
    # J1L1: jev pick first, lane rank0 second, lane rank1 third
    j1l1 = merge([pick_ids[0]] if pick_ids else [] + a_ranked[:2], a_ranked)

    for name, ranked in [("A", a_ranked), ("J1", j1), ("L2J", l2j), ("L3J", l3j), ("J1L1", j1l1)]:
        stats[name][0] += recall_at_k(ranked, gold, 1)
        stats[name][1] += mrr(ranked, gold)
    per.append({"qid": r["query_id"], "type": r["query_type"],
                "A@1": recall_at_k(a_ranked, gold, 1), "J1@1": recall_at_k(j1, gold, 1),
                "L2J@1": recall_at_k(l2j, gold, 1), "L3J@1": recall_at_k(l3j, gold, 1)})

n = len(RES["per_query"])
print(f"{'system':<7}{'recall@1':>10}{'mrr':>10}")
for name in ["A", "J1", "L2J", "L3J", "J1L1"]:
    print(f"{name:<7}{stats[name][0]/n:>10.3f}{stats[name][1]/n:>10.3f}")

print("\nL2J fixes J1 miss:")
for p in per:
    if not p["J1@1"] and p["L2J@1"]:
        print(f"  {p['qid']} [{p['type']}]")
print("\nL3J fixes J1 miss:")
for p in per:
    if not p["J1@1"] and p["L3J@1"]:
        print(f"  {p['qid']} [{p['type']}]")

from collections import defaultdict
agg = defaultdict(lambda: [0, 0, 0, 0])
for p in per:
    t = p["type"]
    agg[t][0] += p["A@1"]; agg[t][1] += p["J1@1"]; agg[t][2] += p["L2J@1"]; agg[t][3] += 1
print(f"\n{'type':<12}{'n':>4}{'A@1':>8}{'J1@1':>8}{'L2J@1':>8}")
for t, v in sorted(agg.items()):
    a, j, l, nq = v
    print(f"{t:<12}{nq:>4}{a/nq:>8.3f}{j/nq:>8.3f}{l/nq:>8.3f}")