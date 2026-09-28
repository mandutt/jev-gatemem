"""v10 vs v10-EN (영어 지시문) A/B — 층화 샘플 400건 생성.

목적: JEV 지시문 언어가 분류 정확도에 미치는 영향 검증.
- v10: 한국어 지시문 + 한국어 예시 (기존)
- v10-EN: 영어 지시문 + 한국어 예시 (입력)
비교 지표: 14-type exact acc, store acc, NO_STORE 판정 변화.

층화: gold NO_STORE 200 + gold non-NO_STORE 200 (각 type 최대 40건씩 캡)
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