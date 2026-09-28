"""Hermes harness — Jev-reranked Mnemosyne memory provider.

Design (approved 2026-09-27):
  - Subclasses mnemosyne_hermes.MnemosyneMemoryProvider so Mnemosyne's
    lifecycle, tools, sync_turn, recall_status etc. keep working unchanged.
  - Overrides ONLY prefetch(): runs the J1 pipeline
    (lane pool -> conservative gate -> Jev choice lift) and emits the same
    "## Mnemosyne Context" block format the base provider emits, so the
    model-facing contract is identical.
  - Fallback (spec §19): any lane/Jev failure -> base prefetch result.
  - Kill switch: JEV_RERANK=0 -> base prefetch (byte-identical to Mnemosyne).
  - Hermes core untouched; Mnemosyne core untouched.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from mnemosyne.core import beam as beam_mod
from mnemosyne_hermes import MnemosyneMemoryProvider

# J1 pipeline access only through the shadowing-safe accessor (see j1_access.py).
# Bare `from gateway.j1_pipeline import ...` breaks inside a real Hermes
# process because hermes-agent's own top-level `gateway` package shadows the
# middleware repo's package on sys.path.
from harnesses.j1_access import j1_pipeline as _j1_pipeline
from harnesses.wg_access import write_gate as _wg

log = logging.getLogger(__name__)

_PREFETCH_TOP_K = 5


class JevRerankProvider(MnemosyneMemoryProvider):
    """Mnemosyne provider whose prefetch is reranked by the J1 pipeline."""

    @property
    def name(self) -> str:  # keep provider name so Mnemosyne stays active
        return "mnemosyne"

    # -- prefetch override -------------------------------------------------
    def prefetch(self, query: str, *, session_id: str = "") -> str:
        base = super().prefetch(query, session_id=session_id)
        if not (query or "").strip():
            return base
        if not _jev_on():
            return base
        beam = getattr(self, "_beam", None)
        if beam is None:
            return base
        try:
            block = _prefetch_with_j1(self, beam, query, session_id)
        except Exception as exc:
            log.warning("J1 prefetch failed (%s); falling back to Mnemosyne base", exc)
            return base
        return block if (block or "").strip() else base

    # -- write gate override (P8+G-qual, 2026-09-28) ----------------------
    # G-qual (user): SKIP iff store==NO_STORE && type==NO_STORE && store_conf>=0.6
    # G-AS   (assistant): SKIP iff store==NO_STORE | (store==STORE && type==context)
    #   (gold50 precision 0.744/recall 0.935/F1 0.829 + ctx17 전수 검증 0오류, 2026-09-28)
    # Any JEV failure / kill switch -> base behavior (KEEP, no data loss).
    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "", messages=None) -> None:
        """Persist the turn to Mnemosyne, applying the JEV write gate to the
        user utterance (G-qual) and the assistant utterance (G-AS).
        G-qual: SKIP iff store==NO_STORE && type==NO_STORE && store_conf>=0.6.
        G-AS:   SKIP iff store==NO_STORE | (store==STORE && type==context).
        Four-way branch: both KEEP -> base; user SKIP -> assistant only;
        assistant SKIP -> user only; both SKIP -> nothing.
        Any JEV failure / kill switch -> base behavior (KEEP, no data loss).
        """
        wg = _wg()
        if wg is None:
            # accessor failed — never lose data, fall back to base
            return super().sync_turn(user_content, assistant_content, session_id=session_id, messages=messages)

        # -- user gate (G-qual) ------------------------------------------
        user_gate = (wg.evaluate(user_content)
                     if (user_content or "").strip() and len(user_content) > 5 else None)
        user_skip = bool(user_gate and user_gate.get("keep") is False)
        if user_skip:
            log.info(
                "write-gate SKIP user utterance (store=%s conf=%.2f type=%s conf=%.2f reason=%s)",
                user_gate.get("store"), user_gate.get("store_conf"),
                user_gate.get("type"), user_gate.get("type_conf"), user_gate.get("reason"),
            )

        # -- assistant gate (G-AS) ---------------------------------------
        asst_gate = None
        asst_skip = False
        if "assistant" in self._sync_roles:
            asst_gate = (wg.evaluate_assistant(assistant_content)
                         if (assistant_content or "").strip() and len(assistant_content) > 10 else None)
            asst_skip = bool(asst_gate and asst_gate.get("keep") is False)
            if asst_skip:
                log.info(
                    "write-gate SKIP assistant utterance (store=%s conf=%.2f type=%s conf=%.2f reason=%s)",
                    asst_gate.get("store"), asst_gate.get("store_conf"),
                    asst_gate.get("type"), asst_gate.get("type_conf"), asst_gate.get("reason"),
                )

        # -- four-way branch ---------------------------------------------
        if user_skip and asst_skip:
            return  # both gated out — nothing to persist
        if user_skip:
            return self._sync_turn_without_user(assistant_content, session_id=session_id, messages=messages)
        if asst_skip:
            return self._sync_turn_without_assistant(user_content, session_id=session_id, messages=messages)
        return super().sync_turn(user_content, assistant_content, session_id=session_id, messages=messages)

    def _sync_turn_without_user(self, assistant_content: str, *, session_id: str = "", messages=None) -> None:
        """Persist only the assistant side of a turn (user side was gated out).

        Mirrors the base sync_turn shape: beam-scoped, ledger-aware, identity
        capture skipped (it keys on user content), assistant stored with
        importance 0.15 as before. Any failure is logged, never raised.
        """
        try:
            self._maybe_retry_init()
            if not self._beam or self._agent_context in getattr(self, "_skip_contexts", set()):
                return
            ledger = getattr(self, "_verbatim_ledger", None)
            active_session = getattr(self, "_active_session_id", "")
            ticket = (ledger.begin(str(session_id or "").strip(), messages)
                      if ledger and active_session == str(session_id or "").strip() else None)
            with self._beam_session_scope(session_id) as beam:
                if beam is None:
                    return
                if "assistant" not in self._sync_roles:
                    return
                if not (assistant_content and len(assistant_content) > 10 and not self._should_filter(assistant_content)):
                    return
                ac = assistant_content
                from mnemosyne_hermes import _sync_turn_assistant_limit
                limit = _sync_turn_assistant_limit()
                if limit > 0:
                    ac = ac[:limit]
                capture = ledger.capture if ledger else None
                remember = (lambda **kw: capture(str(session_id or "").strip(), ticket, beam, ac, **kw)) if capture else beam.remember
                remember(
                    content=f"[ASSISTANT] {ac}",
                    source="conversation",
                    importance=0.15,
                    scope=self._default_scope,
                    extract_entities=True,
                )
        except Exception as e:
            log.debug("sync_turn_without_user failed: %s", e)

    def _sync_turn_without_assistant(self, user_content: str, *, session_id: str = "", messages=None) -> None:
        """Persist only the user side of a turn (assistant side was gated out).

        Mirrors the base sync_turn user branch: beam-scoped, ledger-aware,
        identity capture included, user stored with importance 0.5 as before.
        Any failure is logged, never raised.
        """
        try:
            self._maybe_retry_init()
            if not self._beam or self._agent_context in getattr(self, "_skip_contexts", set()):
                return
            ledger = getattr(self, "_verbatim_ledger", None)
            active_session = getattr(self, "_active_session_id", "")
            ticket = (ledger.begin(str(session_id or "").strip(), messages)
                      if ledger and active_session == str(session_id or "").strip() else None)
            with self._beam_session_scope(session_id) as beam:
                if beam is None:
                    return
                if "user" not in self._sync_roles:
                    return
                if not (user_content and len(user_content) > 5 and not self._should_filter(user_content)):
                    return
                uc = user_content
                from mnemosyne_hermes import _sync_turn_user_limit
                limit = _sync_turn_user_limit()
                if limit > 0:
                    uc = uc[:limit]
                capture = ledger.capture if ledger else None
                remember = (lambda **kw: capture(str(session_id or "").strip(), ticket, beam, uc, **kw)) if capture else beam.remember
                remember(
                    content=f"[USER] {uc}",
                    source="conversation",
                    importance=0.5,
                    scope=self._default_scope,
                    extract_entities=True,
                )
                self._capture_identity_signals(uc)
        except Exception as e:
            log.debug("sync_turn_without_assistant failed: %s", e)


# ---------------------------------------------------------------------------
# plugin-level helpers (module-scoped so the plugin wrapper can reuse them)
# ---------------------------------------------------------------------------
def _jev_on() -> bool:
    return _j1_pipeline().jev_enabled()


def _hydration_get(beam, memory_id: str) -> Optional[dict]:
    """Cross-session hydration via id-only lookup (working -> episodic).

    Mirrors BeamMemory.get()'s row -> dict shape but WITHOUT the
    ``(session_id = ? OR scope = 'global')`` filter, matching the lane
    searches (``_fts_search_working`` / ``_wm_vec_search``) which are
    cross-session. Without this, pool candidates from other sessions are
    search hits that hydration silently drops (observed: 14/62 pool-outside
    gold). Pure read; Mnemosyne core untouched.
    """
    conn = getattr(beam, "conn", None)
    if conn is None:
        # last-resort: public get() (session-scoped; may miss cross-session)
        return beam.get(memory_id)
    for table in ("working_memory", "episodic_memory"):
        row = conn.execute(
            f"SELECT id, content, source, timestamp, session_id,"
            f" importance, metadata_json, veracity, created_at"
            f" FROM {table} WHERE id = ?",
            (memory_id,),
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


def _prefetch_with_j1(provider, beam, query: str, session_id: str) -> str:
    """Run the J1 pipeline against the LIVE beam and format the result."""
    j1 = _j1_pipeline()
    JEV_CHOICE_TIMEOUT_S = j1.JEV_CHOICE_TIMEOUT_S
    POOL_DEFAULT_TOP = j1.POOL_DEFAULT_TOP
    _filter_and_rank = j1._filter_and_rank
    build_lane_pool = j1.build_lane_pool
    build_state = j1.build_state
    jev_rerank = j1.jev_rerank
    _excerpt = j1._excerpt

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
            row = _hydration_get(beam, arg)
            return row if isinstance(row, dict) else None
        return []

    pool = build_lane_pool(recall_raw, query)
    if not pool:
        return ""
    filtered = _filter_and_rank(pool, query)
    if not filtered:
        return ""

    # Hydrate missing fields on filtered rows (get() rows carry these)
    client = _typesafe_client()

    ranked = jev_rerank(
        query=query,
        pool=filtered[:POOL_DEFAULT_TOP],
        client=client,
        call_jev=client is not None,
        timeout=JEV_CHOICE_TIMEOUT_S,
    )
    ranked = ranked[:_PREFETCH_TOP_K]
    if not ranked:
        return ""

    return _format_block(ranked, query)


def _typesafe_client():
    """httpx client for TypeSafe System One; None if no key."""
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


def _format_block(rows: List[dict], query: str) -> str:
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


__all__ = ["JevRerankProvider", "load_j1_plugin"]