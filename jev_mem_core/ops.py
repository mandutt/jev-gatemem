"""DB operational jobs — checkpoint & backup (B §13).

- checkpoint: idle 5 min -> wal_checkpoint(PASSIVE); shutdown -> TRUNCATE.
- backup: daily VACUUM INTO backups/mnemosyne-YYYYMMDD.db, keep last 7,
  on a SEPARATE read-only connection (never through the writer queue),
  file-lock retries 2s x3 (D11d: spool/backup paths only).
- core_state.db is NOT backed up (ephemeral ledger/spool state).
"""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("jev_mem.ops")


def checkpoint_passive(db_path: Path, busy_ms: int = 5000) -> dict:
    """wal_checkpoint(PASSIVE) on a short-lived direct connection.

    Returns {'ok': bool, 'wal_pages': int, 'detail': str}.
    """
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=rw", uri=True,
                               timeout=busy_ms / 1000)
        try:
            conn.execute(f"PRAGMA busy_timeout={busy_ms}")
            row = conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
            # row: (busy, log_frames, checkpointed_frames)
            ok = row and row[0] == 0
            return {"ok": bool(ok), "wal_pages": row[1] if row else -1,
                    "detail": str(row)}
        finally:
            conn.close()
    except sqlite3.Error as e:
        return {"ok": False, "wal_pages": -1, "detail": f"sqlite error: {e}"}


def checkpoint_truncate(db_path: Path, busy_ms: int = 5000) -> dict:
    """wal_checkpoint(TRUNCATE) — used at shutdown (B §13)."""
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=rw", uri=True,
                               timeout=busy_ms / 1000)
        try:
            conn.execute(f"PRAGMA busy_timeout={busy_ms}")
            row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            return {"ok": bool(row and row[0] == 0), "detail": str(row)}
        finally:
            conn.close()
    except sqlite3.Error as e:
        return {"ok": False, "detail": f"sqlite error: {e}"}


def backup_vacuum_into(db_path: Path, backups_dir: Path, keep: int = 7,
                       lock_retries: int = 3) -> Optional[Path]:
    """VACUUM INTO backups/mnemosyne-YYYYMMDD.db (B §13).

    Separate read-only connection; never through the writer queue.
    Lock retries 2s x3 (D11d). Keeps the latest `keep` backups.
    Returns the backup path, or None on failure.
    """
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    target = backups_dir / f"mnemosyne-{stamp}.db"
    if target.exists():
        log.info("backup %s already exists today — skipping", target.name)
        return target

    ro_conn = None
    try:
        for attempt in range(lock_retries):
            try:
                ro_conn = sqlite3.connect(
                    f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=5)
                break
            except sqlite3.Error as e:
                if attempt + 1 == lock_retries:
                    log.error("backup: RO open failed after %d retries: %s",
                              lock_retries, e)
                    return None
                time.sleep(2.0)
        if ro_conn is None:
            return None
        # VACUUM INTO on the RO connection — SQLite requires no other
        # in-progress write txn; WAL readers are fine.
        ro_conn.execute(f"PRAGMA busy_timeout=5000")
        tmp = target.with_suffix(".tmp")
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        # VACUUM INTO 'path' — single-quote escaping for path safety
        quoted = tmp.as_posix().replace("'", "''")
        ro_conn.execute(f"VACUUM INTO '{quoted}'")
        tmp.replace(target)
    except sqlite3.Error as e:
        log.error("backup failed: %s", e)
        return None
    finally:
        if ro_conn is not None:
            try:
                ro_conn.close()
            except Exception:
                pass

    _prune_old(backups_dir, keep)
    log.info("backup written: %s", target)
    return target


def _prune_old(backups_dir: Path, keep: int) -> None:
    try:
        files = sorted(backups_dir.glob("mnemosyne-*.db"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for f in files[keep:]:
            try:
                f.unlink()
                log.info("pruned old backup %s", f.name)
            except OSError:
                pass
    except OSError:
        pass