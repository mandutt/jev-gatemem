# -*- coding: utf-8 -*-
"""pinned slots 후보 — 0콜 사전 검증 (2026-10-09)

목적: '검색 풀에서 규칙/선호형 행을 제외'하면 현재 정답 회수가 망가지는지 확인.
- op-90 gold 중 '규칙/선호형 행이 gold인 쿼리' = 슬롯화 시 손실되는 답변 (회귀 위험)
- recall 상위 규칙 행이 gold인 쿼리 → 그 행을 풀에서 빼면 hit@1 불가

방법:
1) active 1,926행에서 지속 규칙/선호형(슬롯 후보) 식별
2) stage87 op-90 gold_id가 슬롯 후보에 속하는지 대조 (stage87 raw의 gold_rank)
3) 추정: 슬롯 후보 gold 의존 쿼리 수 + recall 상위 규칙 행 의존 수
"""
import sqlite3, json, re, os
from collections import Counter

DB = r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db"
REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 1) 슬롯 후보 (지속 규칙/선호) 식별
sust_q = re.compile(r"(금지|금지사항|원칙|규칙|통일|항상|never|always|~해야|~하지|선호|원함|필수|유지|제한|사용자의|사용자 제약|프로필에서만|관례|convention|governance|policy)", re.I)
rows = cur.execute("""
    SELECT id, content, memory_type, recall_count FROM working_memory
    WHERE superseded_by IS NULL AND (valid_until IS NULL OR valid_until > '2026-10-09')
""").fetchall()
slot_ids = set()
slot_rows = []
for r in rows:
    body = re.sub(r"^\[(USER|ASSISTANT|SYSTEM)\] ?", "", r['content'] or "").strip()
    if sust_q.search(body) or r['memory_type'] in ("instruction", "preference"):
        slot_ids.add(r['id'])
        slot_rows.append(r)
print(f"슬롯 후보: {len(slot_ids)} / {len(rows)}")

# 핵심 후보 = recall 상위 규칙 행 (상시 주입 대상)
core = sorted(slot_rows, key=lambda r: -(r['recall_count'] or 0))[:20]
core_ids = set(r['id'] for r in core)
print(f"핵심 후보(recall top20): {len(core)}")

# 2) stage87 op-90 gold 대조
s87 = json.load(open(os.path.join(REPO, "experiments/operational-golden/data/stage87_exposure_k.json"), encoding="utf-8"))
op87 = s87["k5"]["op"]
# stage87 raw에는 gold_id가 없음 — stage45 snapshot에서 gold_id 매핑
d45 = json.load(open(os.path.join(REPO, "experiments/operational-golden/data/stage45_abstain_label_snapshot.json"), encoding="utf-8"))
op45 = [(r["query"], r["gold_id"]) for r in d45["runs"][0]["records"] if r.get("grp") == "op"]
print(f"op-90 쿼리: {len(op45)}")

gold_slot = 0
gold_core = 0
gold_slot_queries = []
for q, g in op45:
    g16 = (g or "")[:16]
    if any(x[:16] == g16 for x in slot_ids):
        gold_slot += 1
        gold_slot_queries.append(q)
    if any(x[:16] == g16 for x in core_ids):
        gold_core += 1
print(f"\nop-90 gold가 슬롯 후보 행: {gold_slot} / 90")
print(f"op-90 gold가 핵심 후보(recall top20) 행: {gold_core} / 90")
print("슬롯 gold 쿼리:")
for q in gold_slot_queries:
    print(f"  {q[:80]}")

# 3) recall 상위 규칙 행 id show
print("\n핵심 후보(recall top 20):")
for r in core:
    print(f"  rc={r['recall_count']} [{r['memory_type']}] {r['id'][:12]} | {re.sub(chr(10),' ',r['content'])[:70]}")
conn.close()