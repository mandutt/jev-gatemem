"""신규 골든셋 큐레이션 확충 — 라이브 DB에서 gold 쿼리 후보 자동 생성

목표: 2×2 본실험 n≈300 표본 확충 (합성 180 목표, 현재 139)
- 운영 90 (golden_eval_v2)과 gold_id 겹치지 않는 라이브 메모리 사용
- 다중 gold 우선 (정답 2~3개가 필요한 질문 — multi-evidence 이득 관측)
- 자동 템플릿 질문 생성 (회귀 방지: 사람 큐레이션 vs 자동 recall 차이 기록)
- 산출: experiments/operational-golden/data/golden_new_queries.json
  [{qid, query, type, gold_ids, gold_excerpts, auto:true}]
"""
import hashlib
import json
import os
import random
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")

DB = os.path.expandvars(r"%LOCALAPPDATA%\hermes\mnemosyne\data\mnemosyne.db")
OUT = "experiments/operational-golden/data/golden_new_queries.json"

# 기존 운영/합성 gold_id (중복 방지)
EXISTING = set()
for f in [
    "experiments/operational-golden/data/golden_eval_v2.json",
    "data/dataset_curated.json",
    "data/dataset_auto_v2.json",
]:
    try:
        d = json.load(open(f, encoding="utf-8"))
    except FileNotFoundError:
        continue
    for x in d:
        g = x.get("gold_ids") or x.get("gold_id")
        if isinstance(g, list):
            EXISTING.update(g)
        elif g:
            EXISTING.add(g)

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

# 중요 메모리: fact/error/preference/instruction 유형, 100자 이상, 기존 gold 제외
rows = conn.execute(
    """SELECT id, content, memory_type FROM working_memory
       WHERE valid_until IS NULL AND content IS NOT NULL
         AND length(content) > 100
         AND memory_type IN ('fact','error','preference','instruction','artifact')
       ORDER BY created_at DESC LIMIT 400"""
).fetchall()
conn.close()

cands = [r for r in rows if r["id"] not in EXISTING]
print(f"후보: {len(cands)} (기존 gold {len(EXISTING)}개 제외)")

# 카테고리별 분류 + gold 쿼리 자동 생성
rng = random.Random(20261003)
rng.shuffle(cands)

templates = {
    "fact": [
        "라이브 시스템에서 {kw} 관련해서 어떤 설정이 적용되어 있어?",
        "{kw} 구성을 바꾼 적이 있어? 구체적으로 어떻게 했어?",
        "{kw} 작업을 할 때 어떤 도구나 절차를 사용해?",
    ],
    "error": [
        "{kw} 관련해서 겪었던 오류(에러)는 뭐였어? 어떻게 해결했어?",
        "{kw} 작업 중에 발생했던 문제가 있었어? 원인과 해결책이 뭐야?",
    ],
    "preference": [
        "{kw}에 대해 사용자가 선호하는 방식이 있어?",
        "{kw} 작업할 때 주의하거나 선호하는 점이 뭐야?",
    ],
    "instruction": [
        "{kw} 작업을 할 때 따라야 하는 규칙이나 지침이 있어?",
    ],
    "artifact": [
        "{kw} 관련해서 생성한 파일이나 산출물이 있어? 어디에 저장돼?",
    ],
}


def extract_kw(content):
    """첫 문장에서 명사구 후보 추출 ([USER]/[ASSISTANT] 프리픽스 제거 후)"""
    import re
    s = re.sub(r"^\[(USER|ASSISTANT)\]\s*", "", content.strip())[:120]
    # 한글 명사/영단어/숫자/마침표 기준 첫 토큰 2~4개
    m = re.findall(r"[A-Za-z0-9_\-\.]+|[가-힣]{2,8}", s)
    if not m:
        return ""
    # 첫 토큰이 일반명사(USER/가겠/합니다 등)면 다음 토큰까지
    kw = m[0]
    if kw in ("USER", "ASSISTANT", "저는", "네", "좋아", "안녕", "합니다") and len(m) > 1:
        kw = m[1]
    return kw


queries = []
seen = set()
for r in cands:
    if len(queries) >= 44:
        break
    kw = extract_kw(r["content"])
    if not kw or len(kw) < 2:
        continue
    pool = templates.get(r["memory_type"], templates["fact"])
    q = rng.choice(pool).format(kw=kw)
    if q in seen:
        continue
    seen.add(q)
    queries.append({
        "qid": f"n{len(queries)+1:03d}",
        "query": q,
        "type": r["memory_type"],
        "gold_ids": [r["id"]],
        "gold_excerpts": [r["content"][:150]],
        "auto": True,
    })

json.dump(queries, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"생성: {len(queries)}건 → {OUT}")
print("타입 분포:", {t: sum(1 for q in queries if q['type'] == t) for t in set(q['type'] for q in queries)})
print("샘플 3건:")
for q in queries[:3]:
    print(f"  [{q['type']}] {q['query']} → {q['gold_ids']}")