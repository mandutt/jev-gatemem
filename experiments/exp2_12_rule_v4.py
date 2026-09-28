"""실험 2-12: v4 (보호 단어 계층화) — gold50 + 200건.

v3 실패 원인: VERIFY가 "백업"(실행작업, FP)까지 보호 → FP가 안 잡힘.
v4 설계:
  - KNOWLEDGE (TP 보호): 검증|확인|조사|분석|테스트|정밀|확정|검토|추정|판단|파악|실측|분해
    → 이 단어가 있으면 KEEP (지식 작업은 결과물)
  - OPERATION (FP 대상): 백업|설치|스왑|설정|복구|적용|구축|등록|이관|모니터링
    → 실행 작업의 "완료→이제"는 전형적 진행 전환 FP
  - intent(강화): 진행하겠|만들겠|구축하|정리하|작성하겠|등록하겠|돌릴게|할게|해볼게|적용하겠|시작하겠|세겠습니다
    → transition 없이 순수 진행 의지도 SKIP (단 KNOWLEDGE 없을 때)
"""
import json
import re
from pathlib import Path

BASE = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\memory-classification-evaluation")

KNOWLEDGE = re.compile(
    r"(검증|확인|조사|분석|테스트|정밀|확정|검토|추정|판단|파악|실측|분해|라이브|확보)"
)
OPERATION = re.compile(
    r"(백업|설치|스왑|설정|복구|적용|구축|등록|이관|모니터링|cron)"
)
TRANSITION = re.compile(
    r"(정상|감지|동작|완료|완성|등록|파악).{0,40}(이제|다음|그럼)"
)
INTENT = re.compile(
    r"(진행하겠|만들겠|구축하|정리하|작성하겠|등록하겠|돌릴게|할게|해볼게|적용하겠|시작하겠|세겠습니다|확인하겠다)"
)

def rule_v4(u: str) -> bool:
    # 지식 작업은 항상 보호
    if KNOWLEDGE.search(u[:200]):
        return False
    # 실행 작업 전환: "완료...이제" → SKIP (단, 지식 작업 아니면)
    if TRANSITION.search(u) and OPERATION.search(u):
        return True
    # 순수 진행 의지 → SKIP (지식 작업 아님)
    if INTENT.search(u):
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
    rows = load_gold50()
    comm_keep = [o for o in rows if o.get("jev_type") == "commitment" and o.get("jev_store") == "STORE"]
    skip = [o for o in comm_keep if rule_v4(o["utterance"])]
    regression = [o for o in skip if o.get("gold") == "STORE"]
    fp_caught = [o for o in skip if o.get("gold") == "NO_STORE"]
    fp_total = [o for o in comm_keep if o.get("gold") == "NO_STORE"]

    print(f"=== gold50: commitment KEEP {len(comm_keep)} (TP {len(comm_keep)-len(fp_total)}/FP {len(fp_total)}) ===")
    print(f"v4 SKIP {len(skip)}건: 회귀 {len(regression)}건, FP 감소 {len(fp_caught)}/{len(fp_total)} ({len(fp_caught)/len(fp_total)*100:.0f}%)")
    for o in skip:
        v = "FP ✓" if o.get("gold") == "NO_STORE" else "회귀!"
        print(f"  [{v}] {o['utterance'][:75]}")
    print("\n  남은 FP:")
    for o in fp_total:
        if o not in fp_caught:
            print(f"    [FP 남음] {o['utterance'][:75]}")

    rows200 = load_200()
    ck = [o for o in rows200 if o["jev"]["type"] == "commitment" and o["jev"]["store"] == "STORE"]
    sk200 = [o for o in ck if rule_v4(o["utterance"])]
    print(f"\n=== 200건: commitment KEEP {len(ck)} → v4 SKIP {len(sk200)} ({len(sk200)/len(ck)*100:.0f}%) ===")
    for o in sk200:
        print(f"  [SKIP] [conf={o['jev']['store_confidence']:.2f}] {o['utterance'][:80]}")
    print(f"\n  유지 KEEP {len(ck)-len(sk200)}건:")
    for o in ck:
        if o not in sk200:
            print(f"    [KEEP] [conf={o['jev']['store_confidence']:.2f}] {o['utterance'][:80]}")

if __name__ == "__main__":
    main()