"""shadow_log 일일 요약 — 텔레그램 전송용 (2026-10-04, 2026-10-05 보강)

매일 09:00 cron이 실행 → shadow_log 최근 24시간 집계 출력
- gate YES/NO/ABSTAIN 분포 (전체 + 24h)
- R2 결정 분포 (inject / abstain / err)
- A vs R2 갈림: gate NO & R2 abstain 건수 (기존 A는 주입이므로 갈림)
- 이상 징후: 과다 NO율, err 증가
- (2026-10-05) assistant 오염 지표: winner가 [ASSISTANT]인 비율 + pooling 지표
"""
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")
CORE_DB = os.path.join(os.environ.get("LOCALAPPDATA", ""), "jev-mem", "core_state.db")

# ---- 2026-10-10: 90일 보존 정책 (무한 축적 방지, 사용자 승인) ----
# shadow_log·query_log 모두 90일(created_at/received_at 기준) 이전 행 삭제.
try:
    prune_cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%S")
    wconn = sqlite3.connect(CORE_DB, timeout=15)
    for table, col in (("shadow_log", "created_at"), ("query_log", "received_at")):
        try:
            n = wconn.execute(f"DELETE FROM {table} WHERE {col} < ?", (prune_cutoff,)).rowcount
            if n:
                print(f"[보존] {table}: {n}건 삭제 (90일 초과)")
        except Exception as e:
            print(f"[보존] {table} 정리 실패: {e}")
    wconn.commit()
    wconn.close()
except Exception as e:
    print(f"[보존] 정리 건너뜀: {e}")

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

# ---- 2026-10-05: assistant 오염 지표 (b-ai #5) ----
MNEM_DB = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes", "mnemosyne", "data", "mnemosyne.db")
pn = ""
try:
    mconn = sqlite3.connect(f"file:{MNEM_DB}?mode=ro", uri=True)
    mconn.row_factory = sqlite3.Row
    # winner_id -> content 프리픽스 [ASSISTANT] 여부
    winners = conn.execute("SELECT DISTINCT winner_id FROM shadow_log WHERE winner_id IS NOT NULL AND winner_id != ''").fetchall()
    assist_ids = set()
    for w in winners:
        wid = w[0]
        r = mconn.execute("SELECT content FROM working_memory WHERE id=?", (wid,)).fetchone()
        if not r:
            r = mconn.execute("SELECT content FROM episodic_memory WHERE id=?", (wid,)).fetchone()
        if r and r["content"].lstrip().startswith("[ASSISTANT]"):
            assist_ids.add(wid)
    total_win = conn.execute("SELECT COUNT(*) FROM shadow_log WHERE winner_id IS NOT NULL AND winner_id != ''").fetchone()[0]
    if assist_ids:
        ph = ",".join("?" * len(assist_ids))
        n_assist_win = conn.execute(
            f"SELECT COUNT(*) FROM shadow_log WHERE winner_id IN ({ph})", list(assist_ids)
        ).fetchone()[0]
    else:
        n_assist_win = 0
    assist_rate = n_assist_win / total_win if total_win else 0
    pn = f"\n[assistant 오염] 최종 선택(winner) 중 [ASSISTANT] 비율: {assist_rate*100:.1f}% ({n_assist_win}/{total_win})"
    mconn.close()
except Exception as e:
    pn = f"\n[assistant 오염] 계산 실패: {e}"

print("=== jev-mem shadow 일일 요약 ===")
print(f"누적 총 {total}건 | 최근 24h {n_24h}건")
print()
print(f"[게이트 분포 - 전체] YES {g_all.get('YES', 0)} | NO {g_all.get('NO', 0)} | ABSTAIN {g_all.get('ABSTAIN', 0)}")
if n_24h:
    print(f"[게이트 분포 - 24h]  YES {g_24h.get('YES', 0)} | NO {g_24h.get('NO', 0)} | ABSTAIN {g_24h.get('ABSTAIN', 0)}")
print()
print(f"[R2 abstain 결정(잠재 갈림)] 전체 {flip}건 | 24h {flip_24h}건")
print(f"[오류] {errs}건")
print(pn)

# 이상 징후 감지
no_rate = g_all.get("NO", 0) / total if total else 0
yes_rate = g_all.get("YES", 0) / total if total else 0
# ★ 2026-10-10 사용자 라벨링 실측: NO 64%가 작업지시(work) — "NO=과다거부" 경고 기준은
#   작업지시 비율(약 2/3)을 감안해 0.30 → 0.75로 상향 (a-ai 권고 0.60보다 보수적).
#   실제 과다거부 신호는 NO율이 아니라 L2_YES (canary 정답 abstain) + need 비율로 본다.
print()
if no_rate > 0.75:
    print("⚠️ 경고: gate NO율 75% 초과 — 과다거부 의심 (운영 영향 검토 필요)")
elif no_rate > 0.5:
    print("ℹ️ 참고: gate NO율 50% 초과 — 작업지시 밀집 구간일 수 있음 (라벨 감사 시점 확인)")
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