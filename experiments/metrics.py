"""Evaluation metrics — Recall@k, MRR, NDCG@k, evidence-hit rate + paired bootstrap CI."""
from __future__ import annotations

import math
import random
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# Ranking metrics
# ---------------------------------------------------------------------------

def recall_at_k(ranked_ids: list[str], gold_ids: set[str], k: int) -> float:
    if not gold_ids:
        return 0.0
    return len(gold_ids & set(ranked_ids[:k])) / len(gold_ids)


def mrr(ranked_ids: list[str], gold_ids: set[str]) -> float:
    for i, cid in enumerate(ranked_ids, start=1):
        if cid in gold_ids:
            return 1.0 / i
    return 0.0


def _dcg(ranks_of_relevant: Iterable[int]) -> float:
    return sum(1.0 / math.log2(r + 1) for r in ranks_of_relevant)


def ndcg_at_k(ranked_ids: list[str], gold_ids: set[str], k: int) -> float:
    """Binary-relevance NDCG@k (gold ids are equally relevant)."""
    gold = set(gold_ids)
    if not gold:
        return 0.0
    ideal = _dcg(range(1, min(len(gold), k) + 1))
    if ideal == 0:
        return 0.0
    rel_ranks = [i for i, cid in enumerate(ranked_ids[:k], start=1) if cid in gold]
    return _dcg(rel_ranks) / ideal


def evidence_hit(ranked_ids: list[str], gold_ids: set[str], k: int) -> float:
    """1.0 if ANY gold id appears in the top-k pool (first-stage recall check)."""
    return 1.0 if gold_ids & set(ranked_ids[:k]) else 0.0


# ---------------------------------------------------------------------------
# Aggregation + bootstrap
# ---------------------------------------------------------------------------

def summarize(per_query: list[dict], k_list=(1, 3, 5, 10)) -> dict:
    """per_query: [{'id','recalled_ids':[...], 'gold_ids':[...], ...}] -> aggregate metrics."""
    n = len(per_query) or 1
    agg = {"n_queries": len(per_query)}
    for k in k_list:
        agg[f"recall@{k}"] = sum(q[f"recall@{k}"] for q in per_query) / n
        agg[f"ndcg@{k}"] = sum(q[f"ndcg@{k}"] for q in per_query) / n
        agg[f"evidence_hit@{k}"] = sum(q[f"evidence_hit@{k}"] for q in per_query) / n
    agg["mrr"] = sum(q["mrr"] for q in per_query) / n
    return agg


def paired_bootstrap_ci(delta_per_query: list[float], n_boot: int = 2000, seed: int = 7,
                        alpha: float = 0.05) -> tuple[float, float, float]:
    """95% CI for the mean of per-query deltas, paired bootstrap.

    Returns (mean, ci_low, ci_high). CI excludes 0 => significant at alpha.
    """
    n = len(delta_per_query)
    if n == 0:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        s = sum(delta_per_query[rng.randrange(n)] for _ in range(n))
        means.append(s / n)
    means.sort()
    lo = means[int(n_boot * alpha / 2)]
    hi = means[int(n_boot * (1 - alpha / 2)) - 1]
    return sum(delta_per_query) / n, lo, hi


def compare_systems(metric_name: str, sys_a: list[dict], sys_b: list[dict], n_boot: int = 2000, seed: int = 7):
    """Paired comparison of two systems on per-query metric values.
    sys_a/sys_b: lists of per-query metric floats, SAME query order."""
    deltas = [b - a for a, b in zip(sys_a, sys_b)]
    mean, lo, hi = paired_bootstrap_ci(deltas, n_boot=n_boot, seed=seed)
    return {"metric": metric_name, "a_mean": sum(sys_a) / len(sys_a), "b_mean": sum(sys_b) / len(sys_b),
            "delta_mean": mean, "ci_low": lo, "ci_high": hi, "significant": not (lo <= 0 <= hi)}