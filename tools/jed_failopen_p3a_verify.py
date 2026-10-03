"""P3a 단위 검증 — recovery 상태/lease + RejudgeEngine (스크래치 DB, JEV 미호출).

- ledger: recovery_record_success / recovery_reset / ready_incidents / lease
- RejudgeEngine: quarantine 조회, verdict 분류, halt 규칙 (mock으로)
실 DB·실 API 건드리지 않음.
"""
import json
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
ledger.init_schema(conn)

failures = []


def check(name, cond, detail=""):
    print(f"  [{'✅' if cond else '❌'}] {name} {detail}")
    if not cond:
        failures.append(name)


# ---- 1. recovery_record_success: streak 누적 → rejudge_ready 전이 ----
print("[1] recovery_record_success")
inc = ledger.outage_open(conn, reason="http-402", failure_class="billing",
                         incident_id="inc-p3a-0001")
r1 = ledger.recovery_record_success(conn, inc, streak=3, cooldown_min=0)
check("1회: 아직 open", r1 is False)
r2 = ledger.recovery_record_success(conn, inc, streak=3, cooldown_min=0)
check("2회: 아직 open", r2 is False)
r3 = ledger.recovery_record_success(conn, inc, streak=3, cooldown_min=0)
check("3회: rejudge_ready 전이", r3 is True)
row = conn.execute("SELECT * FROM gate_outage WHERE incident_id=?", (inc,)).fetchone()
check("streak=3 기록", int(row["recovery_success_count"]) == 3)
check("confirmed_at 기록", bool(row["recovery_confirmed_at"]))
check("status=rejudge_ready", row["status"] == "rejudge_ready")

# ---- 2. recovery_reset: 장애 재발 → streak 리셋 ----
print("[2] recovery_reset")
ledger.recovery_reset(conn, inc)
row = conn.execute("SELECT * FROM gate_outage WHERE incident_id=?", (inc,)).fetchone()
check("streak=0 리셋", int(row["recovery_success_count"]) == 0)
check("status=open 복귀", row["status"] == "open")

# ---- 3. cooldown: eligible_at 미도달 시 ready 목록 제외 ----
print("[3] cooldown gate")
# (리셋 후 다시 streak 3 달성 — 리셋 상태에서 시작)
ledger.recovery_record_success(conn, inc, streak=3, cooldown_min=10)
ledger.recovery_record_success(conn, inc, streak=3, cooldown_min=10)
ledger.recovery_record_success(conn, inc, streak=3, cooldown_min=10)
ready = ledger.recovery_ready_incidents(conn)
check("cooldown 10분: ready 아님", len(ready) == 0)
row = conn.execute("SELECT * FROM gate_outage WHERE incident_id=?", (inc,)).fetchone()
check("status=rejudge_ready (전이됨)", row["status"] == "rejudge_ready")
check("eligible_at 미래", bool(row["rejudge_eligible_at"]) and
      ledger._parse_ts(row["rejudge_eligible_at"]) > __import__("time").time())

# ---- 4. lease: claim → 유효 lease 재claim 거부 → 만료 후 재claim ----
print("[4] rejudge_claim/release")
ok1 = ledger.rejudge_claim(conn, "mem-001", inc, lease_s=120)
check("신규 claim", ok1 is True)
ok2 = ledger.rejudge_claim(conn, "mem-001", inc, lease_s=120)
check("유효 lease 재claim 거부", ok2 is False)
ledger.rejudge_release(conn, "mem-001")
ok3 = ledger.rejudge_claim(conn, "mem-001", inc, lease_s=120)
check("release 후 재claim", ok3 is True)
leases = ledger.rejudge_leases(conn)
check("lease 1건", len(leases) == 1)

# ---- 5. outage_mark_rejudge_done ----
print("[5] incident 종결")
ledger.outage_mark_rejudge_done(conn, inc)
row = conn.execute("SELECT * FROM gate_outage WHERE incident_id=?", (inc,)).fetchone()
check("status=rejudge_done", row["status"] == "rejudge_done")
check("ended_at 기록", bool(row["ended_at"]))

# ---- 6. RejudgeEngine verdict 분류 + quarantine 조회 (mock) ----
print("[6] RejudgeEngine 기본 로직")
from jev_mem_core.recover import RejudgeEngine, _classify_verdict, quarantine_rows, NORMAL_REASONS
check("NORMAL_REASONS 존재", len(NORMAL_REASONS) >= 7)
# verdict 분류: 정상 KEEP -> keep / 비정상 KEEP -> skip / SKIP -> skip
c1 = _classify_verdict({"keep": True, "reason": "store"})
c2 = _classify_verdict({"keep": True, "reason": "http-402"})
c3 = _classify_verdict({"keep": False, "reason": "no-store"})
check("정상 KEEP->keep", c1 == "keep", f"got {c1}")
check("비정상 KEEP->skip", c2 == "skip", f"got {c2}")
check("SKIP->skip", c3 == "skip", f"got {c3}")

# quarantine_rows: mnemosyne DB mock
mdb = Path(tmp) / "mnemosyne.db"
mconn = sqlite3.connect(mdb)
mconn.row_factory = sqlite3.Row
mconn.execute("""CREATE TABLE working_memory (
  id TEXT PRIMARY KEY, content TEXT, metadata_json TEXT, timestamp TEXT)""")
mconn.execute(
    "INSERT INTO working_memory VALUES (?,?,?,?)",
    ("m1", "[USER] 뭔가 저장", json.dumps({"gate": "fail_open:http-402", "incident_id": inc}),
     "2026-10-03T10:00:00+09:00"))
mconn.execute(
    "INSERT INTO working_memory VALUES (?,?,?,?)",
    ("m2", "저장 안 됨", json.dumps({"gate": "fail_open:http-403", "incident_id": inc}),
     "2026-10-03T10:01:00+09:00"))
mconn.commit()
rows = quarantine_rows(mconn, incident_id=inc)
check("quarantine 조회 2건", len(rows) == 2)
check("fail_open 파싱", rows[0]["fail_open"] == "http-402")
mconn.close()
conn.close()

print(f"\n=== P3a 단위 검증: {'전부 통과' if not failures else f'실패 {len(failures)}건: {failures}'} ===")
sys.exit(1 if failures else 0)