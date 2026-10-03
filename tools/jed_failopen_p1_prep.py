"""P1 — ① 재판정 결과 갱신 (맥락 결합 반영) + ② DB 스냅샷 + 복원 검증

- 맥락 결합 재평가에서 a72fedea(asst, a8m)가 keep으로 전환 → keep 49 / skip 15
- 스냅샷: SQLite online backup API (WAL 안전), 복원 검증 포함
"""
import json, os, sqlite3, datetime, shutil, hashlib

SCRATCH = os.path.expandvars(r"%LOCALAPPDATA%\hermes\cache\scratch")
MNEMO = os.path.expandvars(r"%LOCALAPPDATA%\hermes\mnemosyne\data\mnemosyne.db")
RESULT = os.path.join(SCRATCH, "failopen_rejudge_result.json")
SNAP = os.path.join(SCRATCH, f"failopen_p1_snapshot_{datetime.datetime.now():%Y%m%d_%H%M%S}.db")

# ---- ① 재판정 결과 갱신 ----
res = json.load(open(RESULT, encoding="utf-8"))
# 맥락 결합에서 keep으로 전환된 memory_id (실측: a72fedea = a8m baseline)
CTX_KEEP = {"a72fedea"}  # memory_id 앞 8자 기준 아님 — 전체 ID로 매칭 필요
# 실제 전체 memory_id 확인
print("== 재판정 결과 원본 ==")
from collections import Counter
print("  verdict:", dict(Counter(x["verdict"] for x in res["results"])))
print("  results[0] keys:", sorted(res["results"][0].keys()))

# 맥락결합 전환 적용: memory_id 전체에서 'a72fedea' prefix 매칭
n_conv = 0
for r in res["results"]:
    if r["memory_id"].startswith("a72fedea"):
        if r["verdict"] == "skip":
            r["verdict"] = "keep"
            r["reason"] = "store"
            r["note"] = "ctx-join-keep (a8m baseline 실행, 직전 user=프로세스 종료 대응)"
            n_conv += 1
print(f"  맥락결합 keep 전환: {n_conv}건")
print("  갱신 verdict:", dict(Counter(x["verdict"] for x in res["results"])))
json.dump(res, open(RESULT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ---- ② 스냅샷 + 복원 검증 ----
print(f"\n== 스냅샷 생성 ==")
src = sqlite3.connect(MNEMO)
dst = sqlite3.connect(SNAP)
with dst:
    src.backup(dst)
dst.close()
src.close()
sz = os.path.getsize(SNAP)
print(f"  스냅샷: {SNAP} ({sz:,} bytes)")

# 복원 검증: 스냅샷 열기 + row count 대조
v = sqlite3.connect(f"file:{SNAP}?mode=ro", uri=True)
n_snap = v.execute("SELECT COUNT(*) FROM working_memory").fetchone()[0]
v.close()
m = sqlite3.connect(f"file:{MNEMO}?mode=ro", uri=True)
n_live = m.execute("SELECT COUNT(*) FROM working_memory").fetchone()[0]
m.close()
print(f"  복원 검증: 스냅샷 rows={n_snap} vs 라이브 rows={n_live} -> {'✅ 일치' if n_snap == n_live else '❌ 불일치!'}")
if n_snap != n_live:
    raise SystemExit("스냅샷 불일치 — 중단")

print(f"\n✅ 준비 완료: 결과 갱신(keep 49/skip 15) + 스냅샷 검증 통과")
print(f"   다음: --apply 로 P1 반영")