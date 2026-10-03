"""P2b 단위 검증 — ledger 스키마/outage 함수 + pipeline quarantine 상태 전이.

로컬 임시 DB로 검증 (실 DB 건드리지 않음).
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from jev_mem_core import ledger

tmp = tempfile.mkdtemp()
db_path = Path(tmp) / "core_state.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# 1. 스키마 초기화 (신규 테이블 포함)
ledger.init_schema(conn)
tables = [r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
assert "ingest_ledger" in tables, f"ingest_ledger 없음: {tables}"
assert "gate_outage" in tables, f"gate_outage 없음: {tables}"
print(f"[1] 스키마 OK — tables: {[t for t in tables if t in ('ingest_ledger','gate_outage','core_meta')]}")

# 2. outage_open: 신규 생성 + 연속 병합
# SQLite datetime('now')는 UTC — 'now' 기준 5분 내 병합
inc1 = ledger.outage_open(conn, reason="http-402", failure_class="billing",
                          incident_id="inc-test-0001")
assert inc1 == "inc-test-0001"
inc2 = ledger.outage_open(conn, reason="http-402", failure_class="billing",
                          incident_id="inc-test-0002")
assert inc2 == "inc-test-0001", f"연속 장애 병합 실패: {inc2} != inc-test-0001"
print(f"[2] outage_open: 신규 생성 {inc1} + 연속 병합 {inc2} OK")

# 3. outage_close + open 목록
ledger.outage_close(conn, inc1)
opens = ledger.outage_open_incidents(conn)
assert len(opens) == 0, f"close 후에도 open: {opens}"
print("[3] outage_close + open 목록 OK")

# 4. STATUSES 확장 반영
assert "fail_open_quarantine" in ledger.STATUSES
assert "rejudge_kept" in ledger.STATUSES
print("[4] STATUSES 확장 OK:", [s for s in ledger.STATUSES if "rejudge" in s or "fail_open" in s])

# 5. status CHECK 제약 — fail_open_quarantine 허용
conn.execute(
    "INSERT INTO ingest_ledger (idem_key, turn_id, payload_hash, agent, session_key,"
    " status, received_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
    ("k1", "t1", "h1", "hermes", "s1", "fail_open_quarantine", "2026-10-03T10:00:00+09:00", "2026-10-03T10:00:00+09:00"))
conn.commit()
row = conn.execute("SELECT status FROM ingest_ledger WHERE idem_key='k1'").fetchone()
assert row["status"] == "fail_open_quarantine"
print("[5] CHECK 제약: fail_open_quarantine 허용 OK")

# 6. outage_count_by_class
c = ledger.outage_count_by_class(conn)
assert c.get("billing") == 2, f"billing count mismatch: {c}"
print(f"[6] outage_count_by_class OK: {c}")

# 7. rejudge_verdicts 테이블 (재판정 엔진)
from tools.jed_failopen_rejudge_v2 import VERDICT_TABLE
vconn = sqlite3.connect(db_path)
vconn.executescript(VERDICT_TABLE)
vt = [r[0] for r in vconn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name='rejudge_verdicts'").fetchall()]
assert vt, "rejudge_verdicts 테이블 생성 실패"
print("[7] rejudge_verdicts 테이블 OK")

print("\n=== P2b 단위 검증 전부 통과 ===")