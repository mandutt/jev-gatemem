"""exp8a 분석 — winner-specific score vs pool max + hit@3 + θ 적용"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
d = json.load(open("experiments/operational-golden/data/exp8a_rerun_choice_winner.json", encoding="utf-8"))
recs = d["records"]

print("=== exp8a 재실행 결과 ===")
print("corpus_n:", d.get("corpus_n"))
print()

# 1) op hit@3
op = [r for r in recs if r["grp"] == "op"]
h3 = sum(1 for r in op if r.get("gold_rank") is not None and r["gold_rank"] <= 3)
op_abs = sum(1 for r in op if r.get("choice_abstain"))
print(f"op: hit@3 {h3}/90 ({h3/90*100:.1f}%) | abstain {op_abs}")

# 2) winner_score vs pool_max_score
print()
print("=== winner_score vs pool_max_score (c AI 지적 검증) ===")
diff = n = 0
for r in recs:
    ws, ps = r.get("winner_score"), r.get("pool_max_score")
    if ws is not None and ps is not None:
        n += 1
        if abs(ws - ps) > 0.01:
            diff += 1
print(f"winner_score != pool_max_score: {diff}/{n} ({diff/n*100:.1f}%)")
print("→ winner-specific score 필요:", "YES" if diff > 0 else "NO")
if diff > 0:
    print("예시 (winner != pool max):")
    cnt = 0
    for r in recs:
        ws, ps = r.get("winner_score"), r.get("pool_max_score")
        if ws is not None and ps is not None and abs(ws - ps) > 0.01 and cnt < 8:
            print(f"  [{r['grp']}] {r['qid']}: winner={ws:.2f} max={ps:.2f}")
            cnt += 1

# 3) winner_score < 0.5 분포
print()
print("=== winner_score < 0.5 (gate NO + score<θ 시 abstain) ===")
for grp in ["op", "lgo", "noans"]:
    sub = [r for r in recs if r["grp"] == grp and r.get("winner_score") is not None]
    if not sub:
        print(f"{grp}: winner 0건")
        continue
    low = [r for r in sub if r["winner_score"] < 0.5]
    print(f"{grp}: winner {len(sub)}건 중 score<0.5 {len(low)}건 ({len(low)/len(sub)*100:.1f}%)")

# 4) θ=0.5 적용 시 op hit@3 변화 (winner_score 기준 — gate NO 가정 하한)
print()
print("=== θ=0.5 적용 (winner_score<0.5 → abstain 가정) op hit@3 ===")
lp = 0
for r in op:
    if r.get("choice_abstain"):
        continue
    ws = r.get("winner_score")
    if ws is not None and ws < 0.5:
        lp += 1
print(f"winner_score<0.5인 op 비-abstain: {lp}건 → 이들 abstain 시 hit@3 {h3-lp}/90 ({(h3-lp)/90*100:.1f}%)")

# 5) lgo/noans winner_score 분포
print()
print("=== lgo/noans winner_score ===")
for grp in ["lgo", "noans"]:
    sub = [r for r in recs if r["grp"] == grp and r.get("winner_score") is not None]
    if sub:
        scores = [r["winner_score"] for r in sub]
        print(f"{grp}: winner {len(sub)}건 | mean {sum(scores)/len(scores):.3f} | min {min(scores):.3f} | max {max(scores):.3f}")
    else:
        print(f"{grp}: winner 0건")