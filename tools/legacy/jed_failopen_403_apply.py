"""실제 403 2건 반영 (P1 절차 재사용) — 스냅샷 + apply + 검증.

⚠️ DEPRECATED — DO NOT RUN (canonical 마커 포맷으로 백필 완료, 2026-10-03).
이 스크립트는 gate를 'rejudged:skip@jev-latest'로 덮어쓰는 레거시 태그형
포맷을 생성한다 (원인 정보 훼손 + canonical 불변식 위반). 재실행 금지.
"""
raise SystemExit(
    "DEPRECATED: legacy tag-format writer — canonical backfill completed "
    "(2026-10-03). See tools/jed_failopen_marker_backfill.py.")

import json
import os
import sqlite3
import time
from datetime import datetime

MNEMO_DB = os.path.expandvars(r"%LOCALAPPDATA%\hermes\mnemosyne\data\mnemosyne.db")
STATE_DB = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\core_state.db")

SKIP_IDS = ["48f06bb6ed2360d7", "c4a672ed2edc9835"]
KEEP_IDS = ["8c7b3441597eb71c", "c8b457b64b666e2c"]
SNAP_DIR = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\backups")

def snapshot(db_path: str, tag: str) -> str:
    os.makedirs(SNAP_DIR, exist_ok=True)
    dest = os.path.join(SNAP_DIR, f"{tag}-{time.strftime('%Y%m%d_%H%M%S')}.db")
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(dest)
    with dst:
        src.backup(dst)
    dst.close(); src.close()
    # 복원 검증: 백업 파일이 열리고 행 수 일치
    chk = sqlite3.connect(dest)
    n_orig = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True).execute(
        "SELECT COUNT(*) FROM working_memory").fetchone()[0]
    n_back = chk.execute("SELECT COUNT(*) FROM working_memory").fetchone()[0]
    chk.close()
    assert n_orig == n_back, f"백업 불일치: {n_orig} != {n_back}"
    return dest

def apply():
    now = datetime.now().isoformat(timespec="seconds")
    mconn = sqlite3.connect(MNEMO_DB)
    mconn.row_factory = sqlite3.Row

    for mid, verdict, keep_gate in (
            [(i, "skip", False) for i in SKIP_IDS] + [(i, "keep", True) for i in KEEP_IDS]):
        row = mconn.execute("SELECT metadata_json FROM working_memory WHERE id=?", (mid,)).fetchone()
        if not row:
            print(f"  {mid}: 행 없음"); continue
        meta = json.loads(row["metadata_json"] or "{}")
        old_gate = meta.get("gate")
        meta["gate"] = f"rejudged:{verdict}@jev-latest"
        meta["rejudged_at"] = now
        q = "UPDATE working_memory SET metadata_json=?"
        args = [json.dumps(meta, ensure_ascii=False)]
        if not keep_gate:
            meta["archived"] = True
            q += ", valid_until=?"
            args.append(now)
        q += " WHERE id=?"
        args.append(mid)
        mconn.execute(q, args)
        print(f"  {mid[:16]} {verdict.upper():4} gate: {old_gate} -> {meta['gate']}"
              + (" | archived+valid_until" if not keep_gate else ""))
    mconn.commit()

    # verdict apply_status 갱신
    sconn = sqlite3.connect(STATE_DB)
    for mid in SKIP_IDS + KEEP_IDS:
        sconn.execute(
            "UPDATE rejudge_verdicts SET apply_status='applied' WHERE memory_id=?", (mid,))
    sconn.commit()
    print("verdict apply_status=applied 갱신")

def verify():
    mconn = sqlite3.connect(f"file:{MNEMO_DB}?mode=ro", uri=True)
    mconn.row_factory = sqlite3.Row
    # recall 활성 검증 (P1 방식: valid_until IS NULL + archived 아님)
    for mid, expect_active in (
            [(i, False) for i in SKIP_IDS] + [(i, True) for i in KEEP_IDS]):
        row = mconn.execute(
            "SELECT metadata_json, valid_until FROM working_memory WHERE id=?", (mid,)).fetchone()
        meta = json.loads(row["metadata_json"] or "{}")
        active = row["valid_until"] is None and not meta.get("archived")
        ok = active == expect_active
        print(f"  {mid[:16]} recall_active={active} (기대 {expect_active})"
              + (" ✅" if ok else " ❌"))
        assert ok
    # fail_open 잔여 확인
    n = mconn.execute(
        "SELECT COUNT(*) FROM working_memory WHERE metadata_json LIKE '%fail_open%'"
        " AND metadata_json NOT LIKE '%rejudged%'").fetchone()[0]
    print(f"  재판정 전 fail_open 잔여: {n} (0이어야 함)")
    print("=== 검증 통과 ===")

if __name__ == "__main__":
    print("=== 1) 스냅샷 ===")
    snap = snapshot(MNEMO_DB, "failopen-403-2rows")
    print(f"  백업: {snap} (복원 검증 통과, 실 DB와 행 수 일치)")
    print("=== 2) apply ===")
    apply()
    print("=== 3) 검증 ===")
    verify()
    print(f"\n완료. 복원 지점: {snap}")