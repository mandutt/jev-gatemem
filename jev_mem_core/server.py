"""jev-mem-core HTTP server (B §5, P1).

- aiohttp on 127.0.0.1:47821 (configurable).
- Bearer token auth (except /v1/health), Origin/Host guards (CSRF/DNS-rebinding).
- Endpoints: GET /v1/health, POST /v1/prefetch, POST /v1/turns,
  GET /v1/turns/{id}, GET /v1/status, POST /v1/admin/shutdown.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from aiohttp import web
except ImportError:  # pragma: no cover
    web = None

from . import __version__, PROTOCOL
from .config import Config
from .pipeline import Pipeline
from .tools import ToolExecutor

log = logging.getLogger("jev_mem.server")

# limits (B §5.1)
MAX_BODY_BYTES = 1_048_576
MAX_FIELD_CHARS = 256 * 1024  # 256 KiB per content field
AGENT_RE = None  # validated in validate() below


def _agent_valid(agent: str) -> bool:
    if not agent or len(agent) < 1 or len(agent) > 32:
        return False
    for ch in agent:
        if not (ch.isalnum() or ch in "-_"):
            return False
    return agent[0].isalnum()


class CoreServer:
    def __init__(self, cfg: Config, ctx: Any, token: str):
        self.cfg = cfg
        self.ctx = ctx
        self.token = token
        self.pipeline = Pipeline(ctx)
        self.tools = ToolExecutor()  # P5: mnemosyne_* tool proxy (single writer)
        self.app = None
        self._runner = None
        self._site = None
        self._shutdown_evt = asyncio.Event()

    # ---- startup / shutdown -------------------------------------------
    async def start(self) -> None:
        if web is None:
            raise RuntimeError("aiohttp not installed")
        self.app = web.Application(client_max_size=MAX_BODY_BYTES)
        self.app.router.add_get("/v1/health", self.handle_health)
        self.app.router.add_post("/v1/prefetch", self.handle_prefetch)
        self.app.router.add_post("/v1/turns", self.handle_turns)
        self.app.router.add_get("/v1/turns/{turn_id}", self.handle_turn_get)
        self.app.router.add_post("/v1/tools", self.handle_tools)  # P5
        self.app.router.add_get("/v1/status", self.handle_status)
        self.app.router.add_get("/v1/metrics", self.handle_metrics)
        self.app.router.add_post("/v1/spool/flush", self.handle_spool_flush)
        self.app.router.add_post("/v1/admin/shutdown", self.handle_shutdown)
        self.app.middlewares.append(self.security_middleware)
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.cfg.host, self.cfg.port)
        await self._site.start()
        log.info("jev-mem-core listening on %s:%s (protocol %d)",
                 self.cfg.host, self.cfg.port, PROTOCOL)

    async def stop(self) -> None:
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()

    # ---- middleware ---------------------------------------------------
    @web.middleware
    async def security_middleware(self, request, handler):
        # Origin guard (browser CSRF)
        origin = request.headers.get("Origin")
        if origin and origin not in (f"http://{self.cfg.host}:{self.cfg.port}",):
            return self._error(403, "FORBIDDEN_ORIGIN", "origin not allowed")
        # Host guard (DNS rebinding)
        host = request.headers.get("Host", "")
        if host and not self._host_ok(host):
            return self._error(403, "FORBIDDEN_ORIGIN", "host not allowed")
        # Auth (health exempt)
        if request.path != "/v1/health":
            auth = request.headers.get("Authorization", "")
            if not self._auth_ok(auth):
                return self._error(401, "UNAUTHORIZED", "missing/invalid token")
        return await handler(request)

    def _host_ok(self, host: str) -> bool:
        return host in (f"{self.cfg.host}:{self.cfg.port}", f"{self.cfg.host}")

    def _auth_ok(self, auth: str) -> bool:
        if not auth.startswith("Bearer "):
            return False
        return secrets.compare_digest(auth[7:].strip(), self.token)

    # ---- handlers -----------------------------------------------------
    def _error(self, status: int, code: str, message: str, *, retryable: bool = False,
               retry_after_ms: Optional[int] = None) -> web.Response:
        body = {"ok": False, "error": {"code": code, "message": message,
                                       "retryable": retryable}}
        if retry_after_ms is not None:
            body["error"]["retry_after_ms"] = retry_after_ms
        return web.json_response(body, status=status)

    async def handle_health(self, request) -> web.Response:
        return web.json_response({
            "status": "ready",
            "protocol": PROTOCOL,
            "version": __version__,
        })

    async def handle_prefetch(self, request) -> web.Response:
        self.ctx.touch_activity()  # D-5: real work refreshes idle clock
        try:
            body = await request.json()
        except Exception:
            return self._error(400, "INVALID_REQUEST", "body must be JSON")
        if not isinstance(body, dict):
            return self._error(400, "INVALID_REQUEST", "body must be object")
        agent = str(body.get("agent") or "")
        if not _agent_valid(agent):
            return self._error(400, "INVALID_REQUEST", "invalid agent")
        query = str(body.get("query") or "")
        if len(query) > 8000:
            return self._error(400, "INVALID_REQUEST", "query too long (max 8000)")
        try:
            result = await self.pipeline.process_prefetch(body)
        except Exception as e:
            log.exception("prefetch crashed")
            return self._error(500, "INTERNAL", str(e)[:200], retryable=True)
        return web.json_response({"ok": True, **result})

    async def handle_turns(self, request) -> web.Response:
        self.ctx.touch_activity()  # D-5
        try:
            body = await request.json()
        except Exception:
            return self._error(400, "INVALID_REQUEST", "body must be JSON")
        if not isinstance(body, dict):
            return self._error(400, "INVALID_REQUEST", "body must be object")
        # field validation (D5: idempotency_key required from adapter)
        agent = str(body.get("agent") or "")
        if not _agent_valid(agent):
            return self._error(400, "INVALID_REQUEST", "invalid agent")
        session_id = str(body.get("session_id") or "")
        if not session_id:
            return self._error(400, "INVALID_REQUEST", "session_id required")
        user = str(body.get("user_content") or "")
        asst = str(body.get("assistant_content") or "")
        if len(user) > MAX_FIELD_CHARS or len(asst) > MAX_FIELD_CHARS:
            return self._error(413, "PAYLOAD_TOO_LARGE", "content too large")
        idem_key = body.get("idempotency_key")
        if idem_key is None:
            return self._error(400, "INVALID_REQUEST",
                               "idempotency_key required (adapter always generates — v1.0 D5)")
        if not isinstance(idem_key, str) or not (8 <= len(idem_key) <= 128):
            return self._error(400, "INVALID_REQUEST", "invalid idempotency_key")
        mode = str(body.get("mode") or "async")
        # enrich request
        body["agent"] = agent
        body["session_id"] = session_id
        body["idempotency_key"] = idem_key
        try:
            result = await self.pipeline.process_turn(body)
        except Exception as e:
            log.exception("turn crashed")
            return self._error(500, "INTERNAL", str(e)[:200], retryable=True)
        if result.get("status") == "pending_gate":
            return web.json_response({"ok": True, **result}, status=202)
        if not result.get("ok"):
            code = (result.get("error") or {}).get("code", "INTERNAL")
            return web.json_response(result, status=409 if code == "IDEMPOTENCY_CONFLICT" else 503)
        if mode == "sync":
            return web.json_response({"ok": True, **result}, status=200)
        return web.json_response({"ok": True, **result}, status=202)

    async def handle_turn_get(self, request) -> web.Response:
        turn_id = request.match_info.get("turn_id", "")
        from . import ledger
        try:
            row = await self.ctx.writer.submit(
                lambda w: ledger.ledger_get(w.state, turn_id if turn_id.startswith("t_") else "") or
                          self._get_by_turn_id(w.state, turn_id),
                "ledger_get")
        except Exception:
            row = None
        if not row:
            return self._error(404, "NOT_FOUND", "turn not found")
        return web.json_response({"ok": True, "turn_id": turn_id, **row})

    def _get_by_turn_id(self, state_conn, turn_id: str) -> Optional[Dict]:
        from . import ledger
        row = state_conn.execute(
            "SELECT * FROM ingest_ledger WHERE turn_id = ?", (turn_id,)
        ).fetchone()
        return ledger._row_dict(row) if row else None

    async def handle_tools(self, request) -> web.Response:
        """P5 — mnemosyne_* tool proxy. Body: {tool, args}.

        Runs the tool in the writer thread (serialized with /v1/turns writes),
        returns the tool's JSON result as-is.
        """
        self.ctx.touch_activity()  # D-5
        try:
            body = await request.json()
        except Exception:
            return self._error(400, "INVALID_REQUEST", "body must be JSON")
        if not isinstance(body, dict):
            return self._error(400, "INVALID_REQUEST", "body must be object")
        tool_name = str(body.get("tool") or "")
        args = body.get("args") or {}
        if not tool_name or not tool_name.startswith("mnemosyne_"):
            return self._error(400, "INVALID_REQUEST",
                               "tool must be a mnemosyne_* tool name")
        if not isinstance(args, dict):
            return self._error(400, "INVALID_REQUEST", "args must be object")
        try:
            # run INSIDE the writer thread so tool DB access is serialized
            # with /v1/turns writes (single writer guarantee)
            result = await self.ctx.writer.submit(
                lambda w: self.tools.dispatch(tool_name, args,
                                              session_id=str(body.get("session_id") or "")),
                f"tool_{tool_name}")
        except Exception as e:
            log.exception("tool dispatch crashed")
            return self._error(500, "INTERNAL", str(e)[:200], retryable=True)
        return web.json_response({"ok": True, "tool": tool_name, "result": result})

    async def handle_status(self, request) -> web.Response:
        pending = -1
        try:
            from . import ledger
            pending = await self.ctx.writer.submit(
                lambda w: ledger.pending_gate_count(w.state), "status_pending")
        except Exception:
            pass
        # Δ5 (F11/F15): degraded flag + reasons — adapters check this to
        # surface silent-degradation states instead of failing open quietly.
        spool_files = self.ctx.scanner.pending_files if self.ctx.scanner else 0
        reasons = []
        if self.ctx.breaker.is_open:
            reasons.append("jev_circuit_open")
        if self.ctx.fail_open_streak >= 5:
            reasons.append("gate_fail_open_streak")
        if pending > 50:
            reasons.append("pending_gate_backlog")
        if spool_files > 0:
            reasons.append("spool_backlog")
        # P1 (S4): embedding warmup failure — reachable only in warn mode
        # (JEV_MEM_EMBED_WARMUP=warn); default mode refuses to start.
        if not self.ctx.embedding.get("warmup_ok"):
            reasons.append("embedding_warmup_failed")
        return web.json_response({
            "status": "ready",
            "degraded": bool(reasons),
            "degraded_reasons": reasons,
            "gate_fail_open_total": self.ctx.stats.get("gate_fail_open_total", 0),
            "uptime_s": round(time.monotonic() - self.ctx.started_at, 1),
            "version": __version__,
            "protocol": PROTOCOL,
            "db": {"path": str(self.cfg.mnemosyne_db), "writable": True,
                   "synced_folder_warning": self.ctx.synced_folder_warning},
            "embedding": dict(self.ctx.embedding),
            "jev": {"circuit": self.ctx.breaker.state,
                    "consecutive_failures": self.ctx.breaker.consecutive},
            "queues": {"writer_depth": self.ctx.writer.depth, "pending_gate": pending,
                       "spool_files": spool_files},
            "stats": self.ctx.stats,
        })

    async def handle_metrics(self, request) -> web.Response:
        """B §14 — JSON metrics (no Prometheus dependency)."""
        try:
            import psutil
            rss_mb = round(psutil.Process().memory_info().rss / 1048576, 1)
        except Exception:
            rss_mb = -1.0  # psutil not installed
        st = self.ctx.stats
        return web.json_response({
            "uptime_s": round(time.monotonic() - self.ctx.started_at, 1),
            "version": __version__,
            "jev": {"circuit": self.ctx.breaker.state,
                    "calls": st["jev_calls"], "failures": st["jev_failures"]},
            "writer_queue_depth": self.ctx.writer.depth,
            "turns": st["turns"],
            "dedup_count": st["dedup_count"],
            "prefetch": {"total": st["prefetch_total"],
                         "degraded": st["prefetch_degraded"],
                         "degraded_ratio": round(
                             (st["prefetch_degraded"] / st["prefetch_total"])
                             if st["prefetch_total"] else 0.0, 4)},
            "spool": {"pending_files": (self.ctx.scanner.pending_files
                                        if self.ctx.scanner else 0),
                      "replayed": st["spool_replayed"]},
            "embed_ms": st["embed_ms"],
            "rss_mb": rss_mb,
            "synced_folder_warning": self.ctx.synced_folder_warning,
        })

    async def handle_spool_flush(self, request) -> web.Response:
        """B §9.3 — trigger an immediate spool scan/replay."""
        if self.ctx.scanner is None:
            return self._error(503, "NOT_READY", "spool scanner not initialized")
        try:
            r = await asyncio.to_thread(self.ctx.scanner.scan_once)
        except Exception as e:
            log.exception("spool flush failed")
            return self._error(500, "INTERNAL", str(e)[:200], retryable=True)
        return web.json_response({"ok": True, **r})

    async def handle_shutdown(self, request) -> web.Response:
        asyncio.get_running_loop().call_later(0.1, self._shutdown_evt.set)
        return web.json_response({"ok": True, "status": "shutting_down"}, status=202)