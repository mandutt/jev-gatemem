"""Lane-based candidate pool expansion (Phase 2 early application).

Mnemosyne recall's linear scorer buries short factual memories under long
conversation dumps. This module pulls candidates from SEPARATE lanes:
  - FTS lane:  _fts_search_working (keyword precision)
  - Vector lane: _wm_vec_search (dense similarity)
then union + RRF-merge into one candidate pool of size up to `budget`.

Used by Experiment G (pool expansion) to measure whether gold recall rate
improves when the pool is NOT ranked by the linear scorer.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mnemosyne.core import beam as beam_mod
from mnemosyne.core.beam import BeamMemory

from gateway.types import MemoryCandidate
from gateway.excerpts import prepare_candidates


class LanePool:
    """Union of FTS + vector lanes, re-ranked by RRF over lane ranks."""

    def __init__(self, beam: BeamMemory, *, fts_budget: int = 60, vec_budget: int = 60,
                 rrf_k: int = 30):
        self.beam = beam
        self.fts_budget = fts_budget
        self.vec_budget = vec_budget
        self.rrf_k = rrf_k

    def _lane_ranks(self, query: str) -> dict[str, dict]:
        """id -> {fts_rank?, vec_rank?}"""
        ranks: dict[str, dict] = {}
        try:
            fts = beam_mod._fts_search_working(self.beam.conn, query, k=self.fts_budget)
            for i, r in enumerate(fts, start=1):
                ranks.setdefault(r["id"], {})["fts_rank"] = i
        except Exception:
            pass
        try:
            emb = beam_mod._embeddings.embed([query])
            if emb is not None and len(emb):
                vec = beam_mod._wm_vec_search(self.beam.conn, emb[0], k=self.vec_budget)
                for i, r in enumerate(vec, start=1):
                    ranks.setdefault(r["id"], {})["vec_rank"] = i
        except Exception:
            pass
        return ranks

    def _rrf_score(self, lane_ranks: dict) -> float:
        score = 0.0
        for rank in lane_ranks.values():
            if rank:
                score += 1.0 / (self.rrf_k + rank)
        return score

    def retrieve(self, query: str, budget: int = 100) -> list[MemoryCandidate]:
        ranks = self._lane_ranks(query)
        scored = sorted(
            ((mid, self._rrf_score(lr)) for mid, lr in ranks.items()),
            key=lambda x: -x[1],
        )
        top_ids = [mid for mid, _ in scored[:budget]]
        if not top_ids:
            return []
        # hydrate via BeamMemory.get (public API, single-id)
        rows = []
        for mid in top_ids:
            row = self.beam.get(mid)
            if row is not None:
                rows.append(row)
        by_id = {r["id"]: r for r in rows}
        cands = []
        for i, mid in enumerate(top_ids, start=1):
            row = by_id.get(mid)
            if row is None:
                continue
            cands.append(MemoryCandidate(
                id=mid,
                created_at=str(row.get("created_at") or "") if isinstance(row, dict) else "",
                memory_type=(row.get("memory_type") or "") if isinstance(row, dict) else "",
                scope=(row.get("scope") or "") if isinstance(row, dict) else "",
                importance=float(row.get("importance") or 0.0) if isinstance(row, dict) else 0.0,
                source_agent=(row.get("source") or "") if isinstance(row, dict) else "",
                mnemosyne_rank=i,
                similarity_score=float(ranks[mid].get("vec_rank", 0)),
                short_excerpt="",
            ))
        return cands