# -*- coding: utf-8 -*-
"""0-콜 DB 프로브: additive 중복(같은 사실의 여러 버전)이 실제로 존재하는지 확인.

mem0 글의 'timestamps matter' 포인트 검증 — 우리 코퍼스에서
같은 주제/사실이 여러 행으로 쌓여 Jev가 최신 버전을 구분할
단서 없이 라벨만 읽는 구조가 실제 손실을 만드는지 본다.
"""
import sqlite3, re, sys, json
from collections import Counter

DB = r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

total = conn.execute("SELECT COUNT(*) FROM working_memory").fetchone()[0]
print(f"[i] working_memory 전체 행: {total}")

# 1) 중요한 구조 지표
for lab, sql in [
    ("superseded 보유 (구버전 제거 메커니즘 존재)", "SELECT COUNT(*) c FROM working_memory WHERE superseded_by IS NOT NULL"),
    ("valid_until 설정 행", "SELECT COUNT(*) c FROM working_memory WHERE valid_until IS NOT NULL"),
    ("[ASSISTANT] 프리픽스 행", "SELECT COUNT(*) c FROM working_memory WHERE content LIKE '[ASSISTANT]%'"),
]:
    try:
        print(f"[i] {lab}: {conn.execute(sql).fetchone()[0]}")
    except Exception as e:
        print(f"[!] {lab} 조회 실패: {e}")

# 2) 병렬 행 = 같은 content (정확 중복)
dup = conn.execute("""
    SELECT content, COUNT(*) c, GROUP_CONCAT(id) ids, MIN(created_at) mn, MAX(created_at) mx
    FROM working_memory GROUP BY content HAVING c > 1 ORDER BY c DESC LIMIT 15
""").fetchall()
print(f"\n[중복 content] 정확히 같은 content가 2+ 행: 총 {len(dup)} 그룹 (상위 15)")
for r in dup:
    print(f"  x{r['c']} [{r['mn'][:10]}~{r['mx'][:10]}] ids={r['ids'][:60]}")
    print(f"    {r['content'][:110]}")

# 3) 주제 유사 중복 — 첫 문장/핵심 명사 기준으로 느슨한 클러스터링
import unicodedata
def norm(s):
    s = re.sub(r"\[(USER|ASSISTANT|SYSTEM)\]", "", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s

rows = conn.execute("SELECT id, content, created_at, memory_type FROM working_memory ORDER BY created_at").fetchall()
print(f"\n[i] 클러스터링 대상: {len(rows)} 행")

def korean_nouns(t):
    # 한글 음절 + 영숫자 토큰 (조사 제거는 불가하므로 2자 이상 음절만)
    toks = re.findall(r"[가-힣]{2,}|[A-Za-z_][A-Za-z0-9_]{2,}", t)
    return set(toks)

def drop_common(s):
    stop = {"그리고","그런데","있습니다","했습니다","합니다","입니다","하는","있는","이라는","그래서",
            "하기","위해","하기","위한","관련","대한","경우","때문","통해","이후","이전","현재","다음",
            "사용","사용자","하기","하려면","하려고","등등","등의","및"}
    return set(t for t in s if t not in stop and len(t) >= 2)

clusters = []
seen = [False]*len(rows)
for i in range(len(rows)):
    if seen[i]: continue
    grp = [rows[i]]
    seen[i] = True
    ni = drop_common(korean_nouns(norm(rows[i]["content"])))
    if len(ni) < 2: continue
    for j in range(i+1, len(rows)):
        if seen[j]: continue
        nj = drop_common(korean_nouns(norm(rows[j]["content"])))
        inter = ni & nj
        if len(inter) >= 3 and len(inter)/max(len(ni), len(nj)) >= 0.5:
            grp.append(rows[j]); seen[j] = True
    if len(grp) >= 2:
        clusters.append(grp)

print(f"[클러스터] 명사 50%+ 겹침 & 3개 이상 공유 → {len(clusters)} 그룹 (2+ 행)")
for g in sorted(clusters, key=len, reverse=True)[:12]:
    dates = sorted(r["created_at"][:10] for r in g)
    print(f"\n  [{len(g)}행, {dates[0]}~{dates[-1]}] types={Counter(r['memory_type'] for r in g)}")
    for r in g[:4]:
        print(f"    {r['id']} {r['created_at'][:16]} | {norm(r['content'])[:90]}")