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
import threading

from mnemosyne_hermes import MnemosyneMemoryProvider

# J1 pipeline access only through the shadowing-safe accessor (see j1_access.py).
# Bare `from gateway.j1_pipeline import ...` breaks inside a real Hermes
# process because hermes-agent's own top-level `gateway` package shadows the
# middleware repo's package on sys.path.
from harnesses.j1_access import j1_pipeline as _j1_pipeline
from harnesses.wg_access import write_gate as _wg
from core import j1_engine as _j1_engine

log = logging.getLogger(__name__)

_PREFETCH_TOP_K = 5

# P5 (2026-09-29): transport mode switch (B §11.2).
#   rpc      (기본) — core daemon 경유. Hermes는 mnemosyne.db를 열지 않음.
#   embedded (롤백) — v0.1.0 동작 (JevRerankProvider, 임베디드 beam + 게이트).
_MODE = os.environ.get("JEV_MEM_MODE", "rpc").strip().lower()
RPC_MODE = _MODE == "rpc"
log.info("JEV memory provider mode=%s (JEV_MEM_MODE=%s)", _MODE, os.environ.get("JEV_MEM_MODE") or "(default)")


class JevRpcProvider(MnemosyneMemoryProvider):
    """P5 — RPC provider: all memory access goes through jev-mem-core.

    - prefetch -> POST /v1/prefetch (degrade: '' on any failure — base
      fallback 금지, B §11.2)
    - sync_turn -> POST /v1/turns (fire-and-forget ack; 4-way gate 분기는
      core로 이전됨 — 이 클래스에는 게이트 코드 없음)
    - mnemosyne_* tools -> POST /v1/tools (core 프로세스의 단일 writer가 실행)
    - initialize(): 임베디드 beam을 만들지 않음 (split-brain 원천 차단,
      fastembed RAM을 core에만 로드)
    Real Hermes venv python이 필요 (import mnemosyne_hermes).
    """

    def __init__(self):
        super().__init__()
        from jev_mem_core.client import JevMemClient
        self._client = JevMemClient("hermes", auto_start=True, spool=True)
        self._init_lock = threading.Lock()
        self._initialized = False

    # -- lifecycle ------------------------------------------------------
    def is_available(self) -> bool:
        # core가 없으면 auto-start로 뜬다 (client.ensure_core). 항상 사용 가능.
        return True

    def initialize(self, session_id: str, **kwargs) -> None:
        """rpc 모드: beam 미생성. core 연결만 준비한다."""
        self._session_id = session_id
        self._hermes_home = kwargs.get("hermes_home", "")
        self._agent_context = kwargs.get("agent_context", "primary")
        self._skip_contexts = getattr(self, "_skip_contexts", set())
        self._initialized = True
        # Lazy: core 연결은 첫 prefetch/turn에서 (auto-start)

    def shutdown(self) -> None:
        pass  # core는 데몬으로 유지

    # -- prefetch / sync_turn -------------------------------------------
    def prefetch(self, query: str, *, session_id: str = "") -> str:
        try:
            return self._client.prefetch(
                query, session_id=session_id,
                timeout_ms=1500, rerank=True)
        except Exception as e:
            log.warning("JEV rpc prefetch failed (%s); empty context", e)
            return ""

    def sync_turn(self, user_content: str, assistant_content: str, *,
                  session_id: str = "", messages=None) -> None:
        """Fire-and-forget: ack 수신 후 반환. 실패 시 client가 스풀."""
        if not (user_content or "").strip() and not (assistant_content or "").strip():
            return
        uc = (user_content or "")[:262144]
        ac = (assistant_content or "")[:262144]
        try:
            self._client.turn({
                "agent": "hermes",
                "session_id": session_id or self._session_id or "",
                "user_content": uc,
                "assistant_content": ac,
                "turn_seq": None,
            })
        except Exception as e:
            log.warning("JEV rpc sync_turn failed (%s); spooled by client", e)

    # -- tools ----------------------------------------------------------
    def get_tool_schemas(self):
        """베이스와 동일한 툴 스키마 노출 (core가 실행)."""
        try:
            return super().get_tool_schemas()
        except Exception as e:
            log.error("get_tool_schemas failed: %s", e)
            return []

    def handle_tool_call(self, tool_name: str, args, **kwargs) -> str:
        """모든 mnemosyne_* 툴을 core로 프록시 (단일 writer)."""
        import json
        if not tool_name.startswith("mnemosyne_"):
            return json.dumps({"error": f"Unknown Mnemosyne tool: {tool_name}"})
        try:
            resp = self._client.tool(tool_name, dict(args or {}))
        except Exception as e:
            return json.dumps({"status": "error",
                               "error": f"JEV core tool call failed: {e}"})
        # resp: {"ok": true, "tool": ..., "result": {...}} or error shape
        if resp.get("ok"):
            result = resp.get("result")
            return json.dumps(result, ensure_ascii=False)
        return json.dumps({"status": "error", "error": resp.get("error", "core tool failed")})

    @property
    def name(self) -> str:
        return "mnemosyne"  # provider name 유지 — config/도구 연동 그대로

    def recall_status(self):
        return None  # rpc 모드에선 recall indicator 미제공 (prefetch 결과만)


def _make_provider():
    """register_memory_provider 용 팩토리 — 모드 분기."""
    if RPC_MODE:
        return JevRpcProvider()
    return JevRerankProvider()


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
        j1 = _j1_pipeline()
        if not _j1_engine.j1_on(j1):
            return base
        beam = getattr(self, "_beam", None)
        if beam is None:
            return base
        try:
            block = _j1_engine.run(
                beam,
                query,
                pipeline=j1,
                client=_j1_engine.typesafe_client(),
                top_k=_PREFETCH_TOP_K,
            )
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


__all__ = ["JevRerankProvider", "JevRpcProvider", "_make_provider", "load_j1_plugin"]