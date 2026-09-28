"""실험 2-2: commitment FP 규칙 후보 — gold50 회귀 검증 + KEEP 감소율.

gold50: ab_assistant_gold50.json (STORE 31 / NO_STORE 19, 인간 판정)
규칙 후보: commitment 중 "완료 보고 + 다음 계획" (진행 전환) 형태만 SKIP 추가.
  - 핵심: 진짜 결과물(결과 보고)은 건드리지 않아야 함.
  - conservative 후보만 테스트: "진행하겠다/확인하겠다/조사하겠다"로 끝나는 순수 진행 선언 (결과 보고 없음)
"""
import json
import re
from pathlib import Path

BASE = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\memory-classification-evaluation")

def load(path):
    with open(BASE / path, encoding="utf-8") as f:
        return json.load(f)

def main():
    # gold50 구조 확인
    gold50 = load("data/ab_assistant_gold50.json")
    print(f"gold50 전체 {len(gold50)}건 (list면 첫 2개 출력)")
    if isinstance(gold50, list):
        print(json.dumps(gold50[0], ensure_ascii=False)[:200])
        print(json.dumps(gold50[1], ensure_ascii=False)[:200])
    elif isinstance(gold50, dict):
        print("dict keys:", list(gold50.keys())[:10])

    # 200건 commitment 재분석 — "순수 진행 선언" vs "결과 보고 포함"
    rows = []
    with open(BASE / "data/ab_assistant_classified.jsonl", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    comm_keep = [o for o in rows if o["jev"]["type"] == "commitment" and o["jev"]["store"] == "STORE"]

    # 후보 규칙 A: "~하겠다/확인하겠다/조사하겠다" 로 끝나는 순수 진행 (결과 보고 없음)
    pat_pure = re.compile(r"(하겠다|확인하겠다|조사하겠다|분석하겠다|살펴보겠다|해보겠다|돌릴게|할게|확인할게|조사할게)$")
    pat_has_result = re.compile(r"(완료|완성|등록|확인됨|검증|동작|성공|실패|감지|마무리|정리|확정|확보|파악|해결|수정|구축|작성)")

    a_hit, a_miss = [], []
    for o in comm_keep:
        u = o["utterance"].strip()
        if pat_pure.search(u):
            a_hit.append(o)
        else:
            a_miss.append(o)

    print(f"\n--- 후보 A (순수 진행 선언) — commitment KEEP 25건 중 {len(a_hit)}건 매치 ---")
    for o in a_hit:
        print(f"  [conf={o['jev']['store_confidence']:.2f}] {o['utterance'][:90]}")

    # 후보 B: "결과 보고 없이 순수 진행" & "결과 보고 + 진행" 구분
    b_hit = [o for o in comm_keep if not pat_has_result.search(o["utterance"])]
    print(f"\n--- 후보 B (결과 단어 없음) — {len(b_hit)}건 매치 ---")
    for o in b_hit:
        print(f"  [conf={o['jev']['store_confidence']:.2f}] {o['utterance'][:90]}")

if __name__ == "__main__":
    main()