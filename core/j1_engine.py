"""J1 pipeline engine — Hermes-independent core.

This module is the agent-agnostic heart of the JEV rerank + prefetch path.
It knows NOTHING about Hermes (no mnemosyne_hermes, no MemoryProvider, no
plugin discovery). It receives:

  - ``beam``: a Mnemosyne BeamMemory instance (or anything with ``conn`` and
    the same recall surface)
  - ``pipeline``: the loaded ``gateway.j1_pipeline`` module (injected by the
    caller so this module never imports a shadow-prone top-level package)

and returns the ``## Mnemosyne Context`` block string exactly as the
Mnemosyne base provider formats it, so the model-facing contract is
identical on any agent.

Fallback semantics (spec §19): any failure inside the engine returns "" so
the caller can fall back to its base provider. This module never raises.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Dict, List, Optional

from mnemosyne.core import beam as beam_mod  # Mnemosyne SDK — agent-agnostic

_DEFAULT_TOP_K = 5


def j1_on(pipeline) -> bool:
    """JEV_RERANK kill-switch check (delegates to the injected pipeline)."""
    return bool(pipeline and pipeline.jev_enabled())


def typesafe_client():
    """httpx client for TypeSafe System One; None if no key / import fails."""
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


def hydration_get(beam, memory_id: str) -> Optional[dict]:
    """Cross-session hydration via id-only lookup (working -> episodic).

    Mirrors BeamMemory.get()'s row -> dict shape but WITHOUT the
    ``(session_id = ? OR scope = 'global')`` filter, matching the lane
    searches (``_fts_search_working`` / ``_wm_vec_search``) which are
    cross-session. Without this, pool candidates from other sessions are
    search hits that hydration silently drops (observed: 14/62 pool-outside
    gold). Pure read; Mnemosyne core untouched.

    2026-10-03 archived-filter: FTS/imp/graph lane 원시 쿼리에는 temporal
    필터가 없고(vec lane만 보유) hydration이 pool의 단일 choke point이므로
    여기서 superseded_by/valid_until 필터를 강제한다 — 재판정 skip(archived)
    행이 FTS 경유로 pool에 재유입되는 회귀를 실측('좋아 진행해줘' pool 3건).
    """
    conn = getattr(beam, "conn", None)
    if conn is None:
        # last-resort: public get() (session-scoped; may miss cross-session)
        return beam.get(memory_id)
    now_iso = datetime.now().isoformat()
    for table in ("working_memory", "episodic_memory"):
        row = conn.execute(
            f"SELECT id, content, source, timestamp, session_id,"
            f" importance, metadata_json, veracity, created_at"
            f" FROM {table} WHERE id = ?"
            f" AND superseded_by IS NULL"
            f" AND (valid_until IS NULL OR valid_until > ?)",
            (memory_id, now_iso),
        ).fetchone()
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


def format_block(rows: List[dict], query: str) -> str:
    """Emit the exact '## Mnemosyne Context' block format the base provider
    uses, so downstream prompt parsing keeps working."""
    lines = ["## Mnemosyne Context"]
    for r in rows:
        content = " ".join((r.get("content") or "").split())
        ts = str(r.get("timestamp") or r.get("created_at") or "")[:16]
        imp = float(r.get("importance") or 0.0)
        trust = str(r.get("trust_tier") or "STATED")
        trust_tag = f" [{trust}]" if trust != "STATED" else ""
        source = str(r.get("source") or "").strip()
        source_tag = f", source {source}" if source and source != "conversation" else ""
        lines.append(f"  [{ts}] (importance {imp:.2f}{source_tag}){trust_tag} {content}")
    return "\n".join(lines)


def run(
    beam,
    query: str,
    *,
    pipeline,
    client=None,
    top_k: int = _DEFAULT_TOP_K,
    timeout: Optional[float] = None,
) -> str:
    """Run the J1 pipeline against the LIVE beam and format the result.

    Args:
        beam: Mnemosyne BeamMemory instance (or compatible).
        query: the prefetch query text.
        pipeline: loaded ``gateway.j1_pipeline`` module (injected).
        client: optional httpx client for JEV choice; None -> JEV skipped.
        top_k: how many ranked rows to include in the block.
        timeout: JEV choice hard cap; defaults to pipeline.JEV_CHOICE_TIMEOUT_S.

    Returns:
        The ``## Mnemosyne Context`` block string, or "" on any failure /
        empty pool (caller falls back to its base provider).
    """
    try:
        return _run(beam, query, pipeline=pipeline, client=client,
                    top_k=top_k, timeout=timeout)
    except Exception:
        # spec §19: engine failure -> caller falls back, never raises
        return ""


def _run(beam, query: str, *, pipeline, client, top_k: int, timeout) -> str:
    j1 = pipeline
    j1_timeout = timeout if timeout is not None else j1.JEV_CHOICE_TIMEOUT_S
    pool_top = j1.POOL_DEFAULT_TOP
    _filter_and_rank = j1._filter_and_rank
    build_lane_pool = j1.build_lane_pool
    jev_rerank = j1.jev_rerank

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
            row = hydration_get(beam, arg)
            return row if isinstance(row, dict) else None
        return []

    pool = build_lane_pool(recall_raw, query)
    if not pool:
        return ""
    filtered = _filter_and_rank(pool, query, min_distinctive=1, min_coverage=0.0)
    if not filtered:
        return ""

    ranked, _abstained = jev_rerank(
        query=query,
        pool=filtered[:pool_top],
        client=client,
        call_jev=client is not None,
        timeout=j1_timeout,
    )
    ranked = ranked[:top_k]
    if not ranked:
        return ""

    return format_block(ranked, query)


__all__ = ["run", "j1_on", "typesafe_client", "hydration_get", "format_block"]