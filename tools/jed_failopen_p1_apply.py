"""P1 — ② 64건 반영: keep 49 승격 + skip 15 staged (---apply)

- keep → metadata.gate = "rejudged:keep" (정상 승격, 감사 이력 유지)
- skip → metadata.gate = "rejudged:skip" + "archived": true (recall 가역적 숨김, 하드 삭제 아님)
- dry-run 기본; --apply 로만 DB 변경
- rollback: 스냅샷 복원 또는 백업 failopen_tag_backup.json (gate_old 원복)
"""
import argparse, json, os, sqlite3, datetime, sys

MNEMO = os.path.expandvars(r"%LOCALAPPDATA%\hermes\mnemosyne\data\mnemosyne.db")
RESULT = os.path.expandvars(r"%LOCALAPPDATA%\hermes\cache\scratch\failopen_rejudge_result.json")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    res = json.load(open(RESULT, encoding="utf-8"))
    results = res["results"]
    keeps = [x for x in results if x["verdict"] == "keep"]
    skips = [x for x in results if x["verdict"] == "skip"]
    others = [x for x in results if x["verdict"] not in ("keep", "skip")]
    print(f"keep={len(keeps)} skip={len(skips)} others={len(others)}")

    m = sqlite3.connect(MNEMO, timeout=15)
    cur = m.cursor()
    plan = []
    for r in keeps:
        plan.append((r["memory_id"], "rejudged:keep"))
    for r in skips:
        plan.append((r["memory_id"], "rejudged:skip", True))

    # 현재 메모리 상태 대조
    n_exist = 0
    for p in plan:
        row = cur.execute("SELECT metadata_json FROM working_memory WHERE id=?", (p[0],)).fetchone()
        if row:
            n_exist += 1
    print(f"대상 행 존재: {n_exist}/{len(plan)}")

    if not args.apply:
        print("\n[dry-run] 변경 없음. --apply 로 반영")
        m.close()
        return

    # apply
    n_ok = 0
    for p in plan:
        mid = p[0]
        row = cur.execute("SELECT metadata_json FROM working_memory WHERE id=?", (mid,)).fetchone()
        if not row:
            continue
        meta = json.loads(row[0] or "{}")
        if p[1] == "rejudged:skip":
            meta["gate"] = "rejudged:skip"
            meta["archived"] = True
        else:
            meta["gate"] = "rejudged:keep"
        cur.execute("UPDATE working_memory SET metadata_json=? WHERE id=?",
                    (json.dumps(meta, ensure_ascii=False), mid))
        n_ok += 1
    m.commit()
    m.close()
    print(f"\n[apply] 반영 완료: {n_ok}건 (keep {len(keeps)} 승격 + skip {len(skips)} staged)")

    # 검증
    m2 = sqlite3.connect(f"file:{MNEMO}?mode=ro", uri=True)
    n_keep = m2.execute("SELECT COUNT(*) FROM working_memory WHERE metadata_json LIKE '%rejudged:keep%'").fetchone()[0]
    n_skip = m2.execute("SELECT COUNT(*) FROM working_memory WHERE metadata_json LIKE '%rejudged:skip%'").fetchone()[0]
    n_fo = m2.execute("SELECT COUNT(*) FROM working_memory WHERE metadata_json LIKE '%fail_open%'").fetchone()[0]
    m2.close()
    print(f"검증: rejudged:keep={n_keep} rejudged:skip={n_skip} 잔여 fail_open={n_fo}")

if __name__ == "__main__":
    main()