"""stage74 분석: bekko vs gemma2-q8 vs gemma2-q4f16 쿼리별 대조.
- hit@1 flip (누가 이겼는지)
- abstain 변화
- gold_rank_pool (retrieval) 차이
"""
import json, os, sys

DATA = r"C:/Users/mandu/hermes-made/jev-memory-middleware/experiments/operational-golden/data"

base = json.load(open(os.path.join(DATA, "stage54_op90_regress.json"), encoding="utf-8"))["base"]
q8 = json.load(open(os.path.join(DATA, "stage74_gemma2_q8.json"), encoding="utf-8"))["results"]
q4 = json.load(open(os.path.join(DATA, "stage74_gemma2_q4f16.json"), encoding="utf-8"))["results"]

def rank_of(r):
    """choice lift 후 gold 순위 (stage54 로직과 동일). abstain/err이면 None."""
    if r["err"] or r["abstain"] or r["gold_rank_pool"] is None:
        return None
    ci = r["choice_idx"]
    if ci is not None and isinstance(ci, int):
        return 1 if (ci == r["gold_rank_pool"] - 1) else (
            r["gold_rank_pool"] if r["gold_rank_pool"] <= ci else r["gold_rank_pool"] + 1)
    return r["gold_rank_pool"]

n = len(base)
# 1) hit@1 flip 매트릭스
wins = {"b_only": [], "q8_only": [], "q4_only": [], "all3": [], "none": [], "b_q8": [], "b_q4": [], "q8_q4": []}
for i in range(n):
    rb = 1 if rank_of(base[i]) == 1 else 0
    r8 = 1 if rank_of(q8[i]) == 1 else 0
    r4 = 1 if rank_of(q4[i]) == 1 else 0
    key = f"{rb}{r8}{r4}"
    if key == "111": wins["all3"].append(i)
    elif key == "100": wins["b_only"].append(i)
    elif key == "010": wins["q8_only"].append(i)
    elif key == "001": wins["q4_only"].append(i)
    elif key == "000": wins["none"].append(i)
    elif key == "110": wins["b_q8"].append(i)
    elif key == "101": wins["b_q4"].append(i)
    elif key == "011": wins["q8_q4"].append(i)

print("=== hit@1 (choice lift 후) 쿼리별 대조 ===")
print(f"전부 hit   : {len(wins['all3'])}")
print(f"bekko만 hit: {len(wins['b_only'])} <- {[base[i]['q'][:40] for i in wins['b_only'][:8]]}")
print(f"q8만 hit   : {len(wins['q8_only'])} <- {[base[i]['q'][:40] for i in wins['q8_only'][:8]]}")
print(f"q4만 hit   : {len(wins['q4_only'])} <- {[base[i]['q'][:40] for i in wins['q4_only'][:8]]}")
print(f"q8+q4 hit  : {len(wins['q8_q4'])} <- {[base[i]['q'][:40] for i in wins['q8_q4'][:8]]}")
print(f"bekko+q8   : {len(wins['b_q8'])}")
print(f"bekko+q4   : {len(wins['b_q4'])}")
print(f"모두 miss  : {len(wins['none'])}")

# 2) abstain 변화
print("\n=== abstain ===")
print("bekko:", sum(1 for r in base if r["abstain"]),
      "q8:", sum(1 for r in q8 if r["abstain"]),
      "q4:", sum(1 for r in q4 if r["abstain"]))
# q8에서 abstain된 쿼리 & bekko에서 abstain된 쿼리
for name, arr in (("bekko", base), ("q8", q8), ("q4", q4)):
    abs_idx = [i for i, r in enumerate(arr) if r["abstain"]]
    print(f"  {name} abstain idx: {abs_idx}")
    for i in abs_idx:
        print(f"    [{i}] {arr[i]['q'][:50]}")

# 3) gold_rank_pool 분포 (retrieval 단계만)
print("\n=== pool gold rank (retrieval) ===")
for name, arr in (("bekko", base), ("q8", q8), ("q4", q4)):
    ranks = [r["gold_rank_pool"] for r in arr if r["gold_rank_pool"] is not None]
    in_pool = len(ranks)
    top1 = sum(1 for r in ranks if r == 1)
    top5 = sum(1 for r in ranks if r <= 5)
    print(f"  {name}: pool 내 gold {in_pool}/90, top1={top1}, top5={top5}, median rank={sorted(ranks)[len(ranks)//2] if ranks else '-'}")