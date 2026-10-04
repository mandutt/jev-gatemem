"""0콜 오프라인 파레토 분석 — A choice vs pointwise 점수 임계 스윕

목적: API 호출 없이 raw 데이터만으로,
  "A(choice) 선택 + pointwise max_score 임계 τ" 조합이
  LGO/fresh noans 오주입과 op hit@3 손실을 어떻게 트레이드오프하는지 파레토 곡선 도출.

데이터 (모두 기존 실행 raw):
- exp7a_A_rerun_raw.json   : op 90 A choice (gold_rank, abstain)
- diag6_op_scores.json     : op 90 pointwise (max_score, gold_rank)
- exp7b_lgo_raw.json       : LGO pointwise (max_score)
- exp7b2_lgo_choice_raw.json : LGO choice (abstain)
- exp7d_fresh_noans_raw.json : fresh noans (choice_abstain + max_score)

규칙 (오프라인 시뮬레이션):
- A(choice)가 abstain → 빈 컨텍스트 (안전)
- A(choice)가 선택 + pointwise max_score < τ → 강제 abstain (신규 게이트)
- A(choice)가 선택 + pointwise max_score >= τ → 그대로 주입
τ를 0.0~0.9 스윕하며 op hit@3 / LGO acceptance / noans FP 계산.

검증: 실측 vs 시뮬레이션 (τ=-∞ 즉 게이트 없음 = 순수 A 결과와 일치해야 함)
"""
import json
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
ROOT = "experiments/operational-golden/data"

def load(f):
    d = json.load(open(os.path.join(ROOT, f), encoding="utf-8"))
    return d["records"] if isinstance(d, dict) else d

# --- 데이터 로드 ---
op_choice = load("exp7a_A_rerun_raw.json")     # A choice op
op_point  = load("diag6_op_scores.json")       # pointwise op
lgo_point = load("exp7b_lgo_raw.json")         # LGO pointwise
lgo_choice = load("exp7b2_lgo_choice_raw.json")  # LGO choice
noans     = load("exp7d_fresh_noans_raw.json") # fresh noans

# qid → max_score 매핑 (pointwise)
op_ps = {r["qid"]: r["max_score"] for r in op_point}
lgo_ps = {r["qid"]: r["max_score"] for r in lgo_point}

# --- 기본 실측 (τ 없음) ---
# op: A choice hit@3 — 레코드 단위 (90 = 45 qid × 2 gold, 7차 보고서와 동일 기준)
op_rows = list(op_choice)  # qid dedupe 없이 레코드 그대로 (90건)

op_total = len(op_rows)
op_abstain = sum(1 for r in op_rows if r.get("abstain"))
op_hit3 = sum(1 for r in op_rows if not r.get("abstain") and r.get("gold_rank") is not None and r["gold_rank"] <= 3)
print(f"[실측] op: {op_total}건 abstain {op_abstain} hit@3 {op_hit3} ({op_hit3/op_total:.1%})")

# LGO: choice non-abstain (acceptance)
lgo_total = len(lgo_choice)
lgo_acc = sum(1 for r in lgo_choice if not r.get("abstain"))
print(f"[실측] LGO: {lgo_total}건 acceptance {lgo_acc} ({lgo_acc/lgo_total:.1%})")

# noans: choice FP (non-abstain)
noans_fp = sum(1 for r in noans if not r.get("choice_abstain"))
print(f"[실측] fresh noans: {len(noans)}건 FP {noans_fp} ({noans_fp/len(noans):.1%})")

print()

# --- τ 스윕 시뮬레이션 ---
# 게이트: choice가 선택했는데 pointwise max_score < τ → abstain 강제
print("τ       op hit@3      op abstain    LGO acc      noans FP    (트레이드오프)")
print("-" * 75)
results = []
for tau in [0.0, 0.1, 0.2, 0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.9]:
    # op: choice 선택 + max_score >= tau → hit 유지, 아니면 abstain
    op_hit = 0; op_abs = 0
    for r in op_rows:
        if r.get("abstain"):
            op_abs += 1
            continue
        ms = op_ps.get(r["qid"])
        if ms is None or ms >= tau:
            if r.get("gold_rank") is not None and r["gold_rank"] <= 3:
                op_hit += 1
        else:
            op_abs += 1
    # LGO: choice 선택 + max_score >= tau → acceptance 유지
    lgo_acc_t = 0
    for r in lgo_choice:
        if r.get("abstain"):
            continue
        ms = lgo_ps.get(r["qid"])
        if ms is None or ms >= tau:
            lgo_acc_t += 1
    # noans: choice non-abstain + max_score >= tau → FP 유지 (아니면 abstain으로 방어)
    noans_fp_t = 0
    for r in noans:
        if r.get("choice_abstain"):
            continue
        ms = r.get("max_score", 0)
        if ms >= tau:
            noans_fp_t += 1
    op_hit3_pct = op_hit / op_total * 100
    lgo_pct = lgo_acc_t / lgo_total * 100
    noans_pct = noans_fp_t / len(noans) * 100
    results.append((tau, op_hit, op_abs, lgo_acc_t, noans_fp_t))
    print(f"{tau:>4.2f}   {op_hit:>4}/90 ({op_hit3_pct:>5.1f}%)   {op_abs:>4}/90 ({op_abs/op_total*100:>5.1f}%)   {lgo_acc_t:>4}/90 ({lgo_pct:>5.1f}%)   {noans_fp_t:>4}/50 ({noans_pct:>5.1f}%)")

# --- 파레토 프론티어 추출 ---
print()
print("=== 파레토 프론티어 (noans FP 감소 vs op hit@3 손실) ===")
print("(τ, op hit@3, LGO acc, noans FP, op 손실)")
best = None
for tau, oh, oa, la, nf in results:
    loss = op_total - oh  # hit@3 손실 건수 (abstain 포함)
    gain = noans_fp - nf  # FP 감소 건수
    print(f"τ={tau:.2f}: hit@3 손실 {loss}건, noans FP {nf}건 ({nf/len(noans)*100:.1f}%), LGO acc {la}/{lgo_total} ({la/lgo_total*100:.1f}%)")

# --- 최적 지점 후보 (5% 가드레일: noans FP <= 2.5건 = 5%) ---
print()
print("=== 5% 가드레일 (noans FP ≤ 2.5건) 충족 지점 ===")
for tau, oh, oa, la, nf in results:
    if nf / len(noans) <= 0.05:
        print(f"τ={tau:.2f}: noans FP {nf}/50 ({nf/len(noans)*100:.1f}%) ✓, op hit@3 {oh}/90 ({oh/90*100:.1f}%), LGO acc {la}/90 ({la/90*100:.1f}%)")

# --- 저장 ---
out = {
    "baseline": {
        "op_total": op_total, "op_abstain": op_abstain, "op_hit3": op_hit3,
        "lgo_total": lgo_total, "lgo_acceptance": lgo_acc,
        "noans_total": len(noans), "noans_fp": noans_fp,
    },
    "sweep": [{"tau": t, "op_hit3": oh, "op_abstain": oa, "lgo_acc": la, "noans_fp": nf}
              for t, oh, oa, la, nf in results],
}
os.makedirs("docs/review", exist_ok=True)
with open("experiments/operational-golden/data/pareto_offline_result.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print()
print("저장: experiments/operational-golden/data/pareto_offline_result.json")