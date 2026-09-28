"""실험 2-8: 최종 규칙 후보 — gold50 정밀 회귀 검증.

규칙 (G-AS commitment 추가 필터):
  commitment & store==STORE & 진행의지(~겠다|할게) & !검증목적(검증|확인|조사|분석|테스트) → SKIP

gold50 기준:
  - 회귀: gold=STORE인 commitment가 SKIP되면 안 됨
  - FP 감소: gold=NO_STORE인 commitment KEEP이 SKIP되면 FP 감소
"""
import json
import re
from pathlib import Path

BASE = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\memory-classification-evaluation")

def rule_skip(u: str) -> bool:
    pat_intent = re.compile(r"(겠다|할게|확인하겠다|조사하겠다|분석하겠다|살펴보겠다|해보겠다|돌릴게)")
    pat_verify = re.compile(r"(검증|확인|조사|분석|테스트|정밀|확정|검토)")
    return bool(pat_intent.search(u) and not pat_verify.search(u))

def main():
    rows = []
    with open(BASE / "data/ab_assistant_gold50_as.jsonl", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))

    comm_keep = [o for o in rows if o.get("jev_type") == "commitment" and o.get("jev_store") == "STORE"]
    print(f"gold50 commitment KEEP: {len(comm_keep)}건 (TP {sum(1 for o in comm_keep if o['gold']=='STORE')} / FP {sum(1 for o in comm_keep if o['gold']=='NO_STORE')})\n")

    skip_by_rule = [o for o in comm_keep if rule_skip(o["utterance"])]
    print(f"규칙 추가 SKIP: {len(skip_by_rule)}건")
    for o in skip_by_rule:
        v = "FP 감소 ✓" if o.get("gold") == "NO_STORE" else "*** 회귀! ***"
        print(f"  [{v}] [gold={o.get('gold')}] {o['utterance'][:80]}")

    regression = [o for o in skip_by_rule if o.get("gold") == "STORE"]
    fp_caught = [o for o in skip_by_rule if o.get("gold") == "NO_STORE"]
    fp_total = [o for o in comm_keep if o.get("gold") == "NO_STORE"]
    print(f"\n>>> 회귀: {len(regression)}건 (0이어야 함)")
    print(f">>> FP 감소: {len(fp_caught)}/{len(fp_total)}건")
    if fp_total:
        print(f">>> FP 감소율: {len(fp_caught)/len(fp_total)*100:.0f}%")

if __name__ == "__main__":
    main()