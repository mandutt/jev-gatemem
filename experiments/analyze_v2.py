"""Analyze phase1v2 results — type-wise J1 vs A, lift/miss stats."""
import json
from collections import defaultdict

d = json.load(open(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\results\phase1v2_picks3.json", encoding="utf-8"))
agg = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
for r in d["per_query"]:
    t = r["query_type"]
    agg[t][0] += r["A_recall@1"]
    agg[t][1] += r["J1_recall@1"]
    agg[t][2] += r["A_recall@3"]
    agg[t][3] += r["J1_recall@3"]
    agg[t][4] += 1
    if r["J1_recall@1"] > r["A_recall@1"]:
        agg[t][5] += 1

print(f"{'type':<12}{'n':>4}{'A@1':>8}{'J1@1':>8}{'A@3':>8}{'J1@3':>8}{'wins':>6}")
for t, v in sorted(agg.items()):
    a1, j1, a3, j3, n, w = v
    print(f"{t:<12}{n:>4}{a1/n:>8.3f}{j1/n:>8.3f}{a3/n:>8.3f}{j3/n:>8.3f}{w:>6}")

no_pool = sum(1 for r in d["per_query"] if not (set(r["gold_ids"]) & set(r["A_ranked"])))
print("\nqueries where gold NOT in lane pool:", no_pool)
lifted = sum(1 for r in d["per_query"] if r["J1_recall@1"] and not r["A_recall@1"])
print("queries Jev lifted from A@1=0 to J1@1=1:", lifted)
missed = sum(1 for r in d["per_query"] if not r["J1_recall@1"] and (set(r["gold_ids"]) & set(r["A_ranked"])))
print("queries gold in pool but Jev missed (J1@1=0):", missed)

# show lifted queries detail
print("\n--- lifted queries (Jev found gold at rank1 where lane didn't) ---")
for r in d["per_query"]:
    if r["J1_recall@1"] and not r["A_recall@1"]:
        print(f"  {r['query_id']} [{r['query_type']}] picks={r['jev_picks']}")
# show missed queries detail
print("\n--- missed queries (gold in pool, Jev didn't pick) ---")
for r in d["per_query"]:
    if not r["J1_recall@1"] and (set(r["gold_ids"]) & set(r["A_ranked"])):
        gold = set(r["gold_ids"])
        a_rank = [i for i, cid in enumerate(r["A_ranked"][:20]) if cid in gold]
        print(f"  {r['query_id']} [{r['query_type']}] gold_in_pool_rank={a_rank} picks={r['jev_picks']}")