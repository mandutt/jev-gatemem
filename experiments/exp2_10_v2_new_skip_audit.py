"""실험 2-10: v2 추가 SKIP 8건 중 gold50 미검증 4건의 TP 오손 위험 판정.

gold50 검증은 4건만 통과. 200건에서만 걸린 4건:
  - "확장 기능 로직 검증 완료. 다음 시나리오 A/B/C 판단과 함께 테스트베드 프로젝트 코드를 작성합니다."
  - "핵심 구조 파악: `session_start`에서 config에 따라 **4개 기능을 선택 등록**. 이제 각 기능의 `registerTool`/..."
이들이 실제로 FP인지 TP인지 (인간 판정에 가깝게) 분석.
"""
import json
import re
from pathlib import Path

BASE = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\memory-classification-evaluation")

def rule_v2(u: str) -> bool:
    intent = re.compile(
        r"(진행하겠|만들겠|구축하|정리하|작성하겠|등록하겠|돌릴게|할게|해볼게|적용하겠|시작하겠)"
    )
    verify_150 = re.compile(
        r"(검증|확인|조사|분석|테스트|정밀|확정|검토|추정|판단|파악|백업|계획|확보|설치|비가역)"
    )
    transition = re.compile(
        r"(정상|감지|동작|완료|완성|등록).{0,40}(이제|다음|그럼)"
    )
    if transition.search(u):
        return True
    if intent.search(u):
        head = u[:150]
        if not verify_150.search(head):
            return True
    return False

def main():
    rows = []
    with open(BASE / "data/ab_assistant_classified.jsonl", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))

    comm_keep = [o for o in rows if o["jev"]["type"] == "commitment" and o["jev"]["store"] == "STORE"]
    skip = [o for o in comm_keep if rule_v2(o["utterance"])]

    # gold50에 있는 (4건) = 이미 검증됨. gold50에 없는 신규 4건만 분석
    gold50_ids = set()
    with open(BASE / "data/ab_assistant_gold50_as.jsonl", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                gold50_ids.add(json.loads(line)["id"])

    new_skips = [o for o in skip if o["id"] not in gold50_ids]
    print(f"gold50 미검증 신규 SKIP: {len(new_skips)}건\n")
    for o in new_skips:
        print(f"id={o['id']} conf={o['jev']['store_confidence']:.2f}")
        print(f"  {o['utterance']}")
        print()

    # 규칙이 걸린 이유 출력 (어떤 패턴이 매치됐나)
    for o in new_skips:
        u = o["utterance"]
        reasons = []
        if re.search(r"(정상|감지|동작|완료|완성|등록).{0,40}(이제|다음|그럼)", u):
            reasons.append("transition")
        if re.search(r"(진행하겠|만들겠|구축하|정리하|작성하겠|등록하겠|돌릴게|할게|해볼게|적용하겠|시작하겠)", u):
            reasons.append("intent")
        print(f"  → 매치 이유: {reasons}")

if __name__ == "__main__":
    main()