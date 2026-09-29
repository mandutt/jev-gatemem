"""Turn storage inside the writer thread — 4-way gate branch + remember().

v1.1 D14: remember() embeds+INSERTs as one unit (~0.1s) — runs fully in the
writer thread. v1.1 D12: idem_key/source_agent/session_key ride in metadata
so crash-window requeue can detect already-stored turns via metadata_json.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def _remember_with_meta(beam, content: str, *, importance: float, source: str,
                        scope: str, session_key: str, idem_key: Optional[str],
                        source_agent: str, turn_id: str) -> str:
    """beam.remember() with v1.1 D12 metadata. Returns memory_id."""
    meta: Dict[str, Any] = {
        "source_agent": source_agent,
        "session_key": session_key,
    }
    if idem_key:
        meta["idem_key"] = idem_key
    if turn_id:
        meta["turn_id"] = turn_id
    return beam.remember(
        content=content,
        source=source,
        importance=importance,
        scope=scope,
        metadata=meta,
        extract_entities=True,
    )


def store_kept(wctx, *, req: Dict, decisions: Dict, session_key: str,
               idem_key: Optional[str], turn_id: str) -> List[str]:
    """4-way branch (B §5.4, 기존 hermes_j1 로직 이동) — writer thread only.

    Returns memory_ids created ([] = both skipped).
    """
    beam = wctx.beam
    user_keep = bool(decisions.get("user", {}).get("keep"))
    asst_keep = bool(decisions.get("assistant", {}).get("keep"))
    user = (req.get("user_content") or "").strip()
    asst = (req.get("assistant_content") or "").strip()
    source_agent = req.get("agent", "")
    scope = req.get("scope", "session")

    ids: List[str] = []

    if user_keep and asst_keep:
        if user:
            ids.append(_remember_with_meta(
                beam, f"[USER] {user}", importance=0.5, source="conversation",
                scope=scope, session_key=session_key, idem_key=idem_key,
                source_agent=source_agent, turn_id=turn_id))
        if asst:
            ids.append(_remember_with_meta(
                beam, f"[ASSISTANT] {asst}", importance=0.15, source="conversation",
                scope=scope, session_key=session_key, idem_key=idem_key,
                source_agent=source_agent, turn_id=turn_id))
    elif user_keep:
        if user:
            ids.append(_remember_with_meta(
                beam, f"[USER] {user}", importance=0.5, source="conversation",
                scope=scope, session_key=session_key, idem_key=idem_key,
                source_agent=source_agent, turn_id=turn_id))
    elif asst_keep:
        if asst:
            ids.append(_remember_with_meta(
                beam, f"[ASSISTANT] {asst}", importance=0.15, source="conversation",
                scope=scope, session_key=session_key, idem_key=idem_key,
                source_agent=source_agent, turn_id=turn_id))
    # both SKIP -> nothing
    return ids


def find_stored_by_idem(conn, idem_key: str) -> Optional[str]:
    """Crash-window check (v1.1 D12): did this idem_key already land?

    Searches working_memory metadata_json for the marker. Returns memory_id
    if found. Requires the metadata JSON to be queryable via LIKE.
    """
    if not idem_key:
        return None
    row = conn.execute(
        "SELECT id FROM working_memory WHERE metadata_json LIKE ? LIMIT 1",
        (f'%"idem_key": "{idem_key}"%',),
    ).fetchone()
    return row[0] if row else None


def find_stored_by_idem_episodic(conn, idem_key: str) -> Optional[str]:
    """Same check over episodic_memory (consolidated rows)."""
    if not idem_key:
        return None
    row = conn.execute(
        "SELECT id FROM episodic_memory WHERE metadata_json LIKE ? LIMIT 1",
        (f'%"idem_key": "{idem_key}"%',),
    ).fetchone()
    return row[0] if row else None