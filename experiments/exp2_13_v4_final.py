"""실험 2-13: v4 최종 규칙 — gold50 + 200건 전체 최종 집계.

v4 (확보 보호 추가):
  KNOWLEDGE(지식작업) 있으면 KEEP
  TRANSITION(결과→이제/다음) && OPERATION(실행작업) → SKIP
  INTENT(순수 진행 의지) → SKIP
gold50 검증: 회귀 0, FP 43% 감소 확인됨.
이 스크립트: 200건 전체 적용 집계 + 규칙 최종 문서화용 출력.
"""
import json
import re
from pathlib import Path

BASE = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\memory-classification-evaluation")

# ===== 최종 규칙 v4 =====
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
    if KNOWLEDGE.search(u[:200]):
        return False
    if TRANSITION.search(u) and OPERATION.search(u):
        return True
    if INTENT.search(u):
        return True
    return False

def main():
    # gold50 최종 확인
    rows = []
    with open(BASE / "data/ab_assistant_gold50_as.jsonl", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    comm_keep = [o for o in rows if o.get("jev_type") == "commitment" and o.get("jev_store") == "STORE"]
    skip = [o for o in comm_keep if rule_v4(o["utterance"])]
    regression = [o for o in skip if o.get("gold") == "STORE"]
    fp_caught = [o for o in skip if o.get("gold") == "NO_STORE"]
    fp_total = [o for o in comm_keep if o.get("gold") == "NO_STORE"]
    print("=" * 60)
    print("gold50 최종 검증")
    print("=" * 60)
    print(f"  commitment KEEP: {len(comm_keep)} (TP {len(comm_keep)-len(fp_total)} / FP {len(fp_total)})")
    print(f"  v4 추가 SKIP: {len(skip)}건")
    print(f"  회귀: {len(regression)}건  {'!!!' if regression else '(0 = 안전)'}")
    print(f"  FP 감소: {len(fp_caught)}/{len(fp_total)} ({len(fp_caught)/len(fp_total)*100:.0f}%)")

    # gold50 전체 (commitment 외)에도 적용해 회귀 확인 — G-AS 전체 재계산
    print("\n" + "=" * 60)
    print("gold50 전체 G-AS + v4 (commitment 외 영향)")
    print("=" * 60)
    g_before = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    g_after = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    for o in rows:
        gold_store = o.get("gold") == "STORE"
        keep_before = o.get("jev_store") == "STORE" and o.get("jev_type") != "context"
        if o.get("jev_type") == "commitment" and keep_before and rule_v4(o["utterance"]):
            keep_after = False
        else:
            keep_after = keep_before
        for d, keep in ((g_before, keep_before), (g_after, keep_after)):
            if keep and gold_store: d["tp"] += 1
            elif keep and not gold_store: d["fp"] += 1
            elif not keep and gold_store: d["fn"] += 1
            else: d["tn"] += 1
    def f1(d):
        p = d["tp"]/(d["tp"]+d["fp"]) if (d["tp"]+d["fp"]) else 0
        r = d["tp"]/(d["tp"]+d["fn"]) if (d["tp"]+d["fn"]) else 0
        return p, r, (2*p*r/(p+r) if (p+r) else 0)
    print(f"  G-AS 단독:     TP {g_before['tp']} FP {g_before['fp']} FN {g_before['fn']} TN {g_before['tn']}  P/R/F1 = {tuple(round(x,3) for x in f1(g_before))}")
    print(f"  G-AS + v4:     TP {g_after['tp']} FP {g_after['fp']} FN {g_after['fn']} TN {g_after['tn']}  P/R/F1 = {tuple(round(x,3) for x in f1(g_after))}")

    # 200건 적용 집계
    rows200 = []
    with open(BASE / "data/ab_assistant_classified.jsonl", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows200.append(json.loads(line))
    ck = [o for o in rows200 if o["jev"]["type"] == "commitment" and o["jev"]["store"] == "STORE"]
    sk200 = [o for o in ck if rule_v4(o["utterance"])]
    print("\n" + "=" * 60)
    print(f"200건 전체: commitment KEEP {len(ck)} → v4 SKIP {len(sk200)} ({len(sk200)/len(ck)*100:.0f}%)")
    print("=" * 60)
    for o in sk200:
        print(f"  [SKIP] [conf={o['jev']['store_confidence']:.2f}] {o['utterance'][:75]}")

    # 저장량 영향
    print(f"\n  저장량 감소: commitment KEEP {len(ck)}건 → {len(ck)-len(sk200)}건 (-{len(sk200)}건)")
    print(f"  전체 assistant 저장: 150건 → {150-len(sk200)}건 (G-AS KEEP 150 기준, commitment 추가 SKIP 반영)")

if __name__ == "__main__":
    main()