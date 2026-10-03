"""P3a 실통합 검증 — 실 JEV gate 호출 + 실 DB, 테스트 행 완전 원복.

시나리오 (P3 core invariant):
  1. open incident 생성 (core_state.db)
  2. mnemosyne.db에 fail_open 태그 테스트 행 2건 삽입 (P3A_TEST_ prefix)
  3. recovery streak 3회 기록 → rejudge_ready + eligible
  4. RejudgeEngine.run_batch(incident_id=...) → 실 JEV gate로 재판정
  5. verdict 기록 / incident 종결 확인
  6. 원복: 테스트 행 삭제, incident 삭제, lease/verdicts 정리

※ 실 JEV API 호출 비용: 2건 rejudge ≈ 소액 (STRICT mode).
※ 실 DB에 남는 것: 없음 (원복 보장).
"""
import json
import os
import sqlite3
import sys
import time
import winreg
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# TYPESAFE_API_KEY: HKCU env에서 명시적으로 확보 (상속 불확실성 제거)
try:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as _k:
        _key, _ = winreg.QueryValueEx(_k, "TYPESAFE_API_KEY")
    os.environ["TYPESAFE_API_KEY"] = _key
except Exception:
    print("WARN: TYPESAFE_API_KEY not resolved from HKCU")

from jev_mem_core import ledger
from jev_mem_core.config import Config
from jev_mem_core.recover import RejudgeEngine, quarantine_rows

STATE_DB = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "jev-mem" / "core_state.db"
MEM_DB = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "hermes" / "mnemosyne" / "data" / "mnemosyne.db"

TEST_INC = f"inc-p3a-live-{int(time.time())}"
PREFIX = "P3A_TEST_"

failures = []


def check(name, cond, detail=""):
    print(f"  [{'✅' if cond else '❌'}] {name} {detail}")
    if not cond:
        failures.append(name)


# ---- 0. 실 DB 열기 ----
conn = sqlite3.connect(STATE_DB)
conn.row_factory = sqlite3.Row
ledger.init_schema(conn)

mconn = sqlite3.connect(MEM_DB)
mconn.row_factory = sqlite3.Row

print(f"[0] 실 DB: {STATE_DB}")
print(f"    실 메모리 DB: {MEM_DB}")

# ---- 1. open incident ----
print("[1] incident 생성")
inc = ledger.outage_open(conn, reason="http-402", failure_class="billing",
                         incident_id=TEST_INC)
check("incident open", inc == TEST_INC)

# ---- 2. fail_open 테스트 행 삽입 ----
print("[2] quarantine 행 2건 (P3A_TEST_)")
now_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z")
test_rows = [
    (f"{PREFIX}mem-1", f"[USER] {PREFIX} 실통합검증 메모리 1 — 이 문장은 저장 테스트입니다.",
     json.dumps({"gate": "fail_open:http-402", "incident_id": TEST_INC}, ensure_ascii=False), now_iso),
    (f"{PREFIX}mem-2", f"[USER] {PREFIX} 실통합검증 메모리 2 — 이 문장도 저장 테스트입니다.",
     json.dumps({"gate": "fail_open:http-402", "incident_id": TEST_INC}, ensure_ascii=False), now_iso),
]
for r in test_rows:
    mconn.execute(
        "INSERT OR REPLACE INTO working_memory (id, content, metadata_json, timestamp)"
        " VALUES (?,?,?,?)", r)
mconn.commit()

rows = quarantine_rows(mconn, incident_id=TEST_INC)
check("quarantine 조회 2건", len(rows) == 2)
check("prefix 식별", all(r["id"].startswith(PREFIX) for r in rows))

# ---- 3. recovery streak 3회 — half-open/회복 감지 경로 ----
print("[3] recovery streak 3회 → rejudge_ready")
cfg = Config.load()
# 실제 데몬 설정과 동일한 streak을 쓰되, cooldown은 0으로 (테스트)
cfg.rejudge_cooldown_min = 0

class WriterAdapter:
    """실 데몬의 writer.submit과 동일한 인터페이스: Future를 반환 (.result())."""
    def __init__(self, conn):
        self.conn = conn
    def submit(self, fn, tag):
        class _R:
            def __init__(self, v):
                self._v = v
            def result(self):
                return self._v
        return _R(fn(self))
    def submit_sync(self, fn, tag):
        # submit()과 동일 — 원래부터 동기 실행이었으므로 두 인터페이스 모두 제공
        return self.submit(fn, tag)
    @property
    def state(self):
        return self.conn

class Ctx:
    def __init__(self, conn):
        self.writer = WriterAdapter(conn)
        self.cfg = cfg
        self.reader_conn = lambda: mconn
    class Breaker:
        is_open = False
        def on_success(self): pass
        def on_failure(self, e): pass
    breaker = Breaker()

ctx = Ctx(conn)
engine = RejudgeEngine(ctx, cfg=cfg)

r1 = engine.record_recovery_success(TEST_INC)
r2 = engine.record_recovery_success(TEST_INC)
check("1-2회: open 유지", r1 is False and r2 is False)
r3 = engine.record_recovery_success(TEST_INC)
check("3회: rejudge_ready", r3 is True)
ready = engine.ready_incidents()
check("ready 목록에 포함", any(i["incident_id"] == TEST_INC for i in ready))

# ---- 4. run_batch — 실 JEV gate 호출 ----
print("[4] run_batch (실 JEV STRICT gate 호출 2건)")
res = engine.run_batch(incident_id=TEST_INC, limit=2)
print(f"    결과: {json.dumps(res, ensure_ascii=False)}")
check("2건 처리", res["rejudged"] == 2, f"got {res['rejudged']}")
check("halt 없음", not res["halted"])

# verdict 기록 확인
vrows = conn.execute(
    "SELECT memory_id, verdict, reason, apply_status FROM rejudge_verdicts WHERE incident_id=?",
    (TEST_INC,)).fetchall()
check("verdict 2건 기록", len(vrows) == 2)
for v in vrows:
    print(f"    verdict: {v['memory_id'][:20]}... → {v['verdict']} ({v['reason']}) apply={v['apply_status']}")
check("apply_status=applied", all(v["apply_status"] == "applied" for v in vrows))

# ---- 4b. apply 검증 — 메모리 행 metadata ----
print("[4b] apply 반영 확인")
mrows = mconn.execute(
    "SELECT id, metadata_json FROM working_memory WHERE id LIKE ?",
    (f"{PREFIX}%",)).fetchall()
for m in mrows:
    meta = json.loads(m["metadata_json"])
    print(f"    {m['id'][:20]}... rejudged={meta.get('rejudged')} archived={meta.get('archived')} valid_until={bool(meta.get('valid_until'))}")
check("rejudged 마커 2건", len(mrows) == 2 and all(
    json.loads(m["metadata_json"]).get("rejudged") in ("keep", "skip")
    for m in mrows))

# ---- 5. incident 종결 ----
print("[5] incident 종결")
row = conn.execute("SELECT status FROM gate_outage WHERE incident_id=?", (TEST_INC,)).fetchone()
check("status=rejudge_done", row["status"] == "rejudge_done", f"got {row['status']}")

# ---- 6. 원복! ----
print("[6] 원복")
mconn.execute("DELETE FROM working_memory WHERE id LIKE ?", (f"{PREFIX}%",))
mconn.commit()
left = mconn.execute("SELECT COUNT(*) FROM working_memory WHERE id LIKE ?",
                     (f"{PREFIX}%",)).fetchone()[0]
check("테스트 행 삭제", left == 0)

conn.execute("DELETE FROM gate_outage WHERE incident_id=?", (TEST_INC,))
conn.execute("DELETE FROM rejudge_verdicts WHERE incident_id=?", (TEST_INC,))
conn.execute("DELETE FROM rejudge_lease WHERE incident_id=?", (TEST_INC,))
conn.commit()
left = conn.execute("SELECT COUNT(*) FROM gate_outage WHERE incident_id=?",
                    (TEST_INC,)).fetchone()[0]
check("incident 삭제", left == 0)

conn.close()
mconn.close()

print(f"\n=== P3a 실통합 검증: {'전부 통과' if not failures else f'실패 {len(failures)}건: {failures}'} ===")
sys.exit(1 if failures else 0)