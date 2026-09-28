"""실험 2: commitment FP 규칙 — "진행 전환 문장" 필터 설계 데이터 분석.

데이터: ab_assistant_classified.jsonl (실제 assistant 발화 200건, P8 분류 결과)
목표:
  1. commitment로 분류된 항목 추출 → 실제 KEEP 가치가 있는지 분석
  2. "X 완료. 이제 Y 하겠다" 진행 전환 신호 패턴 식별
  3. 규칙 후보 제안 (gold50 기준 회귀 0 목표)
"""
import json
import re
from collections import Counter
from pathlib import Path

BASE = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\memory-classification-evaluation")

def load(path):
    rows = []
    with open(BASE / path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows

def main():
    rows = load("data/ab_assistant_classified.jsonl")
    print(f"총 {len(rows)}건")

    # 전체 type 분포
    types = Counter(o["jev"]["type"] for o in rows)
    print("\n--- 200건 type 분포 ---")
    for t, n in types.most_common():
        print(f"  {t}: {n}")

    # commitment만 추출
    comm = [o for o in rows if o["jev"]["type"] == "commitment"]
    print(f"\n--- commitment {len(comm)}건 ---")
    
    # G-AS 규칙 적용: store==STORE && type!=context → KEEP
    # commitment는 type!=context 이므로 store==STORE면 KEEP
    comm_keep = [o for o in comm if o["jev"]["store"] == "STORE"]
    comm_skip = [o for o in comm if o["jev"]["store"] != "STORE"]
    print(f"G-AS 기준: KEEP {len(comm_keep)} / SKIP {len(comm_skip)}")

    # 진행 전환 신호 후보 패턴
    patterns = {
        "이제...겠다/할게": r"이제.*(겠다|할게|할게요|해볼게|시작)",
        "완료/끝 + 이제/다음": r"(완료|끝났|끝|마무리|정리).*(이제|다음|그럼)",
        "~겠다 (의지)": r"겠다",
        "~할게 (약속)": r"할게",
        "조사/확인 시작": r"(조사|확인|점검|살펴|분석|테스트).*(하겠다|할게|시작)",
        "먼저/우선": r"(먼저|우선)",
        "진행하겠다": r"(진행|계속).*(하겠다|할게)",
    }

    print("\n--- commitment KEEP {len(comm_keep)}건 패턴 매치 ---")
    for name, pat in patterns.items():
        rx = re.compile(pat)
        matched = [o for o in comm_keep if rx.search(o["utterance"])]
        print(f"  {name}: {len(matched)}/{len(comm_keep)}")

    # KEEP commitment 전체 출력 (패턴 분석용)
    print("\n--- commitment KEEP 전체 (store=STORE) ---")
    for o in comm_keep:
        print(f"  [conf={o['jev']['store_confidence']:.2f}] {o['utterance'][:90]}")

    print("\n--- commitment SKIP 전체 (store=NO_STORE) ---")
    for o in comm_skip:
        print(f"  [conf={o['jev']['store_confidence']:.2f}] {o['utterance'][:90]}")

if __name__ == "__main__":
    main()