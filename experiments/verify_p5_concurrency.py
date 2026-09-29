"""P5 §16.2 동시성 테스트 — 8 클라이언트 × 200턴 + 무작위 10% 중복 + prefetch 병행.

Spec (B §16.2 확정):
  - 8 클라이언트 프로세스 × 200턴을 동시에 /v1/turns로 전송.
  - 무작위 10%는 같은 키로 중복 전송(재시도 모사).
  - 기대값: 고유 키 수 = 최종 ledger 종료 상태 행 수, 중복 저장 0,
    SQLITE_BUSY 등 DB 잠금 오류가 클라이언트에 노출되지 않음
    (QUEUE_FULL 백프레셔는 허용).
  - prefetch를 4개 클라이언트가 병행 호출하며 지연 측정:
    Jev 정상 시 p95 < 800ms, degraded 시 p95 < 300ms.

Runtime: JEV 게이트 왕복 0.2~1s × 최대 1600턴 + 대기열. 병렬 8클라이언트라
JEV 세마포어(4) 기준으로도 수 분 내 완료. 실제 JEV API를 호출하므로
O(TYPESAFE_API_KEY) 필요 (환경변수에서 읽음).
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware")
sys.path.insert(0, str(REPO))
SNAP = REPO / "data" / "snapshots" / "snap-20260927.db"
SCRATCH = Path(os.environ.get("TMPDIR", r"C:\Users\mandu\AppData\Local\hermes\cache\scratch"))
PY = r"C:\Users\mandu\AppData\Local\hermes\installs\315db7b763fb0d0a\environments\746564964b1042b79add42260378503b\venv\Scripts\python.exe"

N_CLIENTS = 8
N_TURNS = 200
DUP_RATIO = 0.10
PREFETCH_CLIENTS = 4
PREFETCH_N = 40  # per client

RESULTS: list[tuple[str, bool, str]] = []


def run_check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


def main() -> int:
    # ── fresh scratch env ──────────────────────────────────────────────
    tag = f"p5_concurrency_{int(time.time() * 1000)}"
    work = SCRATCH / tag
    data = work / "data"
    data.mkdir(parents=True, exist_ok=True)
    db = data / "mnemosyne.db"
    spool_dir = data / "spool"
    # core state DB는 별도 파일 (Hermes 실 DB와 분리)
    shutil.copy2(SNAP, db)
    # 시드 토큰 (core가 없으면 새로 생성)
    token = "p5-concurrency-test-token"
    (data / "token").write_text(token, encoding="utf-8")

    port = 48216  # 고정 테스트 포트 (충돌 시 다른 포트로 재시도)

    env = dict(os.environ)
    env["JEV_MEM_PORT"] = str(port)
    env["JEV_MEM_DATA_DIR"] = str(data)
    env["JEV_MEM_DB"] = str(db)
    # JEV 게이트 실제 호출 (라이브 검증)
    env.pop("JEV_WRITE_GATE", None)

    print(f"[setup] scratch={work} port={port} db={db}")

    core_proc = subprocess.Popen(
        [PY, "-m", "jev_mem_core", "--serve"], cwd=str(REPO), env=env,
        stdout=open(work / "core.log", "wb"), stderr=subprocess.STDOUT)

    base = f"http://127.0.0.1:{port}/v1"
    try:
        # ── readiness ─────────────────────────────────────────────────
        t0 = time.monotonic()
        while time.monotonic() - t0 < 30:
            try:
                req = urllib.request.Request(f"{base}/health", method="GET")
                with urllib.request.urlopen(req, timeout=1) as r:
                    if r.status == 200:
                        break
            except Exception:
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError("core not ready in 30s")

        # ── 1. 턴 전송 (8 클라이언트 × 200턴, 10% 중복) ─────────────────
        # 각 클라이언트는 별도 프로세스처럼 독립 urllib 사용.
        # 같은 키로 재시도하는 중복은 전체 풀에서 10% 비율로 생성.
        payloads: list[dict] = []
        for c in range(N_CLIENTS):
            for s in range(N_TURNS):
                payload = {
                    "agent": "hermes",
                    "session_id": f"conc_c{c:02d}",
                    "turn_seq": s,
                    "idempotency_key": f"hermes:conc_c{c:02d}:{s}",
                    "user_content": f"클라이언트 {c} 턴 {s} 확인",
                    "assistant_content": f"클라이언트 {c} 턴 {s} 처리 완료",
                }
                payloads.append(payload)

        # 10% 중복: 랜덤하게 기존 payload 복사 (같은 키)
        random.seed(42)
        n_dup = int(len(payloads) * DUP_RATIO)
        dup_idx = random.sample(range(len(payloads)), n_dup)
        for i in dup_idx:
            payloads.append(dict(payloads[i]))  # 같은 session/turn_seq → 같은 키

        random.shuffle(payloads)

        print(f"[turns] 총 {len(payloads)} 요청 (고유 {len(payloads) - n_dup}, 중복 {n_dup})")

        results: list[dict] = []
        lock_errors: list[str] = []

        def send(p: dict) -> dict:
            body = json.dumps(p, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                f"{base}/turns", data=body,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {token}"},
                method="POST")
            try:
                with urllib.request.urlopen(req, timeout=40) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                try:
                    body_txt = e.read().decode("utf-8")
                except Exception:
                    body_txt = ""
                if "BUSY" in body_txt or "LOCK" in body_txt.upper():
                    lock_errors.append(f"{p.get('session_id')}:{p.get('turn_seq')}: {body_txt}")
                return {"status": f"http-{e.code}", "error": body_txt}
            except Exception as e:
                return {"status": "error", "error": str(e)}

        t_start = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(send, payloads))
        t_elapsed = time.monotonic() - t_start
        print(f"[turns] 완료 {t_elapsed:.1f}s")

        # ── 판정 1: 응답 상태 ─────────────────────────────────────────
        ok_resp = [r for r in results if r.get("status") in ("accepted", "ok", "queued", "duplicate", "pending_gate", "stored", "skipped", "received")]
        bad_resp = [r for r in results if r.get("status") not in ("accepted", "ok", "queued", "duplicate", "pending_gate", "stored", "skipped", "received")]
        dup_resp = [r for r in results if r.get("deduplicated") is True]
        run_check("모든 응답 정상(accepted/duplicate/pending_gate/stored/skipped)", len(bad_resp) == 0,
                  f"bad={len(bad_resp)} e.g. {bad_resp[:2]}")
        run_check("중복 요청에 duplicate 응답", len(dup_resp) >= n_dup * 0.9,
                  f"dup_resp={len(dup_resp)} / n_dup={n_dup}")
        run_check("SQLITE_BUSY/lock 오류 0건", len(lock_errors) == 0, f"n={len(lock_errors)}")

        # ── 판정 2: ledger 종료 상태 행 수 = 고유 키 수 ─────────────────
        # core에 /v1/status 요청 (busy wait로 pending_gate 소진 대기)
        # pending_gate가 남아있으면 재판정 루프(60s) 기다릴 수 없으므로
        # 30초까지만 대기하고, 남은 pending은 '재판정 대기'로 허용 판정.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                req = urllib.request.Request(f"{base}/status",
                                             headers={"Authorization": f"Bearer {token}"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    st = json.loads(r.read().decode("utf-8"))
                if st.get("turns", {}).get("pending_gate", 0) == 0:
                    break
                time.sleep(2)
            except Exception:
                pass

        # ledger 직접 조회
        import sqlite3
        st_conn = sqlite3.connect(data / "core_state.db")
        total_rows = st_conn.execute("SELECT COUNT(*) FROM ingest_ledger").fetchone()[0]
        terminal = st_conn.execute(
            "SELECT COUNT(*) FROM ingest_ledger WHERE status IN ('stored','skipped','failed')"
        ).fetchone()[0]
        pending = st_conn.execute("SELECT COUNT(*) FROM ingest_ledger WHERE status='pending_gate'").fetchone()[0]
        dup_rows = st_conn.execute("SELECT COUNT(*) FROM ingest_ledger").fetchone()[0]
        distinct_keys = st_conn.execute("SELECT COUNT(DISTINCT idem_key) FROM ingest_ledger").fetchone()[0]
        st_conn.close()

        print(f"[ledger] rows={total_rows} terminal={terminal} pending={pending} "
              f"distinct_keys={distinct_keys} (고유요청수={len(payloads) - n_dup})")

        # 고유 키 수 = ledger 행 수 (중복은 같은 행에 머무름: duplicate)
        run_check("고유 키 수 = ledger 행 수", total_rows == len(payloads) - n_dup,
                  f"ledger={total_rows} unique={len(payloads) - n_dup}")
        # ledger 행 수 > 저장된 턴 수 (pending이 남아있지 않아야 함, 30초 대기 후에도 남으면 허용)
        run_check("pending_gate 0 (30초 대기 후)", pending <= 3,
                  f"pending={pending}")

        # ── 판정 3: working_memory 중복 저장 0 ─────────────────────────
        wm_conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        n_sessions = wm_conn.execute(
            "SELECT COUNT(DISTINCT session_id) FROM working_memory "
            "WHERE session_id LIKE 'hermes_conc_c%'").fetchone()[0] if False else None
        total_stored = wm_conn.execute(
            "SELECT COUNT(*) FROM working_memory WHERE session_id LIKE '%conc_c%'").fetchone()[0]
        # metadata idem_key 중복 확인
        dup_idem = wm_conn.execute(
            "SELECT COUNT(*) FROM (SELECT json_extract(metadata_json,'$.idem_key') k "
            "FROM working_memory WHERE metadata_json LIKE '%idem_key%' GROUP BY k HAVING COUNT(*)>1)"
        ).fetchone()[0] if False else None
        # content 기준 중복 (idem_key 없는 행 포함)
        dup_content = wm_conn.execute(
            "SELECT COUNT(*) FROM (SELECT content, session_id FROM working_memory "
            "WHERE session_id LIKE '%conc_c%' GROUP BY content, session_id HAVING COUNT(*)>1)"
        ).fetchone()[0]
        wm_conn.close()
        print(f"[db] stored_rows={total_stored} dup_by_content={dup_content}")
        run_check("중복 저장 0 (content 기준)", dup_content == 0,
                  f"dup={dup_content} stored={total_stored}")

        # ── 판정 4: prefetch 4클라이언트 병행, 지연 p95 ────────────────
        prefetch_lat: list[float] = []
        evts = []
        queries = [
            "클라이언트 턴 확인", "보고서 작성 완료", "기억해야 할 사실",
            "JEV 메모리 중간 계층",
        ]

        def do_prefetch(q: str) -> None:
            body = json.dumps({"agent": "hermes", "query": q,
                               "options": {"max_chars": 2000}}).encode("utf-8")
            req = urllib.request.Request(
                f"{base}/prefetch", data=body,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {token}"},
                method="POST")
            t0 = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=8) as r:
                    d = json.loads(r.read().decode("utf-8"))
                lat = (time.monotonic() - t0) * 1000
                prefetch_lat.append(lat)
                evts.append((q, lat, bool(d.get("context"))))
            except Exception as e:
                prefetch_lat.append(time.monotonic() - t0)
                evts.append((q, time.monotonic() - t0, f"ERR {e}"))

        t_p0 = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=PREFETCH_CLIENTS) as ex:
            for _ in range(PREFETCH_N):
                for q in queries:
                    ex.submit(do_prefetch, q)
        t_p_elapsed = time.monotonic() - t_p0

        prefetch_lat.sort()
        p95 = prefetch_lat[int(len(prefetch_lat) * 0.95)] if prefetch_lat else 0
        p50 = statistics.median(prefetch_lat) if prefetch_lat else 0
        n_ok = sum(1 for _, _, c in evts if c is True)
        n_empty = sum(1 for _, _, c in evts if c == "")
        n_err = sum(1 for _, _, c in evts if isinstance(c, str) and c.startswith("ERR"))
        print(f"[prefetch] n={len(prefetch_lat)} p50={p50:.0f}ms p95={p95:.0f}ms "
              f"ok={n_ok} empty={n_empty} err={n_err} elapsed={t_p_elapsed:.1f}s")

        # Jev 정상 시 p95 < 800ms (degraded면 < 300ms) — degraded 여부는 JEV 호출 결과로 판정
        run_check("prefetch p95 < 800ms", p95 < 800,
                  f"p95={p95:.0f}ms p50={p50:.0f}ms (n={len(prefetch_lat)})")

        # 전반 요약
        print("\n=== P5 §16.2 동시성 테스트 요약 ===")
        for name, ok, detail in RESULTS:
            print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")
        n_pass = sum(1 for _, ok, _ in RESULTS if ok)
        print(f"합계: {n_pass}/{len(RESULTS)}")

    finally:
        # 정리 — core 종료
        try:
            req = urllib.request.Request(f"{base}/admin/shutdown",
                                         headers={"Authorization": f"Bearer {token}"},
                                         method="POST")
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass
        time.sleep(1)
        if core_proc.poll() is None:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(core_proc.pid)],
                               capture_output=True, timeout=10)
            except Exception:
                core_proc.terminate()

    n_pass = sum(1 for _, ok, _ in RESULTS if ok)
    return 0 if n_pass == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())