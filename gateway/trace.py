"""J1 pipeline trace logger — bounded append-only file with hard size cap.

Ring buffer strategy (no background thread, no scheduler):
  - Appends are cheap (one open/append/close per line).
  - After each append, if the file exceeds the cap we truncate the leading
    half: read the tail, rewrite it, and continue. The file therefore stays
    between ~CAP/2 and ~CAP bytes at all times.
  - Single-writer assumption: only the Hermes memory provider process writes
    it. Concurrent Hermes processes each append atomically via O_APPEND
    (short lines, one write call), so interleaved lines are still bounded.
  - Failures are silent: tracing must never break the prefetch path.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

TRACE_CAP_BYTES = 512 * 1024         # hard ceiling (~512 KB)
_TRIM_HEAD_FRACTION = 0.5            # drop leading 50% when over cap
_LOCK = threading.Lock()


def _resolve_path() -> Path:
    env = os.environ.get("JEV_TRACE_PATH", "").strip()
    if env:
        p = Path(env)
    else:
        base = Path(os.environ.get("LOCALAPPDATA", ""))
        if base.is_dir():
            # 일별 로테이션: jev_trace_YYYYMMDD.log (2026-10-07, b-ai F#4)
            p = base / "hermes" / "logs" / f"jev_trace_{time.strftime('%Y%m%d')}.log"
        else:
            p = Path.home() / f"jev_trace_{time.strftime('%Y%m%d')}.log"
    return p


def trace(event: str, fields: dict) -> None:
    """Append one JSON-ish line: `2026-09-27T22:30:00.123|event|k=v k=v ...`"""
    try:
        parts = [f"{k}={v}" for k, v in fields.items()]
        line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')}.{int(time.time()*1000)%1000:03d}|{event}|{' '.join(parts)}\n"
        path = _resolve_path()
        with _LOCK:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(line)
            except OSError:
                return
            try:
                size = path.stat().st_size
            except OSError:
                return
            if size > TRACE_CAP_BYTES:
                _trim(path)
                # 로테이션 파일이 새로 생겼으면 그 기회에 오래된 것 정리 (최대 1회/일)
                _cleanup_old()
    except Exception:
        pass  # tracing must never raise


def _trim(path: Path) -> None:
    """Drop the leading ~half of the file to get back under the cap."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            keep_from = max(0, int(size * (1.0 - _TRIM_HEAD_FRACTION)))
            fh.seek(keep_from)
            # skip to next newline so we never split a line
            fh.readline()
            tail = fh.read()
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(tail)
        os.replace(tmp, path)
    except OSError:
        pass


_RETENTION_DAYS = 30  # 일별 로테이션 파일 보관 일수 (2026-10-07, b-ai F#4)


def _cleanup_old():
    """Remove rotated trace files older than retention days (best-effort)."""
    try:
        days = int(os.environ.get("JEV_TRACE_RETENTION_DAYS", str(_RETENTION_DAYS)))
    except ValueError:
        days = _RETENTION_DAYS
    if days <= 0:
        return
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "logs"
    if not base.is_dir():
        return
    cutoff = time.time() - days * 86400
    try:
        for p in base.glob("jev_trace_*.log"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
            except OSError:
                pass
    except OSError:
        pass