"""P8 vs P10 언어 A/B — 지시문 언어 영향 측정용 층화 샘플 생성.

목적: P10 vs P10-EN (영어 지시문) 비교.
- P10: 한국어 지시문 + 한국어 예시
- P10-EN: 영어 지시문 + 한국어 예시
실측 결과: 일치 97%, 차이 노이즈 수준 — 한국어 지시(P8) 유지 확정.
"""
import json
import random
from collections import Counter, defaultdict

random.seed(42)

rows = [json.loads(l) for l in open("JEV_ALL1975_V8.jsonl", encoding="utf-8")]
print(f"total rows: {len(rows)}")

no_store = [r for r in rows if r["gold_type"] == "NO_STORE"]
store = [r for r in rows if r["gold_type"] != "NO_STORE"]
print(f"gold NO_STORE: {len(no_store)}, gold store: {len(store)}")

# store 쪽: type별 캡 40 (13종 → 최대 520, 실제는 200 목표)
by_type = defaultdict(list)
for r in store:
    by_type[r["gold_type"]].append(r)

sample_store = []
for t, rs in sorted(by_type.items(), key=lambda x: -len(x[1])):
    take = rs[: min(40, len(rs))]
    sample_store.extend(take)
    # 200 채우면 중단
    if len(sample_store) >= 200:
        break
sample_store = sample_store[:200]

# NO_STORE 쪽: 랜덤 200
sample_no_store = random.sample(no_store, 200)

sample = sample_no_store + sample_store
random.shuffle(sample)
print(f"sample: {len(sample)} (NO_STORE {sum(1 for r in sample if r['gold_type']=='NO_STORE')} / store {sum(1 for r in sample if r['gold_type']!='NO_STORE')})")

# 출력: utterance + gold만 (id는 유지)
out = []
for r in sample:
    out.append({
        "id": r["id"],
        "utterance": r["utterance"],
        "gold_type": r["gold_type"],
        "gold_should_store": r["gold_should_store"],
    })
with open("data/v10_lang_ab_sample.jsonl", "w", encoding="utf-8") as f:
    for o in out:
        f.write(json.dumps(o, ensure_ascii=False) + "\n")
print("written: data/v10_lang_ab_sample.jsonl")