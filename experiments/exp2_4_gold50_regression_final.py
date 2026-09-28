"""실험 2-4: gold50 회귀 검증 (정확판).

gold50 = ab_assistant_gold50_as.jsonl (50건, gold 필드 = 인간 STORE/NO_STORE)
규칙 후보: commitment KEEP 중 "순수 진행 선언" (결과 보고 없음) → 추가 SKIP
검증 기준:
  - 회귀 0: gold=STORE인 commitment가 규칙에 걸리면 안 됨
  - 효과: gold=NO_STORE인 commitment KEEP이 규칙에 걸리면 FP 감소
"""
import json
import re
from pathlib import Path

BASE = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\memory-classification-evaluation")

def main():
    rows = []
    with open(BASE / "data/ab_assistant_gold50_as.jsonl", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if line.strip():
                rows.append(json.loads(line))

    print(f"gold50 {len(rows)}건\n")

    # 1) commitment로 분류된 gold50 항목
    comm = [o for o in rows if o.get("jev_type") == "commitment"]
    print(f"--- gold50 중 commitment: {len(comm)}건 ---")
    for o in comm:
        print(f"  [gold={o.get('gold')}] [jev_store={o.get('jev_store')}] {o['utterance'][:70]}")

    # 2) G-AS 규칙 적용 (jev_as 기준이 아니라 P8 jev 기준으로 G-AS 평가)
    #    G-AS: store==STORE && type!=context → KEEP
    print("\n--- G-AS 기준 KEEP/SKIP + gold 판정 대조 ---")
    from collections import Counter
    conf = Counter()
    for o in rows:
        store = o.get("jev_store")
        mtype = o.get("jev_type")
        gold = o.get("gold")
        keep = (store == "STORE" and mtype != "context")
        conf[(keep, gold)] += 1
    for (keep, gold), n in sorted(conf.items()):
        print(f"  G-AS {'KEEP' if keep else 'SKIP'} / gold {gold}: {n}건")

    # 3) 규칙 후보: 순수 진행 선언 (결과 단어 없음 && 진행 단어 있음)
    pat_pure = re.compile(
        r"(하겠다|확인하겠다|조사하겠다|분석하겠다|살펴보겠다|해보겠다|돌릴게|할게|확인할게|조사할게|확인한다|조사한다|분석한다)$"
    )
    pat_result = re.compile(
        r"(완료|완성|등록|확인됨|검증|동작|성공|실패|감지|마무리|정리|확정|확보|파악|해결|수정|구축|작성|실측|설치|스왑)"
    )

    hit = []
    for o in rows:
        u = o["utterance"].strip()
        if o.get("jev_type") == "commitment" and o.get("jev_store") == "STORE":
            if pat_pure.search(u) and not pat_result.search(u):
                hit.append(o)

    print(f"\n--- 규칙 후보 매치 (commitment KEEP ∩ 순수진행 ∩ 결과단어없음): {len(hit)}건 ---")
    for o in hit:
        verdict = "회귀!" if o.get("gold") == "STORE" else "FP감소 ✓"
        print(f"  [{verdict}] [gold={o.get('gold')}] {o['utterance'][:75]}")

    # 회귀 카운트
    regression = [o for o in hit if o.get("gold") == "STORE"]
    print(f"\n>>> 회귀(규칙이 gold=STORE를 SKIP): {len(regression)}건")
    print(f">>> FP 감소 후보(규칙이 gold=NO_STORE를 SKIP): {len(hit) - len(regression)}건")

if __name__ == "__main__":
    main()