"""P3a 회귀 검증 — 이벤트 루프 스레드에서 submit 경로가 InvalidStateError를
내지 않는지 (2026-10-03 라이브 버그).

실데몬 패턴 재현:
  - SingleWriter 기동 (실 sqlite core_state.db 스키마)
  - async 함수 안에서:
      (a) engine.ready_incidents()      ← 직접 호출 (루프 스레드)
      (b) await asyncio.to_thread(engine.open_incidents)
      (c) await asyncio.to_thread(engine.record_recovery_success, inc)
      (d) await writer.submit(...)      ← async 경로 회귀
  - 이전 버그: submit()이 wrap_future 반환 → .result() → InvalidStateError
  - 수정 후: submit_sync() 경로는 raw Future라 어느 스레드든 동작.

또한 asyncio Future vs concurrent Future의 .result() 시맨틱 차이를 명시 검증.
JEV 호출 없음 (ledger 전용).
"""
import asyncio
import sqlite3
import sys
import tempfile
from concurrent.futures import Future as CFuture
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from jev_mem_core import ledger
from jev_mem_core.writer import SingleWriter, WriterContext

failures = []


def check(name, cond, detail=""):
    print(f"  [{'✅' if cond else '❌'}] {name} {detail}")
    if not cond:
        failures.append(name)


tmp = Path(tempfile.mkdtemp())
state_db = tmp / "core_state.db"

# 메인 스레드 conn: 스키마 초기화 + 직접 검사용 (sqlite check_same_thread 준수)
wconn = sqlite3.connect(state_db)
wconn.row_factory = sqlite3.Row
ledger.init_schema(wconn)
inc = ledger.outage_open(wconn, reason="http-402", failure_class="billing",
                        incident_id="inc-syncpath-test")


def factory():
    conn = sqlite3.connect(state_db)
    conn.row_factory = sqlite3.Row
    return WriterContext(beam=None, state=conn)


class Cfg:
    rejudge_streak = 3
    rejudge_cooldown_min = 30
    rejudge_lease_s = 120
    jev_model = "jev-latest"


class Breaker:
    is_open = False
    def on_success(self): pass
    def on_failure(self, e): pass


writer = SingleWriter(factory, max_depth=100)
writer.start(timeout=30)


class Ctx:
    cfg = Cfg()
    breaker = Breaker()
    writer = writer


from jev_mem_core.recover import RejudgeEngine  # noqa: E402

engine = RejudgeEngine(Ctx())


async def main():
    # ---- 0. 시맨틱 대조: pending asyncio Future .result()는 InvalidStateError ----
    print("[0] Future 시맨틱 대조")
    loop = asyncio.get_running_loop()
    afut = loop.create_future()
    try:
        afut.result()
        check("asyncio pending .result() raises", False, "no exception!")
    except asyncio.InvalidStateError:
        check("asyncio pending .result() raises InvalidStateError", True)
    cfut = CFuture()
    cfut.set_result(42)
    check("concurrent done .result() = 42", cfut.result() == 42)

    # ---- 1. 루프 스레드 직접 호출 (구버전에서 즉사했던 경로) ----
    print("[1] 루프 스레드에서 engine.ready_incidents() 직접 호출")
    try:
        r = engine.ready_incidents()
        check("ready_incidents 직접 호출 예외 없음", isinstance(r, list),
              f"got {type(r).__name__}")
    except Exception as e:
        check("ready_incidents 직접 호출 예외 없음", False, f"{type(e).__name__}: {e}")

    # ---- 2. to_thread 경로 (데몬 op_loop 실제 패턴) ----
    print("[2] to_thread: open_incidents / recovery 성공 streak")
    try:
        opens = await asyncio.to_thread(engine.open_incidents)
        check("open_incidents to_thread", any(i["incident_id"] == inc for i in opens),
              f"n={len(opens)}")
    except Exception as e:
        check("open_incidents to_thread", False, f"{type(e).__name__}: {e}")

    try:
        r1 = await asyncio.to_thread(engine.record_recovery_success, inc)
        r2 = await asyncio.to_thread(engine.record_recovery_success, inc)
        r3 = await asyncio.to_thread(engine.record_recovery_success, inc)
        check("streak 3회 → ready", (r1, r2, r3) == (False, False, True),
              f"got {(r1, r2, r3)}")
    except Exception as e:
        check("streak 3회 → ready", False, f"{type(e).__name__}: {e}")

    # ---- 3. async submit 경로 회귀 (await writer.submit) ----
    print("[3] async submit 경로 회귀")
    try:
        v = await writer.submit(lambda w: "ok-async", "async_check")
        check("await writer.submit 동작", v == "ok-async")
    except Exception as e:
        check("await writer.submit 동작", False, f"{type(e).__name__}: {e}")

    # ---- 4. 회복된 ready 목록에 포함 ----
    print("[4] ready 목록 확인")
    ready = await asyncio.to_thread(engine.ready_incidents)
    row = wconn.execute("SELECT status, recovery_success_count FROM gate_outage"
                        " WHERE incident_id=?", (inc,)).fetchone()
    # cooldown 30분이라 eligible 미도달 → ready 목록에는 없어야 정상 (전이만 확인)
    check("status=rejudge_ready 전이", row["status"] == "rejudge_ready",
          f"got {row['status']}")
    check("streak=3 기록", int(row["recovery_success_count"]) == 3)


try:
    asyncio.run(main())
finally:
    writer.stop(timeout=10)
    try:
        wconn.close()
    except Exception:
        pass

print(f"\n=== P3a sync-path 회귀: {'전부 통과' if not failures else f'실패 {len(failures)}건: {failures}'} ===")
sys.exit(1 if failures else 0)
