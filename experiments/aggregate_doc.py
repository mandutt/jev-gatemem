"""Aggregate doc_improvements result from stored per_query (no re-call)."""
import json
from pathlib import Path

RES = json.load(open(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\results\doc_improvements_full.json", encoding="utf-8"))
per_query = RES["per_query"]
n = len(per_query)

print(f"n_queries={n} jev_used={RES['jev_used']} conf_threshold={RES['conf_threshold']}")

names = ["A", "C_p", "J1", "J1c", "N", "B100"]
print(f"\n{'metric':<12}" + "".join(f"{nm:>10}" for nm in names))
for m in ["recall@1", "recall@3", "recall@5", "recall@10", "ndcg@10", "mrr"]:
    row = []
    for nm in names:
        key = f"{nm}_{m}"
        if key in per_query[0]:
            v = sum(r[key] for r in per_query) / n
            row.append(f"{v:.4f}")
        else:
            row.append("-")
    print(f"{m:<12}" + "".join(f"{v:>10}" for v in row))

# per-type breakdown for the winner
from collections import defaultdict


def agg_type(metric):
    d = defaultdict(lambda: [0] * len(names))
    cnt = defaultdict(int)
    for r in per_query:
        t = r["query_type"]
        cnt[t] += 1
        for i, nm in enumerate(names):
            key = f"{nm}_{metric}"
            if key in r:
                d[t][i] += r[key]
    return d, cnt


d1, cnt = agg_type("recall@1")
print(f"\ntype-wise recall@1 (A vs C_p vs J1 vs J1c vs N vs B100):")
print(f"{'type':<12}{'n':>4}" + "".join(f"{nm:>10}" for nm in names))
for t in sorted(cnt):
    vals = [f"{d1[t][i]/cnt[t]:.3f}" if cnt[t] else "-" for i in range(len(names))]
    print(f"{t:<12}{cnt[t]:>4}" + "".join(f"{v:>10}" for v in vals))