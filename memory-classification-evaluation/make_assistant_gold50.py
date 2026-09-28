"""assistant 발화 50건 gold(인간 판정) 추출 — 게이트 후보 정밀도 비교용.

- ab_assistant_classified.jsonl에서 무작위(시드 고정) 50건 추출
- 각 건: id, utterance, jev store/type/conf
- 출력: data/ab_assistant_gold50.jsonl (인간이 verdict 필드 채움)
"""
import json
import random
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "data" / "ab_assistant_classified.jsonl"
OUT = HERE / "data" / "ab_assistant_gold50.jsonl"

random.seed(42)
rows = [json.loads(l) for l in open(SRC, encoding="utf-8")]
sample = random.sample(rows, 50)

out_rows = []
for r in sample:
    out_rows.append({
        "id": r["id"],
        "utterance": r["utterance"],
        "jev_store": r["jev"].get("store"),
        "jev_type": r["jev"].get("type"),
        "jev_store_conf": r["jev"].get("store_confidence"),
        "jev_type_conf": r["jev"].get("type_confidence"),
        "gold_store": "",   # 인간 판정: STORE / NO_STORE
        "gold_type": "",    # 인간 판정: 위 type 후보 중 하나
    })

OUT.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in out_rows) + "\n", encoding="utf-8")
print(f"{len(out_rows)}건 -> {OUT}")
for r in out_rows:
    print(f"{r['id'][:8]} | {r['jev_store']}/{r['jev_type']} ({r['jev_store_conf']:.2f}) | {r['utterance'][:90]}")