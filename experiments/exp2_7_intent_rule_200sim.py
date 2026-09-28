"""실험 2-7: commitment 진행의지 규칙 — 200건 전체 시뮬레이션.

규칙 후보: G-AS KEEP(commitment & store==STORE) 중
  "진행 의지(~겠다|~할게)" 패턴 && "검증/확인 목적" 없음 → SKIP 추가

gold50에서: FP 7/7 매치, TP 6건 중 회귀는 "~겠다/할게" 포함 & 검증단어 부재 케이스만.
이 스크립트는 200건 전체로 규칙 적용 시:
  1) commitment KEEP 중 몇 건이 추가 SKIP되는가 (FP 감소 상한)
  2) 추가 SKIP 항목의 실제 내용 (TP 오손 위험 판단)
"""
import json
import re
from collections import Counter
from pathlib import Path

BASE = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\memory-classification-evaluation")

def main():
    rows = []
    with open(BASE / "data/ab_assistant_classified.jsonl", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))

    comm_keep = [o for o in rows if o["jev"]["type"] == "commitment" and o["jev"]["store"] == "STORE"]
    print(f"200건 중 commitment KEEP: {len(comm_keep)}건\n")

    pat_intent = re.compile(r"(겠다|할게|확인하겠다|조사하겠다|분석하겠다|살펴보겠다|해보겠다|돌릴게)")
    pat_verify = re.compile(r"(검증|확인|조사|분석|테스트|정밀|확정|검토)")

    # 규칙: 진행의지 && !검증목적 → SKIP
    skip = []
    keep = []
    for o in comm_keep:
        u = o["utterance"]
        if pat_intent.search(u) and not pat_verify.search(u):
            skip.append(o)
        else:
            keep.append(o)

    print(f"--- 규칙 적용 결과 ---")
    print(f"추가 SKIP: {len(skip)}건")
    print(f"유지 KEEP: {len(keep)}건")
    if skip:
        print(f"\n--- 추가 SKIP 항목 ({len(skip)}건) ---")
        for o in skip:
            print(f"  [conf={o['jev']['store_confidence']:.2f}] {o['utterance'][:85]}")
    if keep:
        print(f"\n--- 유지 KEEP 항목 ({len(keep)}건) ---")
        for o in keep:
            print(f"  [conf={o['jev']['store_confidence']:.2f}] {o['utterance'][:85]}")

if __name__ == "__main__":
    main()