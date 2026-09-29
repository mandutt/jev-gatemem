"""Ingest ledger (core_state.db) — idempotency + crash recovery (B §6, v1.1 D12).

SingleWriter owns this DB. Ledger rows track turn lifecycle:
  received -> gated -> stored | skipped | pending_gate | failed

Crash window (v1.1 D12): a turn may be committed to mnemosyne before the
ledger row is marked terminal. On requeue we first check the in-memory
idem marker inside metadata_json of working_memory rows; if found, the row
is marked stored instead of re-committing.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any, Dict, Optional

STATUSES = ("received", "gated", "stored", "skipped", "pending_gate", "failed")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ingest_ledger (
  idem_key       TEXT PRIMARY KEY,
  turn_id        TEXT NOT NULL UNIQUE,
  payload_hash   TEXT NOT NULL,
  agent          TEXT NOT NULL,
  session_key    TEXT NOT NULL,
  turn_seq       INTEGER,
  status         TEXT NOT NULL CHECK (status IN
                   ('received','gated','stored','skipped','pending_gate','failed')),
  decisions_json TEXT,
  memory_ids_json TEXT,
  payload_json   TEXT,            -- origin text; NULL once terminal
  attempts       INTEGER NOT NULL DEFAULT 0,
  last_error     TEXT,
  received_at    TEXT NOT NULL,
  updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_status ON ingest_ledger(status, received_at);
CREATE INDEX IF NOT EXISTS idx_ledger_updated ON ingest_ledger(updated_at);

CREATE TABLE IF NOT EXISTS core_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def init_schema(conn) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def new_turn_id() -> str:
    return "t_" + uuid.uuid4().hex[:18]


def make_idem_key(agent: str, session_id: str, turn_seq: Optional[int], user: str, assistant: str) -> str:
    """Server-side deriving is NOT used (v1.0 D5: adapter always sends a key).

    This helper exists for adapters that do not track turn_seq: it derives a
    UUID-based key so the spool/replay path stays idempotent.
    """
    if turn_seq is not None:
        return f"{agent}:{session_id}:{turn_seq}"
    return f"{agent}:{session_id}:{uuid.uuid4().hex[:12]}"


def payload_hash(agent: str, session_id: str, turn_seq: Optional[int], user: str, assistant: str) -> str:
    norm = lambda s: "\n".join((s or "").splitlines()).strip()
    h = hashlib.sha256()
    for part in (agent, session_id, str(turn_seq or ""), norm(user), norm(assistant)):
        h.update((part or "").encode("utf-8", errors="replace"))
        h.update(b"\0")
    return h.hexdigest()[:40]


def ledger_receive(conn, *, idem_key: str, payload: Dict, payload_hash_: str) -> Dict:
    """Insert or re-read a received row. Returns dict:
    {status: 'new'|'duplicate'|'conflict', turn_id, row: dict|None}
    """
    row = conn.execute(
        "SELECT * FROM ingest_ledger WHERE idem_key = ?", (idem_key,)
    ).fetchone()
    if row is None:
        turn_id = new_turn_id()
        now = _now()
        conn.execute(
            """INSERT INTO ingest_ledger
               (idem_key, turn_id, payload_hash, agent, session_key, turn_seq,
                status, payload_json, attempts, received_at, updated_at)
               VALUES (?,?,?,?,?,?, 'received', ?, 0, ?, ?)""",
            (idem_key, turn_id, payload_hash_, payload.get("agent", ""),
             payload.get("session_key", ""), payload.get("turn_seq"),
             json.dumps(payload, ensure_ascii=False), now, now),
        )
        conn.commit()
        return {"status": "new", "turn_id": turn_id}
    # duplicate / conflict
    if row["payload_hash"] != payload_hash_:
        return {"status": "conflict", "turn_id": row["turn_id"], "row": _row_dict(row)}
    return {"status": "duplicate", "turn_id": row["turn_id"], "row": _row_dict(row)}


def _row_dict(row) -> Dict:
    d = dict(row)
    for k in ("decisions_json", "memory_ids_json", "payload_json"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except Exception:
                pass
    return d


def ledger_get(conn, idem_key: str) -> Optional[Dict]:
    row = conn.execute(
        "SELECT * FROM ingest_ledger WHERE idem_key = ?", (idem_key,)
    ).fetchone()
    return _row_dict(row) if row else None


def ledger_mark(conn, idem_key: str, status: str, *, decisions=None,
                memory_ids=None, last_error=None, clear_payload=False) -> None:
    assert status in STATUSES
    row = conn.execute("SELECT 1 FROM ingest_ledger WHERE idem_key=?", (idem_key,)).fetchone()
    if row is None:
        return
    sets = ["status = ?", "updated_at = ?", "attempts = attempts + 1"]
    args: list = [status, _now()]
    if decisions is not None:
        sets.append("decisions_json = ?")
        args.append(json.dumps(decisions, ensure_ascii=False))
    if memory_ids is not None:
        sets.append("memory_ids_json = ?")
        args.append(json.dumps(memory_ids))
    if last_error is not None:
        sets.append("last_error = ?")
        args.append(str(last_error)[:300])
    if clear_payload:
        sets.append("payload_json = NULL")
    args.append(idem_key)
    conn.execute(f"UPDATE ingest_ledger SET {', '.join(sets)} WHERE idem_key = ?", args)
    conn.commit()


def recover_incomplete(conn) -> list[Dict]:
    """Rows in received/gated/pending_gate return for requeue (B §6.4).

    Returns list of {idem_key, payload, turn_id, status, attempts}.
    """
    rows = conn.execute(
        "SELECT * FROM ingest_ledger WHERE status IN ('received','gated','pending_gate')"
        " ORDER BY received_at"
    ).fetchall()
    out = []
    for r in rows:
        payload = r["payload_json"]
        if payload:
            try:
                payload = json.loads(payload)
            except Exception:
                payload = None
        out.append({
            "idem_key": r["idem_key"], "payload": payload, "turn_id": r["turn_id"],
            "status": r["status"], "attempts": r["attempts"],
        })
    return out


def pending_gate_rows(conn, limit: int = 20) -> list[Dict]:
    """Oldest pending_gate rows with payload (B §8.2 re-judge loop)."""
    rows = conn.execute(
        "SELECT * FROM ingest_ledger WHERE status = 'pending_gate'"
        " ORDER BY received_at LIMIT ?", (limit,)
    ).fetchall()
    out = []
    for r in rows:
        payload = r["payload_json"]
        if payload:
            try:
                payload = json.loads(payload)
            except Exception:
                payload = None
        out.append({
            "idem_key": r["idem_key"], "payload": payload, "turn_id": r["turn_id"],
            "created_at": _parse_ts(r["received_at"]),
        })
    return out


def pending_gate_count(conn) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM ingest_ledger WHERE status = 'pending_gate'"
    ).fetchone()
    return int(row["n"]) if row else 0


def _parse_ts(s: str) -> float:
    """Parse ISO-8601 ('%Y-%m-%dT%H:%M:%S%z') -> epoch seconds (best-effort)."""
    if not s:
        return 0.0
    try:
        from datetime import datetime
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return 0.0