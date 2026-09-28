"""실험 1: P11-a 시뮬레이션 — type 주입이 store 판정에 미치는 효과 측정.

기존 JEV P8 결과(JEV_ALL1975_V8.jsonl)를 재사용.
G-qual은 이미 type 이중확인 구조. 여기서는:
  A) P8 단독 (store만 사용, conf 무관)        — baseline
  B) G-qual (현행 게이트: store/type 이중확인)  — 현행
  C) type 우선 (type이 저장타입이면 무조건 KEEP, 아니면 store 판정) — P11-a를 규칙으로 근사
  D) P11-a (실제 type 주입)는 JEV 재호출 필요 → 여기선 C로 근사하고,
     P11-a 데이터(p11_a_raw.jsonl)가 있으면 별도로 교차 확인

측정: gold store recall / precision / F1 / 과다저장 / 누락
"""
import json
import sys
from collections import Counter
from pathlib import Path

BASE = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\memory-classification-evaluation")

# 저장타입 정의 (G-qual 문서 기준: NO_STORE만 아니면 저장타입)
NON_STORE_TYPES = {"NO_STORE"}

def load_p8():
    rows = {}
    with open(BASE / "JEV_ALL1975_V8.jsonl", encoding="utf-8") as f:
        for line in f:
            o = json.loads(line)
            rows[o["id"]] = o
    return rows

def load_gold():
    gold = {}
    with open(BASE / "ALL1975.jsonl", encoding="utf-8") as f:
        for line in f:
            o = json.loads(line)
            gold[o["id"]] = o
    return gold

def metrics(pred_keep, gold_keep):
    """pred_keep/gold_keep: set of ids"""
    tp = len(pred_keep & gold_keep)
    fp = len(pred_keep - gold_keep)
    fn = len(gold_keep - pred_keep)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"keep": len(pred_keep), "tp": tp, "fp": fp, "fn": fn,
            "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}

def main():
    p8 = load_p8()
    gold = load_gold()
    gold_keep = {i for i, o in gold.items() if o["should_store"]}
    print(f"총 {len(gold)}건, gold store {len(gold_keep)}건 / no-store {len(gold)-len(gold_keep)}건\n")

    # A) P8 store 단독 (store==STORE → KEEP)
    a_keep = {i for i, o in p8.items() if o["store"] == "STORE"}

    # B) G-qual (현행): store==STORE → KEEP; store==NO_STORE && type!=NO_STORE → KEEP;
    #    store==NO_STORE && type==NO_STORE && conf<0.6 → KEEP; conf>=0.6 → SKIP
    b_keep = set()
    for i, o in p8.items():
        if o["store"] == "STORE":
            b_keep.add(i)
        elif o["type"] != "NO_STORE":
            b_keep.add(i)
        elif o["store_confidence"] < 0.6:
            b_keep.add(i)

    # C) type 우선 (P11-a 근사): type이 저장타입이면 KEEP, 아니면 store 판정
    c_keep = set()
    for i, o in p8.items():
        if o["type"] != "NO_STORE":
            c_keep.add(i)
        elif o["store"] == "STORE":
            c_keep.add(i)

    # D) G-qual2 (conf 무관): store==STORE → KEEP; type!=NO_STORE → KEEP
    d_keep = set()
    for i, o in p8.items():
        if o["store"] == "STORE" or o["type"] != "NO_STORE":
            d_keep.add(i)

    print("=" * 70)
    print(f"{'게이트':<28}{'keep':>6}{'TP':>5}{'FP':>5}{'FN':>5}{'P':>8}{'R':>8}{'F1':>8}")
    print("-" * 70)
    for name, keep in [("A) P8 store 단독", a_keep),
                       ("B) G-qual (현행)", b_keep),
                       ("C) type 우선 근사", c_keep),
                       ("D) G-qual2 (conf무관)", d_keep)]:
        m = metrics(keep, gold_keep)
        print(f"{name:<28}{m['keep']:>6}{m['tp']:>5}{m['fp']:>5}{m['fn']:>5}"
              f"{m['precision']:>8.4f}{m['recall']:>8.4f}{m['f1']:>8.4f}")

    # B와 C의 차이 분석 (실질적 개선 여지)
    print("\n--- B(G-qual) vs C(type 우선) 차이 ---")
    b_only = b_keep - c_keep
    c_only = c_keep - b_keep
    print(f"B에서만 KEEP (C는 SKIP): {len(b_only)}건")
    print(f"C에서만 KEEP (B는 SKIP): {len(c_only)}건")
    
    # 각 차이의 gold 정답률
    b_only_gold = sum(1 for i in b_only if i in gold_keep)
    c_only_gold = sum(1 for i in c_only if i in gold_keep)
    print(f"  B-only 중 gold store: {b_only_gold}/{len(b_only)}")
    print(f"  C-only 중 gold store: {c_only_gold}/{len(c_only)}")
    if c_only:
        print("\n  C-only 샘플 (type 저장타입 but store=NO_STORE & conf>=0.6):")
        for i in list(c_only)[:10]:
            o = p8[i]
            g = gold[i]
            print(f"    [{g['gold_type']}/{g['should_store']}] {o['utterance'][:60]} "
                  f"(store={o['store']}/{o['store_confidence']:.2f} type={o['type']}/{o['type_confidence']:.2f})")

    # C의 FP (과다저장) 유형 분석
    c_fp = c_keep - gold_keep
    print(f"\n--- C 과다저장(FP) {len(c_fp)}건 type 분포 ---")
    fp_types = Counter(p8[i]["type"] for i in c_fp)
    for t, n in fp_types.most_common():
        print(f"  {t}: {n}")

    # B의 FN (누락) 유형 분석
    b_fn = gold_keep - b_keep
    print(f"\n--- B 누락(FN) {len(b_fn)}건 gold_type 분포 ---")
    fn_types = Counter(gold[i]["gold_type"] for i in b_fn)
    for t, n in fn_types.most_common():
        print(f"  {t}: {n}")
    print("\n  B 누락 샘플:")
    for i in list(b_fn)[:10]:
        g = gold[i]
        o = p8[i]
        print(f"    [{g['gold_type']}] {o['utterance'][:70]} "
              f"(store={o['store']}/{o['store_confidence']:.2f} type={o['type']}/{o['type_confidence']:.2f})")

    return {"A": metrics(a_keep, gold_keep), "B": metrics(b_keep, gold_keep),
            "C": metrics(c_keep, gold_keep), "D": metrics(d_keep, gold_keep)}

if __name__ == "__main__":
    main()