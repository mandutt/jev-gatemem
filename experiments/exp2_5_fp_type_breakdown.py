"""실험 2-5: G-AS FP(gold=NO_STORE but KEEP) type 구성 분석.

gold50에서 G-AS KEEP/gold NO_STORE 10건의 실제 type이 무엇인지 확인.
→ commitment가 주범인지, 다른 type(context 외)이 주범인지 파악.
"""
import json
from collections import Counter
from pathlib import Path

BASE = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\memory-classification-evaluation")

def main():
    rows = []
    with open(BASE / "data/ab_assistant_gold50_as.jsonl", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))

    # G-AS KEEP = jev_store==STORE && jev_type!=context
    fps = [o for o in rows if o.get("jev_store") == "STORE"
           and o.get("jev_type") != "context"
           and o.get("gold") == "NO_STORE"]
    print(f"G-AS KEEP / gold NO_STORE (FP): {len(fps)}건\n")

    # type 분포
    type_cnt = Counter(o.get("jev_type") for o in fps)
    print("--- FP type 분포 ---")
    for t, n in type_cnt.most_common():
        print(f"  {t}: {n}")

    # 전체 출력
    print("\n--- FP 전체 목록 ---")
    for o in fps:
        print(f"  [{o.get('jev_type')}/{o.get('jev_store_conf'):.2f}] {o['utterance'][:80]}")

    # TP (gold=STORE, KEEP)도 같이 봐서 균형 확인
    tps = [o for o in rows if o.get("jev_store") == "STORE"
           and o.get("jev_type") != "context"
           and o.get("gold") == "STORE"]
    print(f"\n--- TP (KEEP/gold STORE): {len(tps)}건 type 분포 ---")
    for t, n in Counter(o.get("jev_type") for o in tps).most_common():
        print(f"  {t}: {n}")

if __name__ == "__main__":
    main()