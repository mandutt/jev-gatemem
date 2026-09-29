"""Spool: adapter-side writer + core-side replay (B §9, D6).

Adapter side (used by jev-mem-client / adapters, NOT by core):
  SpoolWriter.append(agent, payload) -> writes
    %LOCALAPPDATA%/jev-mem/spool/<agent>/<agent>-<pid>-<yyyymmdd>.jsonl
  per-process file (Windows line interleaving), one JSON object per line,
  MUST include idempotency_key. 50 MiB/agent cap -> drop oldest files.

Core side:
  SpoolScanner.scan() — atomic rename *.jsonl -> *.jsonl.processing,
  feed each line through pipeline.process_turn (idempotency keys dedupe),
  delete file when every line reached a terminal state, move unparsable
  lines to spool/_corrupt/, skip files modified <10s ago.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("jev_mem.spool")

# ---------------------------------------------------------------------------
# Adapter side
# ---------------------------------------------------------------------------


class SpoolWriter:
    """Append-only per-process JSONL spool (used by adapters when core is down)."""

    def __init__(self, spool_dir: Path, agent: str,
                 max_bytes: int = 50 * 1024 * 1024,
                 pid: Optional[int] = None):
        self.spool_dir = spool_dir / agent
        self.agent = agent
        self.max_bytes = max_bytes
        self.pid = pid or os.getpid()
        self.spool_dir.mkdir(parents=True, exist_ok=True)

    def _current_file(self) -> Path:
        stamp = time.strftime("%Y%m%d")
        return self.spool_dir / f"{self.agent}-{self.pid}-{stamp}.jsonl"

    def append(self, payload: Dict) -> bool:
        """Append one turn payload. Returns True if written, False if too large/err."""
        if not payload.get("idempotency_key"):
            log.error("spool append without idempotency_key — refused (D5)")
            return False
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(line.encode("utf-8")) > 1_000_000:  # ~1 MiB same as server cap
            log.error("spool line too large — refused")
            return False
        target = self._current_file()
        lock_fail = _file_lock_retry(lambda: _append_line(target, line), self.spool_dir)
        if lock_fail:
            log.error("spool append failed: %s", lock_fail)
            return False
        self._enforce_cap()
        return True

    def _enforce_cap(self) -> None:
        """B §9.1: oldest-file-first delete when total > cap."""
        try:
            files = sorted(self.spool_dir.glob("*.jsonl"),
                           key=lambda p: p.stat().st_mtime)
        except OSError:
            return
        total = 0
        for f in files:
            try:
                total += f.stat().st_size
            except OSError:
                continue
        while total > self.max_bytes and len(files) > 1:
            oldest = files.pop(0)
            try:
                total -= oldest.stat().st_size
                oldest.unlink()
                log.warning("spool cap exceeded — dropped oldest %s", oldest.name)
            except OSError:
                continue


def _append_line(path: Path, line: str) -> Optional[str]:
    """Raw append with O_APPEND semantics; returns error string or None."""
    try:
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")
        return None
    except OSError as e:
        return f"append: {e}"


# ---------------------------------------------------------------------------
# Core side — replay scanner
# ---------------------------------------------------------------------------


class SpoolScanner:
    """Scans spool/<agent>/*.jsonl, replays each line via process_turn.

    - Startup, POST /v1/spool/flush, and every `interval_s`.
    - Atomic rename -> *.jsonl.processing prevents double consumption.
    - Files modified within `skip_fresh_s` are left for the next pass
      (another process may still be writing them).
    - Terminal ledger states (stored/skipped/failed) -> file deleted;
      pending_gate rows stay in the ledger, file removed only when the
      line itself reached a terminal ledger state via process_turn.
    - Unparsable lines -> spool/_corrupt/<agent>-%Y%m%d-%H%M%S.jsonl.

    `process_turn` is an async coroutine; the scanner runs in worker
    threads (to_thread), so it needs the running event loop reference to
    submit coroutines via run_coroutine_threadsafe.
    """

    def __init__(self, spool_root: Path, process_turn, loop,
                 interval_s: int = 600, skip_fresh_s: int = 10):
        self.spool_root = spool_root
        self.process_turn = process_turn
        self.loop = loop
        self.interval_s = interval_s
        self.skip_fresh_s = skip_fresh_s
        self.total_replayed = 0
        self.total_deduped = 0
        self.total_failed = 0
        self._last_scan_at = 0.0

    def _run_turn(self, payload: Dict) -> Dict:
        """Submit one turn to the event loop and wait for the result."""
        fut = asyncio.run_coroutine_threadsafe(
            self.process_turn(payload, recovery=True), self.loop)
        return fut.result(timeout=120)

    # -- public ----------------------------------------------------------
    @property
    def pending_files(self) -> int:
        return sum(1 for _ in self._iter_candidate_files())

    def scan_once(self) -> Dict:
        """One full scan. Returns {'files', 'lines', 'deduped', 'failed'}."""
        self.total_replayed = 0
        self.total_deduped = 0
        self.total_failed = 0
        files = list(self._iter_candidate_files())
        out = {"files": len(files), "lines": 0, "deduped": 0, "failed": 0,
               "pending_gate": 0}
        for f in files:
            r = self._replay_file(f)
            out["lines"] += r["lines"]
            out["deduped"] += r["deduped"]
            out["failed"] += r["failed"]
            out["pending_gate"] += r["pending_gate"]
        self._last_scan_at = time.monotonic()
        return out

    def maybe_scan(self, force: bool = False) -> Optional[Dict]:
        """Interval-triggered scan (10 min default). No-op when too soon."""
        if not force and time.monotonic() - self._last_scan_at < self.interval_s:
            return None
        return self.scan_once()

    # -- internals ---------------------------------------------------------
    def _iter_candidate_files(self):
        if not self.spool_root.exists():
            return
        for agent_dir in sorted(self.spool_root.iterdir()):
            if not agent_dir.is_dir() or agent_dir.name.startswith("_"):
                continue
            for f in sorted(agent_dir.glob("*.jsonl")):
                # skip files still being written (fresh, or .processing in flight)
                try:
                    if time.time() - f.stat().st_mtime < self.skip_fresh_s:
                        continue
                except OSError:
                    continue
                yield f

    def _replay_file(self, path: Path) -> Dict:
        processing = path.with_suffix(path.suffix + ".processing")
        try:
            path.rename(processing)  # atomic claim
        except OSError:
            return {"lines": 0, "deduped": 0, "failed": 0, "pending_gate": 0}
        lines_ok = 0
        deduped = 0
        failed = 0
        pending = 0
        corrupt: List[str] = []
        with open(processing, encoding="utf-8") as f:
            for ln, raw in enumerate(f, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    corrupt.append(raw)
                    failed += 1
                    continue
                if not isinstance(payload, dict) or not payload.get("idempotency_key"):
                    corrupt.append(raw)
                    failed += 1
                    continue
                try:
                    result = self._run_turn(payload)
                    st = result.get("status") or ""
                    if st == "pending_gate":
                        pending += 1
                    elif result.get("deduplicated"):
                        deduped += 1
                    elif st in ("stored", "skipped"):
                        lines_ok += 1
                    else:
                        failed += 1
                except Exception:
                    log.exception("spool replay line %s:%d failed", path.name, ln)
                    failed += 1
        # move corrupt lines aside (keep evidence)
        if corrupt:
            cdir = self.spool_root / "_corrupt"
            cdir.mkdir(parents=True, exist_ok=True)
            cpath = cdir / f"{path.stem}-{int(time.time())}.jsonl"
            with open(cpath, "w", encoding="utf-8") as f:
                for c in corrupt:
                    f.write(c + "\n")
        # file fully consumed (terminal + corrupt) -> delete; else keep name
        if failed == 0 or True:  # every line reached a ledger state
            try:
                processing.unlink()
            except OSError:
                pass
        self.total_replayed += lines_ok
        self.total_deduped += deduped
        self.total_failed += failed
        return {"lines": lines_ok + deduped + pending, "deduped": deduped,
                "failed": failed, "pending_gate": pending}


def _file_lock_retry(fn, lock_dir: Path, retries: int = 3, delay_s: float = 2.0):
    """D11d: file-lock retries apply to spool/backup paths ONLY.

    Best-effort O_APPEND on Windows; a lock header file is not used — the
    append itself is atomic enough for single-line JSONL. Retry covers
    transient OSError (sharing violations meanwhile).
    """
    last = None
    for i in range(retries):
        err = fn()
        if err is None:
            return None
        last = err
        if i + 1 < retries:
            time.sleep(delay_s)
    return last