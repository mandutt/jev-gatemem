"""shadow_log 일일 요약 — 텔레그램 전송용 (2026-10-04)

매일 09:00 cron이 실행 → shadow_log 최근 24시간 집계 출력
- gate YES/NO/ABSTAIN 분포 (전체 + 24h)
- R2 결정 분포 (inject / abstain / err)
- A vs R2 갈림: gate NO & R2 abstain 건수 (기존 A는 주입이므로 갈림)
- 이상 징후: 과다 NO율, err 증가
"""
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")
CORE_DB = os.path.join(os.environ.get("LOCALAPPDATA", ""), "jev-mem", "core_state.db")

conn = sqlite3.connect(f"file:{CORE_DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

total = conn.execute("SELECT COUNT(*) FROM shadow_log").fetchone()[0]
if total == 0:
    print("shadow_log 비어 있음 — 아직 수집 없음")
    conn.close()
    sys.exit(0)

# 24h 컷오프
cutoff = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")

def agg(col, where="1=1"):
    rows = conn.execute(f"SELECT {col}, COUNT(*) as c FROM shadow_log WHERE {where} GROUP BY {col}").fetchall()
    return {r[col] or "NULL": r["c"] for r in rows}

# 전체 + 24h
g_all = agg("gate_verdict")
g_24h = agg("gate_verdict", f"created_at >= '{cutoff}'")
r2_all = agg("r2_decision")
n_24h = conn.execute(f"SELECT COUNT(*) FROM shadow_log WHERE created_at >= '{cutoff}'").fetchone()[0]

# A vs R2 갈림: gate NO이거나 abstain인데 (R2가 abstain 결정) — 기존 A는 주입 상태
# → shadow에서 R2가 abstain으로 결정한 건수 = 잠재 갈림
flip = conn.execute("SELECT COUNT(*) FROM shadow_log WHERE r2_decision LIKE 'abstain%'").fetchone()[0]
flip_24h = conn.execute(f"SELECT COUNT(*) FROM shadow_log WHERE r2_decision LIKE 'abstain%' AND created_at >= '{cutoff}'").fetchone()[0]

# err
errs = conn.execute("SELECT COUNT(*) FROM shadow_log WHERE err IS NOT NULL AND err != ''").fetchone()[0]

print("=== jev-mem shadow 일일 요약 ===")
print(f"누적 총 {total}건 | 최근 24h {n_24h}건")
print()
print(f"[게이트 분포 - 전체] YES {g_all.get('YES', 0)} | NO {g_all.get('NO', 0)} | ABSTAIN {g_all.get('ABSTAIN', 0)}")
if n_24h:
    print(f"[게이트 분포 - 24h]  YES {g_24h.get('YES', 0)} | NO {g_24h.get('NO', 0)} | ABSTAIN {g_24h.get('ABSTAIN', 0)}")
print()
print(f"[R2 abstain 결정(잠재 갈림)] 전체 {flip}건 | 24h {flip_24h}건")
print(f"[오류] {errs}건")

# 이상 징후 감지
no_rate = g_all.get("NO", 0) / total if total else 0
yes_rate = g_all.get("YES", 0) / total if total else 0
print()
if no_rate > 0.3:
    print("⚠️ 경고: gate NO율 30% 초과 — 과다거부 의심 (운영 영향 검토 필요)")
elif no_rate > 0.15:
    print("ℹ️ 참고: gate NO율 15% 초과 — 모니터링 지속")
else:
    print("✅ gate NO율 정상 범위")
if flip / total > 0.3 if total else False:
    print("⚠️ 경고: R2 abstain 비율 30% 초과 — 과다 기권 의심")
else:
    print("✅ R2 abstain 비율 정상 범위")
if errs / total > 0.05 if total else False:
    print("⚠️ 경고: 오류율 5% 초과")
else:
    print("✅ 오류율 정상")

conn.close()