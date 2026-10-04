"""실측: fit 피드백 루프 — gold50 라벨-결정 쌍으로 G-AS conf 임계 스윕 (0 JEV 콜)

목적 (fit 도입 가능성 실측):
  gold50 (사람 gold + JEV 판정 쌍)에서 현재 G-AS 규칙을 replay하고,
  conf 하한(0.40/0.45/0.50/0.55/0.60/0.65/0.70)을 스윕하여
  '유실 0 유지 + 노이즈(FP) 최소화'가 동시에 가능한지 오프라인 파레토 확인.

규칙 (gate_keep 기준, reference/evaluation-datasets.md full-gate replay):
  jev_store == STORE and jev_type != context  → KEEP (commitment 필터는 이미 gold50 반영)
  그 외 → SKIP
  파생 규칙(후보): KEEP 대신 (jev_store_conf or jev_type_conf) >= tau 추가.

라벨: gold==STORE → KEEP가 정답. gold==NO_STORE → SKIP가 정답.
지표: KEEP 유지율(gold STORE 중 KEEP), FP(gold NO_STORE 중 KEEP), 유실률(gold STORE 중 SKIP).
판정: 유실 0 (또는 baseline 이하) 유지 + FP 감소 시에만 fit 채택 후보.

gold50 배치: getattr(jev_as, 'batch', 0) — 0이 아니면 배치-상대적 → 스윕 무효 선언.
"""
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
GOLD = os.path.join(ROOT, "memory-classification-evaluation", "data", "ab_assistant_gold50_as.jsonl")

def load_gold():
    rows = []
    with open(GOLD, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            rows.append(d)
    return rows

def gate_keep(r):
    """현재 G-AS 규칙 replay — gold50에 이미 적용된 형태 그대로."""
    j_store = (r.get("jev_store") or "").upper()
    j_type = (r.get("jev_type") or "").upper()
    if j_store == "STORE" and j_type != "CONTEXT":
        return True
    return False

def main():
    rows = load_gold()
    print(f"gold50 rows: {len(rows)}")

    # gold 필드 분포 + id 중복 확인
    gold_vals = {}
    for r in rows:
        gold_vals[r["gold"]] = gold_vals.get(r["gold"], 0) + 1
    print("gold 분포:", gold_vals)
    ids = [r["id"] for r in rows]
    print("고유 id:", len(set(ids)), " 중복:", len(ids) - len(set(ids)))

    # 배치-상대성 확인
    has_batch = [r for r in rows if getattr(r.get("jev_as", {}), "batch", 0)]
    print("jev_as.batch 존재:", len(has_batch), "→", "스윕 무효" if has_batch else "스윕 유효")

    # baseline (현재 규칙)
    base_keep = sum(1 for r in rows if gate_keep(r))
    base_fp = sum(1 for r in rows if gate_keep(r) and r["gold"].upper() == "NO_STORE")
    base_lost = sum(1 for r in rows if not gate_keep(r) and r["gold"].upper() == "STORE")
    n_gold_keep = sum(1 for r in rows if r["gold"].upper() == "STORE")
    n_gold_nostore = sum(1 for r in rows if r["gold"].upper() == "NO_STORE")
    print(f"\n[baseline] KEEP {base_keep} / FP {base_fp} / 유실 {base_lost} (gold STORE {n_gold_keep}, NO_STORE {n_gold_nostore})")

    # conf 스윕: KEEP 규칙에 conf 하한 추가
    print("\n[conf 하한 스윕] tau | KEEP | FP | 유실 | 유실률 | FP 절감")
    print("-" * 70)
    for tau in (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70):
        keep = fp = lost = 0
        for r in rows:
            g = gate_keep(r)
            conf = max(r.get("jev_store_conf") or 0.0, r.get("jev_type_conf") or 0.0)
            keep_here = g and conf >= tau
            if keep_here:
                keep += 1
                if r["gold"].upper() == "NO_STORE":
                    fp += 1
            elif r["gold"].upper() == "STORE":
                lost += 1
        print(f"{tau:.2f} | {keep} | {fp} | {lost} | {lost/n_gold_keep:.1%} | {base_fp - fp if fp < base_fp else 0:+d}")

    # FP 유형 분해 (기준 규칙에서)
    print("\n[FP 유형 분해 — baseline KEEP 중 gold NO_STORE]")
    fp_types = {}
    for r in rows:
        if gate_keep(r) and r["gold"].upper() == "NO_STORE":
            t = (r.get("jev_type") or "?").upper()
            fp_types[t] = fp_types.get(t, 0) + 1
    print("type별 FP:", fp_types)
    # 유실 분해
    print("\n[유실 분해 — baseline SKIP 중 gold STORE]")
    lost_types = {}
    for r in rows:
        if not gate_keep(r) and r["gold"].upper() == "STORE":
            t = (r.get("jev_type") or "?").upper()
            lost_types[t] = lost_types.get(t, 0) + 1
    print("type별 유실:", lost_types)

    # 사람 gold와 JEV 판정의 일치율 (라벨 품질 교차)
    agree = sum(1 for r in rows if gate_keep(r) == (r["gold"].upper() == "STORE"))
    print(f"\n규칙-사람 일치: {agree}/{len(rows)} ({agree/len(rows):.1%})")

if __name__ == "__main__":
    main()