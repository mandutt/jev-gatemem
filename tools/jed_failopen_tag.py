"""① 장애 기간(fail-open) 메모리 식별 + 백필 태깅 (JEV 호출 없음, SQLite 전용)

- 대상: ingest_ledger.status='stored' AND received_at in (2026-10-02, 2026-10-03)
        AND decisions_json reason이 http-402/http-403 (fail-open 저장)
- 작업: 1) 대상 목록을 JSON으로 백업 (before_tag_backup)
        2) memory_ids_json의 각 메모리 row에 metadata_json.gate = "fail_open:http-4xx" 태깅
- idempotent: 이미 gate 마커 있는 행은 결과에서 구분, 재실행 안전
- 안전장치: --apply 없으면 dry-run (변경 없음)
"""
import argparse, json, os, sqlite3, sys, datetime

MNEMO = os.path.expandvars(r"%LOCALAPPDATA%\hermes\mnemosyne\data\mnemosyne.db")
CORE = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\core_state.db")
OUT = os.path.expandvars(r"%LOCALAPPDATA%\hermes\cache\scratch\failopen_tag_backup.json")

def ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 태깅 (기본 dry-run)")
    args = ap.parse_args()

    core = ro(CORE)
    led = core.execute("""
        SELECT idem_key, received_at, memory_ids_json, decisions_json
        FROM ingest_ledger
        WHERE status='stored'
          AND (received_at LIKE '2026-10-02%' OR received_at LIKE '2026-10-03%')
        ORDER BY received_at
    """).fetchall()
    core.close()

    targets = []   # {idem_key, received_at, memory_id, reason}
    reasons = {}
    for idem, recv, mem_ids, dec in led:
        try:
            d = json.loads(dec or "{}")
        except Exception:
            continue
        for role in ("user", "assistant"):
            r = d.get(role) or {}
            reason = str(r.get("reason") or "")
            if reason.startswith("http-4") and r.get("keep"):
                mids = json.loads(mem_ids or "[]") if mem_ids else []
                # memory_ids_json은 [user_id, asst_id] 순서로 저장됨 (store.py 저장 순서)
                if mids:
                    targets.append({
                        "idem_key": idem, "received_at": recv,
                        "memory_id": mids[0] if role == "user" else mids[-1],
                        "reason": reason, "role": role,
                    })
                    reasons[reason] = reasons.get(reason, 0) + 1

    # mnemosyne rows 확인 (실존 여부 + 이미 태깅 여부)
    m = ro(MNEMO)
    cur = m.cursor()
    rows_info = []
    existing = 0
    missing = 0
    by_id = {}
    for t in targets:
        mid = t["memory_id"]
        row = cur.execute(
            "SELECT id, metadata_json FROM working_memory WHERE id=?", (mid,)
        ).fetchone()
        if row:
            meta = json.loads(row[1] or "{}")
            old = meta.get("gate")
            by_id[mid] = {"meta": meta, "gate_old": old}
            if old and old.startswith("fail_open"):
                existing += 1
            t["exists"] = True
            t["gate_old"] = old
        else:
            missing += 1
            t["exists"] = False

    print(f"식별된 fail-open 저장 턴: {len(set(t['idem_key'] for t in targets))}턴")
    print(f"  대상 메모리 row: {len(targets)} (user/asst 별개)")
    print(f"  reason 분포: {reasons}")
    print(f"  working_memory 존재: {len(targets)-missing} / 없음: {missing}")
    print(f"  이미 fail_open 태깅됨: {existing}")

    # 백업 저장 (dry-run에도 백업은 생성 — 복원용)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    backup = {"created_at": datetime.datetime.now().isoformat(),
              "targets": targets, "by_id": {k: v["meta"] for k, v in by_id.items()}}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(backup, f, ensure_ascii=False, indent=1)
    print(f"백업 (복원용): {OUT} (대상 {len(targets)})")

    if not args.apply:
        print("\n[dry-run] --apply 없음 — 변경 없음. 적용하려면 --apply")
        return

    # 실제 태깅 — 트랜잭션
    mw = sqlite3.connect(MNEMO, timeout=10)
    try:
        n = 0
        for t in targets:
            if not t["exists"]:
                continue
            meta = by_id[t["memory_id"]]["meta"]
            if meta.get("gate") and meta["gate"].startswith("fail_open"):
                continue
            meta["gate"] = f"fail_open:{t['reason']}"
            mw.execute(
                "UPDATE working_memory SET metadata_json=? WHERE id=?",
                (json.dumps(meta, ensure_ascii=False), t["memory_id"]),
            )
            n += 1
        mw.commit()
        print(f"\n[apply] 태깅 완료: {n}건")
    except Exception:
        mw.rollback()
        raise
    finally:
        mw.close()

if __name__ == "__main__":
    main()