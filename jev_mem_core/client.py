"""jev-mem-client — shared adapter client (B §11.1, D4 auto-start).

Single-file, stdlib-only (urllib). Used by Hermes/pi/codex/opencode
adapters and the `jev-mem-client` CLI.

- Reads port from core.json, token from token file.
- Lazy auto-start: if core.json missing or health probe fails, spawns
  `python -m jev_mem_core --serve` detached once, waits for readiness.
- prefetch() -> str (empty on failure)  [degrade, never error]
- turn() -> dict (spools to JSONL on hard failure)
- 401 -> re-read token, retry once (B §11.1).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from .spool import SpoolWriter

DEFAULT_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "jev-mem"
AUTO_START_TIMEOUT_S = 20.0
HEALTH_PROBE_TIMEOUT_S = 0.5


class JevMemClient:
    def __init__(self, agent: str, data_dir: Optional[Path] = None,
                 auto_start: bool = True, spool: bool = True,
                 port: Optional[int] = None):
        self.agent = agent
        self.data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        self.auto_start = auto_start
        self.port = port  # explicit port (else read from core.json)
        self.core_json = self.data_dir / "core.json"
        self.token_path = self.data_dir / "token"
        self._token: Optional[str] = None
        self.spool_writer = (SpoolWriter(self.data_dir / "spool", agent)
                             if spool else None)

    # -- discovery / auto-start ------------------------------------------
    def _read_core_json(self) -> Optional[Dict]:
        try:
            return json.loads(self.core_json.read_text(encoding="utf-8"))
        except Exception:
            return None

    def base_url(self) -> Optional[str]:
        if self.port:
            return f"http://127.0.0.1:{self.port}/v1"
        meta = self._read_core_json()
        if not meta:
            return None
        port = meta.get("port")
        if not port:
            return None
        return f"http://127.0.0.1:{port}/v1"

    def ensure_core(self) -> Optional[str]:
        """Return base URL if a core is (or becomes) reachable; else None."""
        base = self.base_url()
        if base and self._probe(base):
            return base
        if not self.auto_start:
            return None
        # lazy auto-start (D4): spawn detached, wait for readiness.
        # core.json may not exist yet — poll until it appears, then probe.
        try:
            self._spawn_core()
        except Exception as e:
            print(f"jev-mem: auto-start failed: {e}", file=sys.stderr)
            return None
        t0 = time.monotonic()
        while time.monotonic() - t0 < AUTO_START_TIMEOUT_S:
            base = self.base_url()
            if base and self._probe(base):
                return base
            if base is None and self.core_json.exists():
                # core.json exists but health not ready yet — keep probing
                pass
            time.sleep(0.3)
        return None

    def _probe(self, base: str) -> bool:
        try:
            req = urllib.request.Request(f"{base}/health", method="GET")
            with urllib.request.urlopen(req, timeout=HEALTH_PROBE_TIMEOUT_S) as r:
                return r.status == 200
        except Exception:
            return False

    def _spawn_core(self) -> None:
        """Detached core spawn: python -m jev_mem_core --serve.

        Windows: DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP, stdio to
        data_dir/logs/core.out.log. The core's own singleton guard makes
        concurrent spawns harmless (only one survives).
        """
        py = sys.executable
        cmd = [py, "-m", "jev_mem_core", "--serve"]
        env = dict(os.environ)
        # if this client targets a non-default data dir, the spawned core
        # must inherit the same port/data-dir (tests use scratch dirs)
        env.setdefault("JEV_MEM_DATA_DIR", str(self.data_dir))
        env.setdefault("JEV_MEM_DB", str(self.data_dir / "mnemosyne.db"))
        if self.port:
            env["JEV_MEM_PORT"] = str(self.port)
        if sys.platform == "win32":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(
                subprocess, "DETACHED_PROCESS", 0)
            shell = False
            logf = self.data_dir / "logs"
            logf.mkdir(parents=True, exist_ok=True)
            out = open(logf / "core.out.log", "ab")
            try:
                subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL,
                                 stdout=out, stderr=subprocess.STDOUT,
                                 creationflags=flags, close_fds=True)
            finally:
                out.close()
        else:
            subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True,
                             close_fds=True)

    # -- auth ------------------------------------------------------------
    def _token(self) -> str:
        if self._token:
            return self._token
        try:
            self._token = self.token_path.read_text(encoding="utf-8").strip()
        except Exception:
            self._token = ""
        return self._token

    def _headers(self, use_token: bool = True) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if use_token:
            t = self._token()
            if t:
                h["Authorization"] = f"Bearer {t}"
        return h

    # -- API -------------------------------------------------------------
    def prefetch(self, query: str, *, session_id: str = "",
                 max_chars: int = 6000, timeout_ms: int = 1500,
                 rerank: bool = True) -> str:
        """Returns '## Mnemosyne Context' block ('' on any failure)."""
        base = self.ensure_core()
        if not base:
            return ""
        body = json.dumps({
            "agent": self.agent, "query": query, "session_id": session_id,
            "options": {"max_chars": max_chars, "timeout_ms": timeout_ms,
                        "rerank": rerank},
        }).encode("utf-8")
        for attempt in (0, 1):
            try:
                req = urllib.request.Request(
                    f"{base}/prefetch", data=body, headers=self._headers(),
                    method="POST")
                with urllib.request.urlopen(req, timeout=max(timeout_ms / 1000 + 1, 3)) as r:
                    data = json.loads(r.read().decode("utf-8"))
                return data.get("context") or ""
            except urllib.error.HTTPError as e:
                if e.code == 401 and attempt == 0:
                    self._token = None  # re-read token file once (B §11.1)
                    continue
                return ""
            except Exception:
                return ""
        return ""

    def turn(self, payload: Dict, *, timeout_s: float = 40.0) -> Dict:
        """POST /v1/turns (async). On final failure -> spool (D6)."""
        payload = dict(payload)
        payload.setdefault("agent", self.agent)
        if not payload.get("idempotency_key"):
            payload["idempotency_key"] = self._make_idem_key(payload)
        base = self.ensure_core()
        if not base:
            self._spool(payload)
            return {"ok": False, "status": "spooled", "error": "core unreachable"}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        for attempt in (0, 1):
            try:
                req = urllib.request.Request(
                    f"{base}/turns", data=body, headers=self._headers(), method="POST")
                with urllib.request.urlopen(req, timeout=timeout_s) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 401 and attempt == 0:
                    self._token = None
                    continue
                if 400 <= e.code < 500:
                    # 4xx not retryable, not spoolable (B §9.2)
                    try:
                        return json.loads(e.read().decode("utf-8"))
                    except Exception:
                        return {"ok": False, "status": "error", "error": f"HTTP {e.code}"}
                # 5xx: retry once, then spool
                time.sleep(0.3)
            except Exception:
                time.sleep(0.3)
        self._spool(payload)
        return {"ok": False, "status": "spooled", "error": "core failed"}

    # -- spool / idem -----------------------------------------------------
    def _spool(self, payload: Dict) -> None:
        if self.spool_writer is None:
            return
        try:
            # B §5.3 (승인 2): 어댑터 스풀 저장분도 redaction (활성 시)
            from .redact import redact_payload
            sp = redact_payload(payload)
            ok = self.spool_writer.append(sp)
            if not ok:
                print("jev-mem: spool append failed", file=sys.stderr)
        except Exception as e:
            print(f"jev-mem: spool error: {e}", file=sys.stderr)

    @staticmethod
    def _make_idem_key(payload: Dict) -> str:
        import uuid
        agent = payload.get("agent") or "x"
        session_id = payload.get("session_id") or "x"
        seq = payload.get("turn_seq")
        if seq is not None:
            return f"{agent}:{session_id}:{seq}"
        return f"{agent}:{session_id}:{uuid.uuid4().hex[:12]}"


def cli_main() -> int:
    import argparse

    p = argparse.ArgumentParser(prog="jev-mem-client")
    p.add_argument("--agent", default="cli")
    p.add_argument("--data-dir", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("prefetch")
    pf.add_argument("query")
    pf.add_argument("--session-id", default="")
    pf.add_argument("--max-chars", type=int, default=6000)
    pf.add_argument("--timeout-ms", type=int, default=1500)
    pf.add_argument("--no-rerank", action="store_true")

    tf = sub.add_parser("turn")
    tf.add_argument("--session-id", required=True)
    tf.add_argument("--user", default="")
    tf.add_argument("--assistant", default="")
    tf.add_argument("--turn-seq", type=int, default=None)
    tf.add_argument("--stdin", action="store_true",
                    help="read full JSON payload from stdin")

    args = p.parse_args()
    client = JevMemClient(args.agent,
                          Path(args.data_dir) if args.data_dir else None)
    if args.cmd == "prefetch":
        ctx = client.prefetch(args.query, session_id=args.session_id,
                              max_chars=args.max_chars,
                              timeout_ms=args.timeout_ms,
                              rerank=not args.no_rerank)
        if ctx:
            print(ctx)
        return 0 if ctx else 1
    if args.cmd == "turn":
        if args.stdin:
            payload = json.load(sys.stdin)
        else:
            payload = {"session_id": args.session_id, "user_content": args.user,
                       "assistant_content": args.assistant}
            if args.turn_seq is not None:
                payload["turn_seq"] = args.turn_seq
        res = client.turn(payload)
        print(json.dumps(res, ensure_ascii=False))
        return 0 if res.get("ok") else 1
    return 2


if __name__ == "__main__":
    sys.exit(cli_main())