"""exp8a 최종 분석 — winner-specific score 기반 R2 재평가 (2026-10-04)"""
import json
import statistics
import sys

sys.stdout.reconfigure(encoding="utf-8")
d = json.load(open("experiments/operational-golden/data/exp8a_rerun_choice_winner.json", encoding="utf-8"))
recs = d["records"]

print("=" * 70)
print("exp8a: winner-specific score 기반 R2 θ 스윕 (사람 판정 라벨 필요 시 별도)")
print("=" * 70)

# 1) op hit@3 — winner_score < θ 인 경우 abstain 시뮬레이션
op = [r for r in recs if r["grp"] == "op"]
print("\n=== op (90건) — θ 스윕 (winner_score < θ → abstain 가정) ===")
print(f"{'θ':<6} {'hit@3':<10} {'abstain':<10}")
base_h3 = sum(1 for r in op if r.get("gold_rank") is not None and r["gold_rank"] <= 3)
base_abs = sum(1 for r in op if r.get("choice_abstain"))
print(f"{'base':<6} {base_h3}/90 ({base_h3/90*100:.1f}%)  {base_abs}")
for th in [0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7]:
    h3 = 0
    abs_n = base_abs
    for r in op:
        if r.get("choice_abstain"):
            continue
        ws = r.get("winner_score")
        if ws is not None and ws < th:
            abs_n += 1  # abstain 전환
            continue
        if r.get("gold_rank") is not None and r["gold_rank"] <= 3:
            h3 += 1
    print(f"{th:<6} {h3}/90 ({h3/90*100:.1f}%)  {abs_n}")

# 2) lgo acceptance (선택률) — θ 스윕
lgo = [r for r in recs if r["grp"] == "lgo"]
print("\n=== lgo (90건) — θ 스윕 (winner_score < θ → abstain) ===")
lgo_base = sum(1 for r in lgo if not r.get("choice_abstain") and r.get("winner_id"))
print(f"base: acceptance {lgo_base}/90 ({lgo_base/90*100:.1f}%)")
for th in [0.4, 0.5, 0.6, 0.7]:
    acc = sum(1 for r in lgo if not r.get("choice_abstain") and r.get("winner_id")
              and (r.get("winner_score") is None or r["winner_score"] >= th))
    print(f"θ={th}: acceptance {acc}/90 ({acc/90*100:.1f}%)")

# 3) noans non-abstention — θ 스윕
noans = [r for r in recs if r["grp"] == "noans"]
print("\n=== noans (50건) — θ 스윕 ===")
noans_base = sum(1 for r in noans if not r.get("choice_abstain") and r.get("winner_id"))
print(f"base: non-abstain {noans_base}/50 ({noans_base/50*100:.1f}%)")
for th in [0.4, 0.5, 0.6, 0.7]:
    na = sum(1 for r in noans if not r.get("choice_abstain") and r.get("winner_id")
             and (r.get("winner_score") is None or r["winner_score"] >= th))
    print(f"θ={th}: non-abstain {na}/50 ({na/50*100:.1f}%)")

# 4) winner-specific 필요성
diff = n = 0
for r in recs:
    ws, ps = r.get("winner_score"), r.get("pool_max_score")
    if ws is not None and ps is not None:
        n += 1
        if abs(ws - ps) > 0.01:
            diff += 1
print(f"\n=== winner-specific score 필요성 ===")
print(f"winner != pool_max: {diff}/{n} ({diff/n*100:.1f}%)")

# 5) $0 비용 확인
costs = [r.get("cost") for r in recs if r.get("cost") is not None]
print(f"\n=== 비용 ===")
print(f"cost 샘플: {costs[:5]} | 전부 0.0: {all(c == 0.0 for c in costs) if costs else 'N/A'}")