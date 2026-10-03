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
import logging
import time
import uuid
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

STATUSES = ("received", "gated", "stored", "skipped", "pending_gate", "failed",
            "fail_open_quarantine", "rejudge_pending", "rejudge_running",
            "rejudge_kept", "rejudge_invalidated")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ingest_ledger (
  idem_key       TEXT PRIMARY KEY,
  turn_id        TEXT NOT NULL UNIQUE,
  payload_hash   TEXT NOT NULL,
  agent          TEXT NOT NULL,
  session_key    TEXT NOT NULL,
  turn_seq       INTEGER,
  status         TEXT NOT NULL CHECK (status IN
                   ('received','gated','stored','skipped','pending_gate','failed',
                    'fail_open_quarantine','rejudge_pending','rejudge_running',
                    'rejudge_kept','rejudge_invalidated')),
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

-- P2b: JEV 장애 구간 기록 (D7) — incident_id = start~end 구간
CREATE TABLE IF NOT EXISTS gate_outage (
  incident_id   TEXT PRIMARY KEY,
  started_at    TEXT NOT NULL,
  ended_at      TEXT,
  reason        TEXT NOT NULL,      -- http-402 / http-403 / no-key / kill ...
  failure_class TEXT NOT NULL,      -- billing / auth / transient / config ...
  count         INTEGER NOT NULL DEFAULT 0,
  status        TEXT NOT NULL DEFAULT 'open',  -- open | closed | rejudge_ready | rejudge_done
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL DEFAULT '',
  -- P3 (D7): 회복 판정 상태 — DB 영속 (재시작 안전, worker 메모리 금지)
  recovery_success_count INTEGER NOT NULL DEFAULT 0,
  recovery_confirmed_at  TEXT,
  rejudge_eligible_at    TEXT,
  rejudge_started_at     TEXT,
  rejudge_finished_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_outage_status ON gate_outage(status, started_at);

-- P3: 재판정 행 lease (restart-safe claim — SQLite가 유일한 source of truth)
CREATE TABLE IF NOT EXISTS rejudge_lease (
  memory_id    TEXT PRIMARY KEY,
  incident_id  TEXT NOT NULL,
  leased_at    TEXT NOT NULL,
  lease_until  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lease_until ON rejudge_lease(lease_until);
"""


def init_schema(conn) -> None:
    conn.executescript(_SCHEMA)
    _migrate_status_check(conn)
    _migrate_outage_p3(conn)
    conn.commit()


def _migrate_outage_p3(conn) -> None:
    """P3: 기존 gate_outage 테이블에 recovery/rejudge 컬럼 추가 (경량).

    P2b 이전 DB는 status='open'|'closed' 2종 + P3 컬럼 없음. ALTER ADD COLUMN
    (SQLite는 컬럼 추가만 지원 — DEFAULT 있으면 기존 행에 자동 채움).
    """
    cols = {r[1] for r in conn.execute(
        "PRAGMA table_info(gate_outage)").fetchall()}
    adds = {
        "updated_at": "TEXT NOT NULL DEFAULT ''",
        "recovery_success_count": "INTEGER NOT NULL DEFAULT 0",
        "recovery_confirmed_at": "TEXT",
        "rejudge_eligible_at": "TEXT",
        "rejudge_started_at": "TEXT",
        "rejudge_finished_at": "TEXT",
    }
    for name, ddl in adds.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE gate_outage ADD COLUMN {name} {ddl}")
    # 레거시 정정: ended_at이 찍혔는데 status='open'으로 남은 행 → closed
    # (P2a outage_close가 ended_at만 기록하고 status 업데이트를 놓친 경우)
    conn.execute(
        "UPDATE gate_outage SET status = 'closed', updated_at = ended_at"
        " WHERE status = 'open' AND ended_at IS NOT NULL AND ended_at != ''")
    conn.commit()
    log.info("gate_outage P3 columns migrated")


def _migrate_status_check(conn) -> None:
    """기존 ingest_ledger의 CHECK 제약이 구버전(6개)일 때 table 재생성으로 확장.

    CREATE TABLE IF NOT EXISTS는 기존 테이블 스키마를 바꾸지 않으므로,
    status CHECK가 새 상태(11개)를 허용하지 않는 레거시 DB는 마이그레이션 필요.
    Data는 보존 (same name + rename swap).
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='ingest_ledger'"
    ).fetchone()
    if not row or not row[0]:
        return
    sql = str(row[0])
    # 새 CHECK가 이미 포함되어 있으면 스킵
    if "fail_open_quarantine" in sql and "rejudge_kept" in sql:
        return
    conn.execute("ALTER TABLE ingest_ledger RENAME TO ingest_ledger_old")
    conn.executescript(_SCHEMA)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(ingest_ledger)").fetchall()]
    collist = ", ".join(cols)
    conn.execute(
        f"INSERT INTO ingest_ledger ({collist})"
        f" SELECT {collist} FROM ingest_ledger_old")
    conn.execute("DROP TABLE ingest_ledger_old")
    # 신규 테이블에도 인덱스 복구
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_ledger_status ON ingest_ledger(status, received_at);
        CREATE INDEX IF NOT EXISTS idx_ledger_updated ON ingest_ledger(updated_at);
    """)
    conn.commit()
    log.info("ingest_ledger CHECK migrated: 6 -> 11 statuses")


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


# ---- P2b: gate_outage (D7 — 장애 구간 기록) ----

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def outage_open(conn, *, reason: str, failure_class: str,
                incident_id: Optional[str] = None) -> str:
    """Open (or reuse) an incident. Returns incident_id.

    Same reason+class within 5 minutes reuses the open incident (연속 장애
    병합); otherwise a new incident is created.
    """
    if not incident_id:
        incident_id = f"inc-{uuid.uuid4().hex[:12]}"
    now = _now_iso()
    row = conn.execute(
        "SELECT incident_id FROM gate_outage WHERE status = 'open'"
        " AND reason = ? AND failure_class = ?"
        " AND started_at >= datetime('now', '-5 minutes')"
        " ORDER BY started_at DESC LIMIT 1", (reason, failure_class)
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE gate_outage SET ended_at = ?, count = count + 1"
            " WHERE incident_id = ?", (now, row["incident_id"]))
        conn.commit()
        return row["incident_id"]
    conn.execute(
        "INSERT INTO gate_outage (incident_id, started_at, ended_at, reason,"
        " failure_class, count, status, created_at) VALUES (?,?,?,?,?,1,'open',?)",
        (incident_id, now, now, reason, failure_class, now))
    conn.commit()
    return incident_id


def outage_close(conn, incident_id: str) -> None:
    conn.execute(
        "UPDATE gate_outage SET ended_at = ?, status = 'closed'"
        " WHERE incident_id = ? AND status = 'open'",
        (_now_iso(), incident_id))
    conn.commit()


def outage_open_incidents(conn) -> list[Dict]:
    rows = conn.execute(
        "SELECT * FROM gate_outage WHERE status = 'open' ORDER BY started_at"
    ).fetchall()
    return [dict(r) for r in rows]


def outage_count_by_class(conn) -> Dict[str, int]:
    rows = conn.execute(
        "SELECT failure_class, SUM(count) AS n FROM gate_outage"
        " GROUP BY failure_class").fetchall()
    return {r["failure_class"]: int(r["n"]) for r in rows}


def _parse_ts(s: str) -> float:
    """Parse ISO-8601 ('%Y-%m-%dT%H:%M:%S%z') -> epoch seconds (best-effort)."""
    if not s:
        return 0.0
    try:
        from datetime import datetime
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return 0.0


# ---- P3: 회복 감지 (D4, D7 — DB 영속, worker 메모리 금지) ----

def recovery_record_success(conn, incident_id: str, *, streak: int,
                            cooldown_min: int) -> bool:
    """장애 incident에 성공 streak 1회 기록. 임계 도달 시 rejudge_ready 전이.

    Returns True if the incident transitioned to rejudge_ready.
    """
    row = conn.execute(
        "SELECT recovery_success_count, status FROM gate_outage"
        " WHERE incident_id = ?", (incident_id,)
    ).fetchone()
    if not row or row["status"] != "open":
        return False
    n = int(row["recovery_success_count"] or 0) + 1
    now = _now_iso()
    confirmed = None
    eligible = None
    status = "open"
    ready = False
    if n >= streak:
        confirmed = now
        # 히스테리시스: confirmed_at + cooldown_min (UTC 비교)
        eligible = time.strftime(
            "%Y-%m-%dT%H:%M:%S%z",
            time.localtime(time.time() + cooldown_min * 60))
        status = "rejudge_ready"
        ready = True
    conn.execute(
        "UPDATE gate_outage SET recovery_success_count = ?,"
        " recovery_confirmed_at = COALESCE(?, recovery_confirmed_at),"
        " rejudge_eligible_at = COALESCE(?, rejudge_eligible_at),"
        " status = ?, updated_at = ? WHERE incident_id = ?",
        (n, confirmed, eligible, status, now, incident_id))
    conn.commit()
    return ready


def recovery_reset(conn, incident_id: str) -> None:
    """장애 재발 시 streak 리셋 (open 유지)."""
    conn.execute(
        "UPDATE gate_outage SET recovery_success_count = 0,"
        " recovery_confirmed_at = NULL, rejudge_eligible_at = NULL,"
        " status = 'open', updated_at = ? WHERE incident_id = ?",
        (_now_iso(), incident_id))
    conn.commit()


def recovery_ready_incidents(conn) -> list[Dict]:
    """rejudge_ready 상태 + eligible_at 도달한 incident 목록."""
    rows = conn.execute(
        "SELECT * FROM gate_outage WHERE status = 'rejudge_ready'"
        " ORDER BY started_at").fetchall()
    out = []
    now_ts = time.time()
    for r in rows:
        elig = _parse_ts(r["rejudge_eligible_at"] or "") if r["rejudge_eligible_at"] else 0
        if elig and now_ts >= elig:
            out.append(dict(r))
    return out


def outage_mark_rejudge_done(conn, incident_id: str) -> None:
    """재판정 완료 시 incident 종결 (rejudge_done + closed)."""
    now = _now_iso()
    conn.execute(
        "UPDATE gate_outage SET status = 'rejudge_done', ended_at = ?,"
        " rejudge_finished_at = ? WHERE incident_id = ?",
        (now, now, incident_id))
    conn.commit()


# ---- P3: 행 lease (restart-safe claim, D3) ----

def rejudge_claim(conn, memory_id: str, incident_id: str, lease_s: int) -> bool:
    """행 claim. 이미 유효 lease 있으면 False. 만료된 lease는 재claim."""
    now = _now_iso()
    until = time.strftime(
        "%Y-%m-%dT%H:%M:%S%z",
        time.localtime(time.time() + lease_s))
    row = conn.execute(
        "SELECT lease_until FROM rejudge_lease WHERE memory_id = ?",
        (memory_id,)).fetchone()
    if row:
        if row["lease_until"] and _parse_ts(row["lease_until"]) > time.time():
            return False  # 타 worker가 점유 중
        conn.execute(
            "UPDATE rejudge_lease SET incident_id=?, leased_at=?, lease_until=?"
            " WHERE memory_id=?", (incident_id, now, until, memory_id))
    else:
        conn.execute(
            "INSERT INTO rejudge_lease (memory_id, incident_id, leased_at, lease_until)"
            " VALUES (?,?,?,?)", (memory_id, incident_id, now, until))
    conn.commit()
    return True


def rejudge_release(conn, memory_id: str) -> None:
    conn.execute("DELETE FROM rejudge_lease WHERE memory_id = ?", (memory_id,))
    conn.commit()


def rejudge_leases(conn) -> list[Dict]:
    rows = conn.execute("SELECT * FROM rejudge_lease").fetchall()
    return [dict(r) for r in rows]