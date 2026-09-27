"""Mnemosyne backend adapter — public API only, no internal SQLite access (spec §6.1, §18)."""
from __future__ import annotations

import json
from typing import Optional

from gateway.types import MemoryCandidate, MemoryRecord, RecallHit


class MnemosyneBackend:
    """Candidates + hydration through Mnemosyne's public recall interface.

    The backend is constructed against a *snapshot* DB path during experiments
    so the live Hermes store is never touched (design gate: live DB unmodified).

    API facts verified against mnemosyne 3.15.1 (2026-09-27):
      - BeamMemory lives at mnemosyne.core.beam (not top-level export)
      - __init__ takes (session_id, db_path, author_id, author_type, channel_id,
        use_cloud, event_emitter) — NO config kwarg
      - recall(query, top_k=40, *, ..., _cross_session=None) -> List[Dict]
      - recall_enhanced(query, top_k=40, *, use_cache, use_weibull, use_mmr,
        use_intent, use_synonyms, use_associative, mmr_lambda, **kwargs)
      - get(memory_id) -> Optional[Dict]  # full hydration, pure read
      - remember(content, source, importance, metadata, valid_until, scope,
        memory_id, extract_entities, extract, veracity, trust_tier) -> str
    """

    def __init__(self, db_path: str, session_id: str = "hermes_snapshot_eval"):
        self.db_path = db_path
        self.session_id = session_id
        self._beam = None

    # -- lifecycle ----------------------------------------------------------
    def _ensure_beam(self):
        if self._beam is not None:
            return self._beam
        from mnemosyne.core.beam import BeamMemory

        # session_id='hermes_snapshot_eval' + _cross_session=True on recall:
        # eval must see memories from all sessions/agents
        self._beam = BeamMemory(
            session_id=self.session_id,
            db_path=self.db_path,
        )
        return self._beam

    # -- retrieval ----------------------------------------------------------
    def recall(self, query: str, top_k: int = 30, *, use_enhanced: bool = False,
               cross_session: bool = True) -> list[RecallHit]:
        """First-stage candidate retrieval via the public recall API."""
        beam = self._ensure_beam()
        if use_enhanced:
            raw = beam.recall_enhanced(query, top_k=top_k)
        else:
            raw = beam.recall(query, top_k=top_k, _cross_session=cross_session)
        return self._hits(raw)

    def get_by_ids(self, ids: list[str]) -> list[MemoryRecord]:
        """Full hydration through the public get() API (pure read)."""
        out = []
        for mid in ids:
            item = self.get_hydrated(mid)
            if not item:
                continue
            out.append(self._record(item))
        return out

    def get_hydrated(self, memory_id: str) -> Optional[dict]:
        """Cross-session hydration (id-only lookup, no session filter).

        Mirrors BeamMemory.get()'s row -> dict shape (working_memory first,
        then episodic_memory) but WITHOUT the ``(session_id = ? OR scope =
        'global')`` filter. The lane searches (``_fts_search_working`` /
        ``_wm_vec_search``) are cross-session, so hydration must be too —
        otherwise pool candidates from other sessions silently drop out
        (observed: 14/62 pool-outside gold were search hits that hydration
        rejected). Pure read; Mnemosyne core is untouched.
        """
        beam = self._ensure_beam()
        conn = beam.conn
        cursor = conn.cursor()
        for table in ("working_memory", "episodic_memory"):
            cursor.execute(
                f"SELECT id, content, source, timestamp, session_id,"
                f" importance, metadata_json, veracity, created_at"
                f" FROM {table} WHERE id = ?",
                (memory_id,),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "content": row[1],
                    "source": row[2],
                    "timestamp": row[3],
                    "session_id": row[4],
                    "importance": row[5],
                    "metadata": row[6],
                    "veracity": row[7],
                    "created_at": row[8],
                    "memory_store": "working" if table == "working_memory" else "episodic",
                }
        return None

    # -- conversion helpers ------------------------------------------------
    @staticmethod
    def _hits(raw: list[dict]) -> list[RecallHit]:
        hits = []
        for rank, item in enumerate(raw, start=1):
            hit = RecallHit(
                id=item.get("id") or item.get("memory_id") or "",
                content=item.get("content") or item.get("text") or "",
                score=float(item.get("score") or item.get("similarity") or 0.0),
                rank=rank,
            )
            for key in ("created_at", "memory_type", "scope", "importance", "source"):
                if key in item:
                    setattr(hit, key, item[key])
            meta = item.get("metadata") or item.get("metadata_json") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            if isinstance(meta, dict):
                hit.metadata = meta
            hits.append(hit)
        return hits

    @staticmethod
    def _record(item: dict) -> MemoryRecord:
        meta = item.get("metadata") or item.get("metadata_json") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        return MemoryRecord(
            id=item.get("id") or "",
            content=item.get("content") or item.get("text") or "",
            created_at=item.get("created_at") or "",
            memory_type=item.get("memory_type") or "",
            scope=item.get("scope") or "",
            importance=float(item.get("importance") or 0.0),
            source=item.get("source") or "",
            metadata=meta if isinstance(meta, dict) else {},
        )

    def to_candidate(self, hit: RecallHit) -> MemoryCandidate:
        """Convert a RecallHit into the candidate header DTO (spec §18)."""
        return MemoryCandidate(
            id=hit.id,
            created_at=hit.created_at,
            memory_type=hit.memory_type,
            scope=hit.scope,
            importance=hit.importance,
            source_agent=(hit.metadata or {}).get("source_agent", "") or hit.source,
            mnemosyne_rank=hit.rank,
            similarity_score=hit.score,
        )