"""rejudge_verdicts P1 64건 백필 — 감사 SoT 정합 (2026-10-03).

배경: P1 수동 재판정(2026-10-03 12:42) 시 rejudge_verdicts 테이블이 없어
판정 이력이 metadata와 dry-run JSON에만 남았다. 이후 생성된 32건(P2b/P3a)은
테이블에 있으나 P1 64건은 결손 → 감사 이력 SoT 불완전.

소스: %LOCALAPPDATA%/hermes/cache/scratch/failopen_rejudge_result.json (P1 dry-run)
- verdict/reason/latency_ms 실측 보유
- rejudged_at = 배치 run_at (판정 시각), model = jev-latest (실측 판정 모델)
- incident_id = metadata에서 추출

사전검증(스크립트 자체):
- dry-run 64건 ∩ 기존 verdicts 32건 == 0 (중복 삽입 방지)
- dry-run verdict vs 현재 metadata.rejudged 불일치 0 (데이터 신뢰)
- dry-run 행 전부 working_memory에 존재

실행: %LOCALAPPDATA%/jev-mem/venv/Scripts/python.exe tools/jed_failopen_verdicts_backfill.py
"""
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

LA = os.environ["LOCALAPPDATA"]
STATE_DB = Path(LA) / "jev-mem" / "core_state.db"
MNEMO_DB = Path(LA) / "hermes" / "mnemosyne" / "data" / "mnemosyne.db"
DRY_RUN = Path(LA) / "hermes" / "cache" / "scratch" / "failopen_rejudge_result.json"
BAK_DIR = Path(LA) / "jev-mem" / "backups"

FAILED = []

def log(msg):
    print(msg, flush=True)

def fail(msg):
    FAILED.append(msg)
    log(f"  ❌ {msg}")

def snapshot(db_path, tag):
    os.makedirs(BAK_DIR, exist_ok=True)
    dest = BAK_DIR / f"{tag}-{datetime.now():%Y%m%d_%H%M%S}.db"
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(dest))
    with dst:
        src.backup(dst)
    dst.close(); src.close()
    n1 = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True).execute(
        "SELECT COUNT(*) FROM rejudge_verdicts").fetchone()[0]
    n2 = sqlite3.connect(f"file:{dest.as_posix()}?mode=ro", uri=True).execute(
        "SELECT COUNT(*) FROM rejudge_verdicts").fetchone()[0]
    assert n1 == n2, f"백업 불일치 {n1} != {n2}"
    return dest

def main():
    # ---- 0) preflight ----
    log("=== 0) preflight ===")
    dry = json.loads(DRY_RUN.read_text(encoding="utf-8"))
    items = dry.get("results", [])
    run_at = dry.get("run_at")
    log(f"dry-run: {len(items)}건, run_at={run_at}")

    sconn = sqlite3.connect(f"file:{STATE_DB.as_posix()}?mode=ro", uri=True)
    sconn.row_factory = sqlite3.Row
    existing = {r["memory_id"] for r in sconn.execute("SELECT memory_id FROM rejudge_verdicts")}
    sconn.close()
    log(f"기존 verdicts: {len(existing)}건")

    mconn = sqlite3.connect(f"file:{MNEMO_DB.as_posix()}?mode=ro", uri=True)
    mconn.row_factory = sqlite3.Row

    overlap = [i for i in items if i["memory_id"] in existing]
    if overlap:
        fail(f"기존 verdicts와 {len(overlap)}건 겹침 — 중단")

    no_row = [i["memory_id"] for i in items
              if not mconn.execute("SELECT 1 FROM working_memory WHERE id=?",
                                   (i["memory_id"],)).fetchone()]
    if no_row:
        fail(f"working_memory에 없는 행 {len(no_row)}건 — 중단")

    # verdict 대조 (metadata.rejudged vs dry)
    mism = []
    for it in items:
        cur = mconn.execute(
            "SELECT json_extract(metadata_json,'$.rejudged') AS v"
            " FROM working_memory WHERE id=?", (it["memory_id"],)).fetchone()
        if not cur or cur["v"] != it["verdict"]:
            mism.append(it["memory_id"][:16])
    if mism:
        fail(f"metadata.rejudged와 불일치 {len(mism)}건: {mism[:5]}")
    mconn.close()
    if FAILED:
        log(f"preflight 실패 {len(FAILED)}건 — 중단 (변경 없음)")
        sys.exit(2)

    log(f"preflight 통과: 삽입 대상 {len(items)}건")

    # ---- 1) 백업 ----
    log("\n=== 1) 백업 스냅샷 ===")
    bak = snapshot(STATE_DB, "verdicts-p1-backfill")
    log(f"  백업: {bak}")

    # ---- 2) INSERT ----
    log("\n=== 2) INSERT ===")
    conn = sqlite3.connect(str(STATE_DB), timeout=30)
    mconn = sqlite3.connect(f"file:{MNEMO_DB.as_posix()}?mode=ro", uri=True)
    mconn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        n = 0
        for it in items:
            inc = mconn.execute(
                "SELECT json_extract(metadata_json,'$.incident_id') AS i"
                " FROM working_memory WHERE id=?", (it["memory_id"],)).fetchone()
            conn.execute(
                "INSERT OR REPLACE INTO rejudge_verdicts"
                " (memory_id, verdict, model, reason, conf, lat_ms, rejudged_at,"
                "  incident_id, apply_status) VALUES (?,?,?,?,?,?,?,?,?)",
                (it["memory_id"], it["verdict"], "jev-latest", it["reason"],
                 None, int(it.get("latency_ms") or 0),
                 run_at, (inc["i"] or "") if inc else "", "applied"))
            n += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close(); mconn.close()
    log(f"  {n}건 INSERT 완료")

    # ---- 3) 검증 ----
    log("\n=== 3) 검증 ===")
    vconn = sqlite3.connect(f"file:{STATE_DB.as_posix()}?mode=ro", uri=True)
    vconn.row_factory = sqlite3.Row
    total = vconn.execute("SELECT COUNT(*) FROM rejudge_verdicts").fetchone()[0]
    if total != len(existing) + len(items):
        fail(f"총 행 수 불일치: {total} != {len(existing)}+{len(items)}")
    else:
        log(f"  총 행 수: {total} (기존 {len(existing)} + 신규 {len(items)}) OK")
    dist = Counter(r["verdict"] for r in vconn.execute("SELECT verdict FROM rejudge_verdicts"))
    log(f"  verdict 전체 분포: {dict(dist)}")
    st = Counter(r["apply_status"] for r in vconn.execute("SELECT apply_status FROM rejudge_verdicts"))
    log(f"  apply_status 분포: {dict(st)}")
    # P1 64건 확인
    ids = [i["memory_id"] for i in items]
    ins = ",".join("?" * len(ids))
    found = vconn.execute(
        f"SELECT memory_id, verdict, rejudged_at, incident_id FROM rejudge_verdicts"
        f" WHERE memory_id IN ({ins})", ids).fetchall()
    if len(found) != len(ids):
        fail(f"백필 행 조회 불일치: {len(found)} != {len(ids)}")
    else:
        empty_inc = sum(1 for r in found if not r["incident_id"])
        log(f"  P1 64건 전부 존재, incident_id 미기재 {empty_inc}건")
    vconn.close()

    log(f"\n=== 결과: {'PASS' if not FAILED else 'FAIL'} (실패 {len(FAILED)}) — 복원 지점: {bak} ===")
    sys.exit(0 if not FAILED else 1)

if __name__ == "__main__":
    main()