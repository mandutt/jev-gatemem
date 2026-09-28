"""실험 2-11: v3 (transition에 verify 보호 추가) — gold50 + 200건 재검증.

v2 문제: transition(결과→이제/다음)이 verify(검증|확인|조사...) 무시 → 
  "검증 완료. 다음 ... 작성합니다"(TP 후보)가 걸림.
v3: transition && !verify(보호단어) → SKIP
"""
import json
import re
from pathlib import Path

BASE = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\memory-classification-evaluation")

VERIFY = re.compile(
    r"(검증|확인|조사|분석|테스트|정밀|확정|검토|추정|판단|파악|백업|계획|확보|설치|비가역)"
)
INTENT = re.compile(
    r"(진행하겠|만들겠|구축하|정리하|작성하겠|등록하겠|돌릴게|할게|해볼게|적용하겠|시작하겠)"
)
TRANSITION = re.compile(
    r"(정상|감지|동작|완료|완성|등록|파악).{0,40}(이제|다음|그럼)"
)

def rule_v3(u: str) -> bool:
    if TRANSITION.search(u) and not VERIFY.search(u[:200]):
        return True
    if INTENT.search(u):
        if not VERIFY.search(u[:150]):
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
    skip = [o for o in comm_keep if rule_v3(o["utterance"])]
    regression = [o for o in skip if o.get("gold") == "STORE"]
    fp_caught = [o for o in skip if o.get("gold") == "NO_STORE"]
    fp_total = [o for o in comm_keep if o.get("gold") == "NO_STORE"]

    print(f"=== gold50: commitment KEEP {len(comm_keep)} (TP {len(comm_keep)-len(fp_total)}/FP {len(fp_total)}) ===")
    print(f"v3 SKIP {len(skip)}건: 회귀 {len(regression)}건, FP 감소 {len(fp_caught)}/{len(fp_total)} ({len(fp_caught)/len(fp_total)*100:.0f}%)")
    for o in skip:
        v = "FP ✓" if o.get("gold") == "NO_STORE" else "회귀!"
        print(f"  [{v}] {o['utterance'][:70]}")

    print("\n  남은 FP:")
    for o in fp_total:
        if o not in fp_caught:
            print(f"    [FP 남음] {o['utterance'][:70]}")

    # 200건
    rows200 = load_200()
    ck = [o for o in rows200 if o["jev"]["type"] == "commitment" and o["jev"]["store"] == "STORE"]
    sk200 = [o for o in ck if rule_v3(o["utterance"])]
    print(f"\n=== 200건: commitment KEEP {len(ck)} → v3 추가 SKIP {len(sk200)}건 ({len(sk200)/len(ck)*100:.0f}%) ===")
    for o in sk200:
        print(f"  [SKIP] [conf={o['jev']['store_confidence']:.2f}] {o['utterance'][:80]}")
    print(f"\n  유지 KEEP {len(ck)-len(sk200)}건 (TP 후보, 오손 방지 확인):")
    for o in ck:
        if o not in sk200:
            print(f"    [KEEP] [conf={o['jev']['store_confidence']:.2f}] {o['utterance'][:80]}")

if __name__ == "__main__":
    main()