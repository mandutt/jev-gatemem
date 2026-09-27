"""Consistent snapshot of the LIVE Mnemosyne DB + integrity verification.

`VACUUM INTO` produces a transactionally consistent copy. Design gate:
experiments run against the snapshot; the live DB must be byte-identical
before and after (sha256 check).
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot_db(live_db: str | Path, out_path: str | Path) -> tuple[str, str]:
    """Create a consistent copy via VACUUM INTO. Returns (out_path, sha256_of_copy)."""
    live = Path(live_db)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    con = sqlite3.connect(f"file:{live}?mode=ro", uri=True)
    try:
        con.execute(f"VACUUM INTO '{out.as_posix()}'")
    finally:
        con.close()
    return str(out), sha256(out)


def verify_live_unchanged(live_db: str | Path, before_sha: str) -> bool:
    return sha256(live_db) == before_sha