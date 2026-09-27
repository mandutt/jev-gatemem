"""Rank fusion — RRF over Mnemosyne rank + Jev rank (spec §11).

Rules from spec:
- Jev continuous score -> descending rank; ties broken by Mnemosyne rank
- candidates Jev didn't score get no Jev rank => Jev RRF contribution 0
- k is NOT fixed in the spec; compare k=10/20/30/60 on validation split
"""
from __future__ import annotations

from typing import Optional


def rrf_rank(mnemosyne_rank: dict[str, int], jev_rank: Optional[dict[str, int]], *, k: int = 30) -> list[str]:
    """Return candidate ids sorted by fused RRF score (desc).

    mnemosyne_rank: {id: 1-based rank}
    jev_rank:       {id: 1-based rank} or None (fallback => pure Mnemosyne order)
    """
    if jev_rank is None:
        return sorted(mnemosyne_rank, key=lambda i: mnemosyne_rank[i])

    fused = {}
    for cid in mnemosyne_rank:
        r_m = mnemosyne_rank[cid]
        r_j = jev_rank.get(cid)
        score = 1.0 / (k + r_m)
        if r_j is not None:
            score += 1.0 / (k + r_j)
        fused[cid] = score
    return sorted(fused, key=lambda i: (-fused[i], mnemosyne_rank[i]))


def rank_from_scores(scores: dict[str, float], tiebreak: Optional[dict[str, int]] = None) -> dict[str, int]:
    """Convert continuous scores to descending rank (1-based). Ties broken by
    the tiebreak dict (Mnemosyne rank) when provided, else stable input order."""
    items = list(scores.items())
    if tiebreak:
        items.sort(key=lambda kv: (-kv[1], tiebreak.get(kv[0], 10**9)))
    else:
        items.sort(key=lambda kv: -kv[1])
    return {cid: i + 1 for i, (cid, _) in enumerate(items)}


def mnemosyne_rank_map(candidates: list) -> dict[str, int]:
    """1-based Mnemosyne ranks from a candidate list."""
    return {c.id: c.mnemosyne_rank for c in candidates}


def apply_jev_scores(candidates: list, scores: Optional[dict[str, float]]) -> None:
    """Attach jev_score in place; None scores stay None."""
    if not scores:
        return
    for c in candidates:
        if c.id in scores:
            c.jev_score = scores[c.id]