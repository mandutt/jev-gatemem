"""P5 tool proxy — run Hermes mnemosyne_* tools inside the core process.

Single-writer goal: after the Hermes RPC switch, ALL mnemosyne access
(mnemosyne_remember / mnemosyne_recall / mnemosyne_batch / ...) must run in
the core process so the Hermes process never opens the DB writable.

Design (approved 2026-09-29):
  - The core reuses `mnemosyne_hermes.MnemosyneMemoryProvider` as the tool
    executor — the exact same class Hermes embeds, so tool semantics are
    byte-identical (no logic duplication).
  - A persistent provider instance is initialized ONCE at core startup with
    hermes_home=<hermes home> (the real DB) and session_id='core-tools'.
  - Each /v1/tools call dispatches handle_tool_call(tool, args) and returns
    the JSON string as-is.
  - Writes still go through Beam inside core — that is the single writer.
    Hermes never opens the DB with write access in rpc mode.

Threading: mnemosyne_hermes tools are synchronous; run them in the writer
thread (asyncio.to_thread) to serialize DB access with /v1/turns writes.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("jev_mem.tools")


class ToolExecutor:
    """Lazy-initialized mnemosyne_hermes provider used for tool dispatch."""

    def __init__(self, hermes_home: Optional[Path] = None,
                 mnemosyne_data_dir: Optional[Path] = None):
        self._hermes_home = Path(hermes_home) if hermes_home else None
        self._mnemosyne_data_dir = mnemosyne_data_dir
        self._provider = None
        self._init_error: Optional[str] = None

    @property
    def ready(self) -> bool:
        return self._provider is not None

    def _resolve_hermes_home(self) -> Path:
        if self._hermes_home:
            return self._hermes_home
        env = os.environ.get("HERMES_HOME")
        if env:
            return Path(env)
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "hermes"

    def ensure(self, session_id: str = "") -> Any:
        """Return the initialized provider (lazy, once). None on failure."""
        if self._provider is not None:
            return self._provider
        if self._init_error:
            return None
        try:
            from mnemosyne_hermes import MnemosyneMemoryProvider
            home = self._resolve_hermes_home()
            p = MnemosyneMemoryProvider()
            # A4 (2026-09-30): initialize with the FIRST caller session when
            # provided, so tool writes land in that session's scope instead of
            # a shared 'core-tools' bucket. Later /v1/tools calls with a
            # different session_id rebind via _rebind_session (below).
            init_session = session_id or "core-tools"
            if init_session.startswith("hermes_"):
                init_session = init_session[7:]  # avoid hermes_hermes_ double prefix
            p.initialize(init_session, hermes_home=str(home), platform="windows")
            self._provider = p
            self._bound_session = init_session
            log.info("tool executor initialized (hermes_home=%s, session=%s)",
                     home, init_session)
            return p
        except Exception as e:
            self._init_error = str(e)
            log.error("tool executor init failed: %s", e)
            return None

    _bound_session: str = "core-tools"

    def _rebind_session(self, session_id: str) -> None:
        """A4: switch the durable tool session when the caller's differs.

        Uses on_session_switch(reset=False) — no ledger reset, no data loss;
        only session-scoped state (beam session_id / channel_id) is rebound.

        Session-prefix normalization: mnemosyne_hermes unconditionally wraps
        the scope as f"hermes_{scope}" (_provider_session_id), so a caller
        passing an already-prefixed id would double it (measured:
        hermes_hermes_a4_live_probe). Strip a leading "hermes_" here.
        """
        if not session_id or session_id == self._bound_session:
            return
        scope = session_id[7:] if session_id.startswith("hermes_") else session_id
        try:
            self._provider.on_session_switch(scope, reset=False)
            self._bound_session = scope
            log.info("tool executor session rebound: %s", scope)
        except Exception as e:
            log.error("session rebind to %s failed: %s", scope, e)

    def tool_schemas(self) -> list:
        p = self.ensure()
        if p is None:
            return []
        try:
            return p.get_tool_schemas()
        except Exception as e:
            log.error("tool schemas failed: %s", e)
            return []

    def dispatch(self, tool_name: str, args: Dict[str, Any],
                 session_id: str = "") -> Dict[str, Any]:
        p = self.ensure(session_id)
        if p is None:
            return {"status": "memory_unavailable",
                    "tool": tool_name,
                    "error": f"tool executor unavailable: {self._init_error}"}
        if session_id:
            self._rebind_session(session_id)
        # tool_runner: sync function -> JSON string. Return as parsed JSON.
        try:
            raw = p.handle_tool_call(tool_name, args)
        except Exception as e:
            log.error("tool %s crashed: %s", tool_name, e)
            return {"status": "error", "tool": tool_name,
                    "error": f"tool dispatch failed: {e}"}
        try:
            import json
            return json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            # non-JSON string (rare) — wrap
            return {"status": "ok", "tool": tool_name, "result": raw}