"""실험 2-9: 규칙 v2 (강화) — gold50 회귀 + 200건 시뮬레이션.

v1 (채택 후보): intent(겠다|할게...) && !verify(검증|확인|조사|분석|테스트...) → SKIP
  → FP 3/7 (43%), 회귀 0

v2 (강화) 전략:
  1. intent를 "태스크 진행 의지"로 좁힘: 진행하겠|만들겠|구축하|정리하|작성하겠|등록하겠|돌릴게|할게|해볼게|적용하겠
     - "확인하겠다/조사하겠다" (지식 작업) 제외 → TP 5("deepcombo...확인하겠다") 보호
  2. verify를 "첫 문장(150자)"으로 제한 + 결과/계획 단어 추가:
     검증|확인|조사|분석|테스트|정밀|확정|검토|추정|판단|파악|백업|계획|확보|설치|비가역
     - "④ ... 검증까지 한 번에"(문장 끝)가 첫 문장에 안 걸리도록 → FP 4("진행할게") 포획
     - "설정"은 verify에서 제외 (FP 4의 "① allow-remote=all 설정" 방어 무력화), "설치"는 유지 (TP 4 보호)
  3. transition 추가: (정상|감지|동작|완료|완성|등록).{0,40}(이제|다음|그럼) → SKIP
     - "모니터가 정상 작동...이제" FP 2 포획
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

def load_gold50():
    rows = []
    with open(BASE / "data/ab_assistant_gold50_as.jsonl", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows

def load_200():
    rows = []
    with open(BASE / "data/ab_assistant_classified.jsonl", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows

def main():
    # 1) gold50 검증
    rows = load_gold50()
    comm_keep = [o for o in rows if o.get("jev_type") == "commitment" and o.get("jev_store") == "STORE"]
    skip = [o for o in comm_keep if rule_v2(o["utterance"])]
    regression = [o for o in skip if o.get("gold") == "STORE"]
    fp_caught = [o for o in skip if o.get("gold") == "NO_STORE"]
    fp_total = [o for o in comm_keep if o.get("gold") == "NO_STORE"]

    print(f"=== gold50 검증 ===")
    print(f"commitment KEEP {len(comm_keep)}건 (TP {len(comm_keep)-len(fp_total)} / FP {len(fp_total)})")
    print(f"v2 추가 SKIP: {len(skip)}건")
    print(f"  회귀: {len(regression)}건  {'*** 회귀 발생 ***' if regression else '(0 = OK)'}")
    print(f"  FP 감소: {len(fp_caught)}/{len(fp_total)}건 ({len(fp_caught)/len(fp_total)*100:.0f}%)")
    for o in skip:
        v = "FP ✓" if o.get("gold") == "NO_STORE" else "회귀!"
        print(f"    [{v}] {o['utterance'][:70]}")
    print(f"\n  남은 FP (못 잡음):")
    for o in fp_total:
        if o not in fp_caught:
            print(f"    [FP 남음] {o['utterance'][:70]}")

    # 2) 200건 시뮬레이션
    print(f"\n=== 200건 시뮬레이션 ===")
    rows200 = load_200()
    comm_keep200 = [o for o in rows200 if o["jev"]["type"] == "commitment" and o["jev"]["store"] == "STORE"]
    skip200 = [o for o in comm_keep200 if rule_v2(o["utterance"])]
    print(f"commitment KEEP {len(comm_keep200)}건 → v2 추가 SKIP {len(skip200)}건 ({len(skip200)/len(comm_keep200)*100:.0f}%)")
    for o in skip200:
        print(f"    [SKIP] [conf={o['jev']['store_confidence']:.2f}] {o['utterance'][:80]}")

    # 남은 KEEP (v2가 못 잡은, TP 오손 위험 검토용)
    print(f"\n  유지 KEEP {len(comm_keep200)-len(skip200)}건:")
    for o in comm_keep200:
        if o not in skip200:
            print(f"    [KEEP] [conf={o['jev']['store_confidence']:.2f}] {o['utterance'][:80]}")

if __name__ == "__main__":
    main()