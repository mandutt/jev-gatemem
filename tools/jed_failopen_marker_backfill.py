"""rejudged 마커 canonical 백필 — gate 원본 복원 + 단일 포맷 통일 (2026-10-03).

검토 확정 사항 (외부 AI 3종 종합):
- canonical: gate(원인, 불변) + rejudged(결과) 분리
- gate 원본 복원: P1 64행 -> snapA(13:10:28, apply 직전), 403 4행 -> snapB(13:32:31)
- rejudged_at: ① rejudge_verdicts(정확) -> ② P1 dry-run 리포트 run_at(판정 배치 시각)
  -> 그 외 없음(NULL). 스냅샷 시각/archived_at은 '판정 시각'으로 쓰지 않음.
  모든 행에 rejudged_at_source 표기 (verdicts | dry_run_report | null)
- valid_until 컬럼 절대 변경 금지 (recall 필터 — 누출/유실 방지)
- metadata_json만 UPDATE, 직렬화 separators=(",", ": ") 고정
- 단일 트랜잭션 + pre/post 검증 + 롤백 지점(온라인 백업)

실행: %LOCALAPPDATA%/jev-mem/venv/Scripts/python.exe tools/jed_failopen_marker_backfill.py
"""
import hashlib
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

LA = os.environ["LOCALAPPDATA"]
MNEMO_DB = Path(LA) / "hermes" / "mnemosyne" / "data" / "mnemosyne.db"
STATE_DB = Path(LA) / "jev-mem" / "core_state.db"
SNAP_A = Path(LA) / "hermes" / "cache" / "scratch" / "failopen_p1_snapshot_20261003_131028.db"
SNAP_B = Path(LA) / "jev-mem" / "backups" / "failopen-403-2rows-20261003_133231.db"
DRY_RUN = Path(LA) / "hermes" / "cache" / "scratch" / "failopen_rejudge_result.json"
BAK_DIR = Path(LA) / "jev-mem" / "backups"

FAILED = []

def log(msg):
    print(msg, flush=True)

def fail(msg):
    FAILED.append(msg)
    log(f"  ❌ {msg}")

# ----------------------------------------------------------------------
def snapshot(db_path, tag):
    os.makedirs(BAK_DIR, exist_ok=True)
    dest = BAK_DIR / f"{tag}-{datetime.now():%Y%m%d_%H%M%S}.db"
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(dest))
    with dst:
        src.backup(dst)
    dst.close(); src.close()
    n1 = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True).execute(
        "SELECT COUNT(*) FROM working_memory").fetchone()[0]
    n2 = sqlite3.connect(f"file:{dest.as_posix()}?mode=ro", uri=True).execute(
        "SELECT COUNT(*) FROM working_memory").fetchone()[0]
    assert n1 == n2, f"백업 행 수 불일치 {n1} != {n2}"
    return dest

# ----------------------------------------------------------------------
def load_dryrun():
    """P1 dry-run 리포트: memory_id -> {verdict, reason, latency_ms}."""
    d = json.loads(DRY_RUN.read_text(encoding="utf-8"))
    out = {}
    for r in d.get("results", []):
        out[r["memory_id"]] = r
    return out, d.get("run_at")

# ----------------------------------------------------------------------
def build_plan():
    """행별 마이그레이션 계획: old/new meta + gate 원본 + rejudged_at 소스."""
    mconn = sqlite3.connect(f"file:{MNEMO_DB.as_posix()}?mode=ro", uri=True)
    mconn.row_factory = sqlite3.Row
    rows = mconn.execute(
        "SELECT id, metadata_json, valid_until FROM working_memory"
        " WHERE metadata_json LIKE '%rejudged%' ORDER BY id").fetchall()
    mconn.close()

    # gate 원본: snapA 우선 -> snapB 보강 (값 로그 포함)
    gate_src = {}
    for sp, tag in [(SNAP_A, "snapA"), (SNAP_B, "snapB")]:
        assert sp.exists(), f"스냅샷 부재: {sp}"
        sc = sqlite3.connect(f"file:{sp.as_posix()}?mode=ro", uri=True)
        ids = [r["id"] for r in rows]
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            ins = ",".join("?" * len(chunk))
            for mid, g in sc.execute(
                    f"SELECT id, json_extract(metadata_json,'$.gate')"
                    f" FROM working_memory WHERE id IN ({ins})", chunk):
                if g and mid not in gate_src:
                    gate_src[mid] = (g, tag)
        sc.close()

    # rejudge_verdicts (정확한 판정 시각)
    sconn = sqlite3.connect(f"file:{STATE_DB.as_posix()}?mode=ro", uri=True)
    sconn.row_factory = sqlite3.Row
    vmap = {r["memory_id"]: dict(r) for r in
            sconn.execute("SELECT memory_id, verdict, model, rejudged_at"
                          " FROM rejudge_verdicts")}
    sconn.close()

    dry, run_at = load_dryrun()

    plan = []
    for r in rows:
        old = json.loads(r["metadata_json"])
        mid = r["id"]
        # 1) verdict: canonical 필드 우선, 없으면 레거시 태그 gate에서
        verdict = old.get("rejudged")
        if not verdict:
            g = str(old.get("gate") or "")
            if g.startswith("rejudged:"):
                verdict = g[len("rejudged:"):].split("@")[0].strip()
        assert verdict in ("keep", "skip"), f"{mid[:16]}: verdict 불명 {old.get('gate')}"

        # 2) gate 원본 (불변식 복원)
        #    - 현 DB gate가 이미 fail_open:* 이면 그 자체가 원본 (필드형 28행)
        #    - 태그형(rejudged:*)이면 스냅샷 체인에서 복원 (P1 64행 + 403 4행)
        cur_gate = str(old.get("gate") or "")
        if cur_gate.startswith("fail_open:"):
            orig, src_tag = cur_gate, "current"
        else:
            orig, src_tag = gate_src.get(mid, (None, None))
        if orig is None:
            fail(f"{mid[:16]}: gate 원본 미커버 (스냅샷 2개 모두)")
            continue
        if not str(orig).startswith("fail_open:"):
            fail(f"{mid[:16]}: 초기 gate가 fail_open 아님 -> {orig!r}")
            continue

        # 3) rejudged_at 소스
        if mid in vmap:
            rj_at, rj_src = vmap[mid]["rejudged_at"], "rejudge_verdicts"
        elif mid in dry:
            rj_at, rj_src = run_at, "dry_run_report"
        else:
            rj_at, rj_src = None, "null"

        # 4) new meta 구성
        new = dict(old)
        new["gate"] = orig                      # 원인 복원
        new["rejudged"] = verdict               # 결과 (단일 필드)
        new["rejudged_at"] = rj_at
        new["rejudged_at_source"] = rj_src
        if verdict == "skip":
            new["archived"] = True              # 2건 보충 포함
            new.setdefault("archived_at", datetime.now().astimezone()
                           .isoformat(timespec="seconds"))
        # 레거시 잔여 제거 (gate 합성 흔적 불필요 — rejudged 필드로 대체)
        new.pop("rejudged_model", None)

        old_raw = json.dumps(old, ensure_ascii=False, separators=(",", ": "))
        new_raw = json.dumps(new, ensure_ascii=False, separators=(",", ": "))
        plan.append({
            "id": mid,
            "verdict": verdict,
            "old_meta": old, "new_meta": new,
            "old_raw": old_raw, "new_raw": new_raw,
            "old_hash": hashlib.sha256(old_raw.encode()).hexdigest()[:16],
            "new_hash": hashlib.sha256(new_raw.encode()).hexdigest()[:16],
            "valid_until": r["valid_until"],   # 불변 — 검증에 사용
            "gate_src": src_tag,
            "rejudged_at": rj_at, "rejudged_at_src": rj_src,
        })
    return plan

# ----------------------------------------------------------------------
def main():
    log("=== 0) preflight ===")
    plan = build_plan()
    if FAILED:
        log(f"preflight 실패: {len(FAILED)}건 — 중단 (변경 없음)")
        sys.exit(2)
    from collections import Counter
    log(f"계획 {len(plan)}행: {dict(Counter(p['verdict'] for p in plan))}")
    log(f"gate 원본 소스: {dict(Counter(p['gate_src'] for p in plan))}")
    log(f"rejudged_at 소스: {dict(Counter(p['rejudged_at_src'] for p in plan))}")
    skip_n = sum(1 for p in plan if p["verdict"] == "skip")
    log(f"skip {skip_n} / keep {len(plan)-skip_n}")

    # ── 1) 롤백 지점: 온라인 백업 ──
    log("\n=== 1) 백업 스냅샷 ===")
    bak = snapshot(MNEMO_DB, "marker-canonicalize")
    log(f"  백업: {bak}")

    # ── 2) dry-run 저널 저장 ──
    log("\n=== 2) dry-run 저널 ===")
    journal = {
        "applied_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "count": len(plan),
        "backup": str(bak),
        "rows": [{
            "id": p["id"], "verdict": p["verdict"],
            "old_hash": p["old_hash"], "new_hash": p["new_hash"],
            "gate_src": p["gate_src"], "rejudged_at_src": p["rejudged_at_src"],
            "changes": {k: p["old_meta"].get(k) for k in
                        ("gate", "rejudged", "rejudged_at",
                         "rejudged_at_source", "archived")}
        } for p in plan],
    }
    jpath = Path(LA) / "hermes" / "cache" / "scratch" / "marker_backfill_journal.json"
    jpath.write_text(json.dumps(journal, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    log(f"  저널: {jpath} ({jpath.stat().st_size:,} bytes)")

    # ── 3) 단일 트랜잭션 백필 — metadata_json만 UPDATE ──
    log("\n=== 3) 트랜잭션 백필 ===")
    conn = sqlite3.connect(str(MNEMO_DB), timeout=30)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for p in plan:
            conn.execute(
                "UPDATE working_memory SET metadata_json=? WHERE id=?",
                (p["new_raw"], p["id"]))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    log(f"  {len(plan)}행 UPDATE 완료 (단일 트랜잭션)")

    # ── 4) post-verify ──
    log("\n=== 4) post-verify ===")
    ok = verify(plan)
    log(f"\n=== 결과: {'PASS' if ok and not FAILED else 'FAIL'} "
        f"(실패 {len(FAILED)}) — 복원 지점: {bak} ===")
    sys.exit(0 if ok and not FAILED else 1)

# ----------------------------------------------------------------------
def verify(plan):
    conn = sqlite3.connect(f"file:{MNEMO_DB.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    pre_ids = {p["id"] for p in plan}
    vus = {p["id"]: p["valid_until"] for p in plan}

    # 4-1) 행별 shape + valid_until 불변
    shape_ok = True
    for p in plan:
        row = conn.execute("SELECT metadata_json, valid_until FROM working_memory"
                           " WHERE id=?", (p["id"],)).fetchone()
        if row is None:
            fail(f"{p['id'][:16]}: 행 소실"); shape_ok = False; continue
        if row["valid_until"] != vus[p["id"]]:
            fail(f"{p['id'][:16]}: valid_until 컬럼 변경 "
                 f"({vus[p['id']]} -> {row['valid_until']})"); shape_ok = False
        d = json.loads(row["metadata_json"])
        if d.get("gate") != p["new_meta"]["gate"]:
            fail(f"{p['id'][:16]}: gate 불일치"); shape_ok = False
        if d.get("rejudged") != p["verdict"]:
            fail(f"{p['id'][:16]}: rejudged 불일치"); shape_ok = False
        if p["verdict"] == "skip" and d.get("archived") is not True:
            fail(f"{p['id'][:16]}: skip인데 archived 누락"); shape_ok = False
        if "rejudged_at_source" not in d:
            fail(f"{p['id'][:16]}: rejudged_at_source 누락"); shape_ok = False
        if '"rejudged": "' not in row["metadata_json"]:
            fail(f"{p['id'][:16]}: canonical 직렬화 아님"); shape_ok = False
    log(f"  행별 shape + valid_until 불변: {'OK' if shape_ok else 'FAIL'}")

    # 4-2) 전수: 96행 canonical / 레거시 태그형 0
    n_canon = conn.execute(
        "SELECT COUNT(*) FROM working_memory WHERE metadata_json LIKE"
        " '%\"rejudged\": \"%'").fetchone()[0]
    n_tag = conn.execute(
        "SELECT COUNT(*) FROM working_memory WHERE metadata_json LIKE"
        " '%\"gate\": \"rejudged:%'").fetchone()[0]
    n_failopen_orig = conn.execute(
        "SELECT COUNT(*) FROM working_memory WHERE metadata_json LIKE"
        " '%\"gate\": \"fail_open:%'").fetchone()[0]
    log(f"  canonical(\"rejudged\")={n_canon} / 레거시 태그형(gate=rejudged:)= {n_tag}"
        f" / gate=fail_open:*={n_failopen_orig}")
    if n_tag != 0:
        fail("레거시 태그형 잔존 > 0")
    if n_canon != len(plan):
        fail(f"canonical 수 불일치: {n_canon} != {len(plan)}")

    # 4-3) skip 24행 recall inactive + keep active 불변
    skip_rows, keep_rows = [], []
    for p in plan:
        row = conn.execute("SELECT valid_until FROM working_memory WHERE id=?",
                           (p["id"],)).fetchone()
        (skip_rows if p["verdict"] == "skip" else keep_rows).append(row[0])
    bad_skip = [v for v in skip_rows if v is None]
    bad_keep = [v for v in keep_rows if v is not None]
    log(f"  skip {len(skip_rows)}행 valid_until: {"OK" if not bad_skip else f"FAIL {len(bad_skip)}"}"
        f" / keep {len(keep_rows)}행 NULL 유지: {"OK" if not bad_keep else f"FAIL {len(bad_keep)}"}")
    if bad_skip: fail("skip인데 valid_until NULL (recall 누출)")
    if bad_keep: fail("keep인데 valid_until 존재 (유실)")

    # 4-4) ID set 동일
    cur_ids = {r["id"] for r in conn.execute(
        "SELECT id FROM working_memory WHERE metadata_json LIKE '%rejudged%'")}
    if cur_ids != pre_ids:
        fail(f"rejudged 행 ID set 변경: ±{len(pre_ids ^ cur_ids)}")
    else:
        log(f"  ID set 동일 ({len(cur_ids)}행)")
    conn.close()
    return shape_ok

if __name__ == "__main__":
    main()