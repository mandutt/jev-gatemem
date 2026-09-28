"""실험 2-6: commitment TP vs FP 구분 특징 분석.

gold50에서 commitment type:
  - TP (gold=STORE, KEEP)
  - FP (gold=NO_STORE, KEEP)
두 그룹의 언어적 특징을 비교해 규칙으로 분리 가능한 신호 탐색.
"""
import json
import re
from collections import Counter
from pathlib import Path

BASE = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\memory-classification-evaluation")

def main():
    rows = []
    with open(BASE / "data/ab_assistant_gold50_as.jsonl", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))

    comm = [o for o in rows if o.get("jev_type") == "commitment" and o.get("jev_store") == "STORE"]
    tp = [o for o in comm if o.get("gold") == "STORE"]
    fp = [o for o in comm if o.get("gold") == "NO_STORE"]

    print(f"commitment KEEP: TP {len(tp)} / FP {len(fp)}\n")

    # 특징: "완료/이제" (결과+계획), "~겠다" (의지), 길이, 질문형, 특정 접두사
    features = {
        "결과+계획 (완료|완성|등록|확인.*이제|완료.*이제)": r"(완료|완성|등록|정상).{0,20}(이제|다음|그럼)",
        "결과 보고 (완료|완성|등록|확인됨|동작)": r"(완료|완성|등록|확인됨|정상|동작|감지)",
        "진행 의지 (~겠다|~할게)": r"(겠다|할게|확인하겠다)",
        "검증/확인 목적 (검증|확인|조사)": r"(검증|확인|조사|분석)",
        "약속 순서 (먼저|우선|①|순서)": r"(먼저|우선|①|순서|차례)",
        "비가역/위험 (백업|비가역|위험)": r"(백업|비가역|위험|설치|스왑)",
        "질문형 (?|요)": r"[?？]|요\.$",
        "첫 단어 가정/추정 (아마|것 같|추정|판단|필요)": r"(것 같|추정|필요|가능|아마)",
    }

    print("--- 특징별 TP/FP 매치율 ---")
    for name, pat in features.items():
        rx = re.compile(pat)
        tp_n = sum(1 for o in tp if rx.search(o["utterance"]))
        fp_n = sum(1 for o in fp if rx.search(o["utterance"]))
        gap = (tp_n / len(tp) - fp_n / len(fp)) if tp and fp else 0
        print(f"  {name:<40} TP {tp_n}/{len(tp)}  FP {fp_n}/{len(fp)}  (Δ {gap:+.2f})")

    # TP/FP 전체 문장 출력 (수동 패턴 발견용)
    print("\n--- TP commitment ---")
    for o in tp:
        print(f"  {o['utterance'][:100]}")
    print("\n--- FP commitment ---")
    for o in fp:
        print(f"  {o['utterance'][:100]}")

if __name__ == "__main__":
    main()