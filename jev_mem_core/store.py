"""Turn storage inside the writer thread — 4-way gate branch + remember().

v1.1 D14: remember() embeds+INSERTs as one unit (~0.1s) — runs fully in the
writer thread. v1.1 D12: idem_key/source_agent/session_key ride in metadata
so crash-window requeue can detect already-stored turns via metadata_json.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional


def _remember_with_meta(beam, content: str, *, importance: float, source: str,
                        scope: str, session_key: str, idem_key: Optional[str],
                        source_agent: str, turn_id: str,
                        fail_open: Optional[str] = None) -> str:
    """beam.remember() with v1.1 D12 metadata. Returns memory_id."""
    meta: Dict[str, Any] = {
        "source_agent": source_agent,
        "session_key": session_key,
    }
    if idem_key:
        meta["idem_key"] = idem_key
    if turn_id:
        meta["turn_id"] = turn_id
    if fail_open:
        # F11: gate-less storage marker — enables later re-judging/cleanup
        meta["gate"] = f"fail_open:{fail_open}"
    return beam.remember(
        content=content,
        source=source,
        importance=importance,
        scope=scope,
        metadata=meta,
        extract_entities=True,
    )


def _config_store_redact() -> bool:
    """D-3 toggle: env JEV_MEM_STORE_REDACT=0 disables; config default ON."""
    v = os.environ.get("JEV_MEM_STORE_REDACT")
    if v is not None:
        return v not in ("0", "false", "False")
    return True  # default ON (config ops.store_redact mirrors this)


def store_kept(wctx, *, req: Dict, decisions: Dict, session_key: str,
               idem_key: Optional[str], turn_id: str) -> List[str]:
    """4-way branch (B §5.4, 기존 hermes_j1 로직 이동) — writer thread only.

    Returns memory_ids created ([] = both skipped).

    P5: session_key(예: hermes_<sid>)를 beam.session_id로 임시 설정해
    저장 행의 session_id가 Hermes 임베디드와 동일한 규칙을 따르게 한다
    (B §11.2 '세션 접두사 hermes_<session_id> 유지'). SingleWriter가
    직렬화하므로 런타임 교체는 안전하다.
    """
    beam = wctx.beam
    prev_sid = getattr(beam, "session_id", None)
    if session_key:
        beam.session_id = session_key
    try:
        return _store_kept_impl(beam, req, decisions, session_key, idem_key, turn_id)
    finally:
        if prev_sid is not None:
            beam.session_id = prev_sid


def _store_kept_impl(beam, req: Dict, decisions: Dict, session_key: str,
                     idem_key: Optional[str], turn_id: str) -> List[str]:
    user_keep = bool(decisions.get("user", {}).get("keep"))
    asst_keep = bool(decisions.get("assistant", {}).get("keep"))
    user = (req.get("user_content") or "").strip()
    asst = (req.get("assistant_content") or "").strip()
    # D-3 (2026-09-30, review F13): redact the STORE path so secrets never
    # reach mnemosyne.db (and thus other agents' prompts). Format-based
    # high-precision patterns only. Applied AFTER gate evaluation so the gate
    # sees the original text. Toggle: config ops.store_redact (default ON).
    from .redact import redact_text_high_precision
    if _config_store_redact():
        user = redact_text_high_precision(user)
        asst = redact_text_high_precision(asst)
    source_agent = req.get("agent", "")
    scope = req.get("scope", "session")

    ids: List[str] = []
    fo_user = (decisions.get("user", {}) or {}).get("fail_open")
    fo_asst = (decisions.get("assistant", {}) or {}).get("fail_open")

    if user_keep and asst_keep:
        if user:
            ids.append(_remember_with_meta(
                beam, f"[USER] {user}", importance=0.5, source="conversation",
                scope=scope, session_key=session_key, idem_key=idem_key,
                source_agent=source_agent, turn_id=turn_id, fail_open=fo_user))
        if asst:
            ids.append(_remember_with_meta(
                beam, f"[ASSISTANT] {asst}", importance=0.15, source="conversation",
                scope=scope, session_key=session_key, idem_key=idem_key,
                source_agent=source_agent, turn_id=turn_id, fail_open=fo_asst))
    elif user_keep:
        if user:
            ids.append(_remember_with_meta(
                beam, f"[USER] {user}", importance=0.5, source="conversation",
                scope=scope, session_key=session_key, idem_key=idem_key,
                source_agent=source_agent, turn_id=turn_id, fail_open=fo_user))
    elif asst_keep:
        if asst:
            ids.append(_remember_with_meta(
                beam, f"[ASSISTANT] {asst}", importance=0.15, source="conversation",
                scope=scope, session_key=session_key, idem_key=idem_key,
                source_agent=source_agent, turn_id=turn_id, fail_open=fo_asst))
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