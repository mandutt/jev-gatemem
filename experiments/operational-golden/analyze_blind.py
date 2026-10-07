"""맹검 재판정 일치도 분석 — Cohen's kappa + 전환 매트릭스 (2026-10-04)"""
import json
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

# 맹검 결과
blind = json.load(open(os.path.expandvars(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data\wgate3_blind_verdicts.json"), encoding="utf-8"))
# 이전 사람 판정
vp = os.path.expandvars(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data\wgate_3class_verdicts.json")
v = json.load(open(vp, encoding="utf-8"))
# exp7g full-text 게이트 결과
g = json.load(open("experiments/operational-golden/data/exp7g_gate_fulltext_raw.json", encoding="utf-8"))
recs = g["records"]
for i, r in enumerate(recs):
    r["human"] = v[i]["v"]

# targets 순서 (build_blind_review.py와 동일 로직)
targets = [r for r in recs
           if (r.get("new_verdict") == "NO" and r["human"] == "VALID") or r["human"] == "PLAUS"]
# old_idx는 이 targets 리스트의 인덱스
print(f"targets: {len(targets)}건")

# old_idx → 이전 판정 매핑
prev_by_old = {i: r["human"] for i, r in enumerate(targets)}
prev_by_old_inv = {i: r["qid"] for i, r in enumerate(targets)}

# 맹검 vs 이전
pairs = []
for b in blind:
    old_i = b["old_idx"]
    pairs.append((prev_by_old[old_i], b["v"]))

agree = sum(1 for a, b in pairs if a == b)
n = len(pairs)
print(f"\n=== 일치도 ===")
print(f"일치: {agree}/{n} ({agree/n*100:.1f}%)")
print(f"불일치: {n - agree}건")

# Cohen's kappa (3분류)
labels = ["VALID", "PLAUS", "IRREL"]
mat = {}
for a in labels:
    mat[a] = {}
    for b in labels:
        mat[a][b] = 0
for a, b in pairs:
    mat[a][b] += 1

# kappa 계산
total = n
p0 = sum(mat[a][a] for a in labels) / total
pa = {}
for a in labels:
    pa[a] = (sum(mat[a][b] for b in labels) / total) * (sum(mat[b][a] for b in labels) / total)
pe = sum(pa.values())
kappa = (p0 - pe) / (1 - pe) if pe < 1 else 0
print(f"Cohen's kappa: {kappa:.3f}")
print(f"  (p0={p0:.3f}, pe={pe:.3f})")
if kappa >= 0.8:
    print("  해석: 거의 완벽한 일치 (평가자 안정성 높음)")
elif kappa >= 0.6:
    print("  해석: 상당한 일치")
elif kappa >= 0.4:
    print("  해석: 중간 일치 — 평가 기준이 다소 불안정")
else:
    print("  해석: 낮은 일치 — 평가 기준 변경 우려")

print(f"\n=== 전환 매트릭스 (이전 → 맹검) ===")
for a in labels:
    row = "  ".join(f"{mat[a][b]:>2}" for b in labels)
    print(f"  {a:<6} → [{row}]  (VALID PLAUS IRREL)")

print(f"\n=== 불일치 케이스 상세 ===")
for b in blind:
    old_i = b["old_idx"]
    prev_v = prev_by_old[old_i]
    if prev_v != b["v"]:
        r = targets[old_i]
        print(f"  [{r['src']}] {r['qid']}: 이전 {prev_v} → 맹검 {b['v']} | gate={r.get('new_verdict')}")