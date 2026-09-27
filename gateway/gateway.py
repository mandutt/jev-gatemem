"""Memory Gateway — stable contract between harnesses and memory backends (spec §7).

Phase 2 surface:
  - retrieve_candidates(query): J1 pipeline (lane pool -> conservative gate ->
    Jev choice lift) returning MemoryCandidate headers, or pool-only on any
    Jev failure (spec §19 fallback).  use_j1=False keeps the Phase 0
    backend.recall surface.
  - retrieve(ids): full hydration via the backend public get() API.

remember / invalidate / forget remain declared stubs (Phase 3+, YAGNI).
"""
from __future__ import annotations

from typing import Optional

from backends.mnemosyne import MnemosyneBackend
from gateway.excerpts import prepare_candidates
from gateway.types import MemoryCandidate, MemoryRecord


_J1_TIMEOUT_S = 5.0  # hard cap; matches harness JEV_CHOICE_TIMEOUT_S


class MemoryGateway:
    def __init__(self, backend: MnemosyneBackend, *, candidate_budget: int = 40,
                 use_j1: bool = True, timeout: float = _J1_TIMEOUT_S):
        self.backend = backend
        self.candidate_budget = candidate_budget
        self.use_j1 = use_j1
        self.timeout = timeout

    # -- live Phase 0/1 surface -------------------------------------------
    def retrieve_candidates(self, query: str, *, candidate_budget: Optional[int] = None,
                            use_j1: Optional[bool] = None,
                            use_enhanced: bool = False) -> list[MemoryCandidate]:
        """Candidate headers for a query.

        use_j1=True (default): J1 pipeline — lane pool (FTS+vec, RRF) ->
        conservative gate -> Jev choice lift (spec §18/§26-J1).  Any Jev or
        pipeline failure falls back to the pool-only ranking (spec §19) and
        never raises.

        use_j1=False: Phase 0 surface — backend.recall + excerpts.
        """
        use_j1 = self.use_j1 if use_j1 is None else use_j1
        budget = candidate_budget or self.candidate_budget

        if not use_j1:
            hits = self.backend.recall(query, top_k=budget, use_enhanced=use_enhanced)
            return prepare_candidates(hits, backend=self.backend)

        return self._retrieve_j1(query, budget)

    def retrieve(self, ids: list[str]) -> list[MemoryRecord]:
        """Full hydration of the given memory ids (public get() API)."""
        return self.backend.get_by_ids(ids)

    # -- J1 path ----------------------------------------------------------
    def _retrieve_j1(self, query: str, budget: int) -> list[MemoryCandidate]:
        """Lane pool -> gate -> Jev lift; pool-only on any failure (never raises)."""
        try:
            from harnesses.j1_access import j1_pipeline

            j1 = j1_pipeline()
        except Exception:
            # accessor itself failed (broken install): fall back cleanly
            return self._pool_only(query, budget)

        beam = self.backend._ensure_beam()
        import mnemosyne.core.beam as beam_mod

        def recall_raw(kind: str, arg, k: int):
            if kind == "fts":
                return beam_mod._fts_search_working(beam.conn, arg, k=k)
            if kind == "vec":
                emb = beam_mod._embeddings.embed([arg])
                if emb is None or not len(emb):
                    return []
                return beam_mod._wm_vec_search(beam.conn, emb[0], k=k)
            if kind == "imp":
                return j1._imp_search(beam.conn, k=k)
            if kind == "graph":
                return j1._graph_lane_search(beam.conn, arg, k=k)
            if kind == "get":
                # cross-session hydration (lane searches are cross-session too)
                row = self.backend.get_hydrated(arg)
                return row if isinstance(row, dict) else None
            return []

        try:
            pool = j1.build_lane_pool(recall_raw, query)
            if not pool:
                return []
            filtered = j1._filter_and_rank(pool, query)[:budget]
            if not filtered:
                return []
            if not j1.jev_enabled():
                # JEV_RERANK=0 (kill switch): pool-only, identical to harness
                return self._rows_to_candidates(filtered)
            client = self._typesafe_client()
            ranked = j1.jev_rerank(
                query=query,
                pool=filtered,
                client=client,
                call_jev=client is not None,
                timeout=self.timeout,
            )
            return self._rows_to_candidates(ranked)
        except Exception:
            # any pipeline failure -> pool-only ranking (spec §19), no raise
            return self._pool_only(query, budget)

    def _pool_only(self, query: str, budget: int) -> list[MemoryCandidate]:
        """Pool-only fallback: lane pool + gate, no Jev (spec §19 shape)."""
        try:
            from harnesses.j1_access import j1_pipeline

            j1 = j1_pipeline()
            beam = self.backend._ensure_beam()
            import mnemosyne.core.beam as beam_mod

            def recall_raw(kind: str, arg, k: int):
                if kind == "fts":
                    return beam_mod._fts_search_working(beam.conn, arg, k=k)
                if kind == "vec":
                    emb = beam_mod._embeddings.embed([arg])
                    if emb is None or not len(emb):
                        return []
                    return beam_mod._wm_vec_search(beam.conn, emb[0], k=k)
                if kind == "imp":
                    return j1._imp_search(beam.conn, k=k)
                if kind == "graph":
                    return j1._graph_lane_search(beam.conn, arg, k=k)
                if kind == "get":
                    # cross-session hydration (lane searches are cross-session too)
                    row = self.backend.get_hydrated(arg)
                    return row if isinstance(row, dict) else None
                return []

            pool = j1.build_lane_pool(recall_raw, query)
            if not pool:
                return []
            filtered = j1._filter_and_rank(pool, query)[:budget]
            return self._rows_to_candidates(filtered)
        except Exception:
            return []

    @staticmethod
    def _typesafe_client():
        """httpx client for TypeSafe System One; None if no key."""
        import os

        key = os.environ.get("TYPESAFE_API_KEY") or ""
        if not key:
            return None
        try:
            import httpx

            return httpx.Client(
                timeout=httpx.Timeout(5.0, connect=5.0),
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
        except Exception:
            return None

    @staticmethod
    def _rows_to_candidates(rows: list[dict]) -> list[MemoryCandidate]:
        """Convert J1 pipeline result rows (dicts) to candidate DTOs."""
        out = []
        for rank, row in enumerate(rows, start=1):
            cand = MemoryCandidate(
                id=row.get("id") or "",
                created_at=str(row.get("created_at") or row.get("timestamp") or "")[:19],
                memory_type=row.get("memory_type") or "",
                scope=row.get("scope") or "",
                importance=float(row.get("importance") or 0.0),
                source_agent=str(row.get("source") or ""),
                mnemosyne_rank=rank,
                similarity_score=float(row.get("similarity_score") or row.get("score")
                                       or row.get("sim") or 0.0),
                short_excerpt=str(row.get("content") or "")[:120],
            )
            cand.jev_rank = rank  # pipeline order = Jev-reranked order
            out.append(cand)
        return out

    # -- declared stubs (Phase 3+) ----------------------------------------
    def remember(self, *args, **kwargs):
        raise NotImplementedError("remember() lands in Phase 3+")

    def invalidate(self, memory_id: str, replacement_id: Optional[str] = None):
        raise NotImplementedError("invalidate() lands in Phase 3+")

    def forget(self, memory_id: str):
        raise NotImplementedError("forget() lands in Phase 3+")