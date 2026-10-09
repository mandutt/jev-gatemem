# -*- coding: utf-8 -*-
"""0콜 실측: [IMPORTANT: 배경 프로세스 발화가 JEV write gate를 어떻게 통과하는가 (2026-10-09)

목적: 사용자 지적 — '[USER][IMPORTANT: Background process ...] 자동 발화가 메모리에
저장되는 건 좋은 형태가 아니다' → G-qual이 이 패턴을 왜 KEEP하는지, 어떤 조건에서
그런지 실측 (코드 경로 + trace + DB 라벨).

핵심 관측 후보:
1) 이 발화는 Hermes가 만든 시스템 발화임에도 [USER] 역할로 sync_turn에 들어감
2) G-qual 기준: SKIP iff store==NO_STORE && type==NO_STORE && store_conf>=0.6
   — 'no store' 판정이 안 나오면(store=STORE 등) KEEP
3) 내용이 '작업 완료 보고'라 G-qual이 '사실/진행 상태'로 분류할 가능성
"""
import sqlite3, re, json, os
from collections import Counter

TRACE_DIR = r"C:\Users\mandu\AppData\Local\hermes\logs"
DB = r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db"

# 1) trace에서 IMPORTANT 발화의 write-gate 판정 찾기
hits = []
for fn in sorted(os.listdir(TRACE_DIR)):
    if not fn.startswith("jev_trace_2026"): continue
    for line in open(os.path.join(TRACE_DIR, fn), encoding="utf-8", errors="replace"):
        if "write-gate" in line and "IMPORTANT" in line:
            hits.append(line.strip()[:400])
print(f"trace write-gate+IMPORTANT: {len(hits)}건")
for h in hits[:5]:
    print(" ", h)

# 2) DB: IMPORTANT 행의 source/author_type/trust_tier 분포
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
rows = cur.execute("""
    SELECT source, author_type, trust_tier, COUNT(*) c
    FROM working_memory WHERE content LIKE '%[IMPORTANT:%'
    GROUP BY source, author_type, trust_tier ORDER BY c DESC
""").fetchall()
print("\nIMPORTANT 행 원본 분류:")
for r in rows:
    print(f"  source={r['source']} author_type={r['author_type']} trust_tier={r['trust_tier']} x{r['c']}")

# 3) G-qual이 '사실로 봤을' 가능성 — IMPORTANT 행의 memory_type 분포
types = cur.execute("""
    SELECT memory_type, COUNT(*) c FROM working_memory
    WHERE content LIKE '%[IMPORTANT:%' GROUP BY memory_type ORDER BY c DESC
""").fetchall()
print("\nIMPORTANT 행 memory_type:")
for t in types:
    print(f"  {t['memory_type']}: {t['c']}")

# 4) '중복 사실성': IMPORTANT 행들이 서로 content 유사 (같은 프로세스 재보고?)
conn.close()