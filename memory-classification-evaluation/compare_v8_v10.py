"""v8 vs v10 (ALL1975 전체) 비교 — 정확도·store·type 분포·오분류 변화 분석.

Usage: python compare_v8_v10.py [v8.jsonl] [v10.jsonl]
"""
import json
import sys
from collections import Counter, defaultdict

v8_path = sys.argv[1] if len(sys.argv) > 1 else "JEV_ALL1975_V8.jsonl"
v10_path = sys.argv[2] if len(sys.argv) > 2 else "JEV_ALL1975_V10.jsonl"

v8 = {r["id"]: r for r in (json.loads(l) for l in open(v8_path, encoding="utf-8"))}
v10 = {r["id"]: r for r in (json.loads(l) for l in open(v10_path, encoding="utf-8"))}
ids = [i for i in v8 if i in v10]
print(f"matched: {len(ids)}\n")

# 1. 전체 정확도
def acc(m):
    ok = sum(1 for i in ids if m[i]["type"] == m[i]["gold_type"])
    return ok, 100 * ok / len(ids)

for name, m in [("v8", v8), ("v10", v10)]:
    ok, pct = acc(m)
    print(f"{name}: 14-type {ok}/{len(ids)} = {pct:.1f}%")

# store 정확도
def store_acc(m):
    tp = sum(1 for i in ids if m[i]["gold_type"] != "NO_STORE" and m[i]["store"] == "STORE")
    gs = sum(1 for i in ids if m[i]["gold_type"] != "NO_STORE")
    ps = sum(1 for i in ids if m[i]["store"] == "STORE")
    return tp, gs, ps

for name, m in [("v8", v8), ("v10", v10)]:
    tp, gs, ps = store_acc(m)
    p = tp / ps if ps else 0
    r = tp / gs if gs else 0
    print(f"{name}: store precision {p:.3f} ({tp}/{ps}) recall {r:.3f} ({tp}/{gs})")

# 2. gold 구간별 (NO_STORE vs store)
print("\n=== gold 구간별 ===")
for label, sub in [("gold NO_STORE", [i for i in ids if v8[i]["gold_type"] == "NO_STORE"]),
                    ("gold store", [i for i in ids if v8[i]["gold_type"] != "NO_STORE"])]:
    if not sub:
        continue
    for name, m in [("v8", v8), ("v10", v10)]:
        ok = sum(1 for i in sub if m[i]["type"] == m[i]["gold_type"])
        print(f"  {label} {name}: {ok}/{len(sub)} = {100*ok/len(sub):.1f}%")

# 3. per-type 정확도
print("\n=== per-type 정확도 (v8 vs v10) ===")
by_type = defaultdict(list)
for i in ids:
    by_type[v8[i]["gold_type"]].append(i)
for t, sub in sorted(by_type.items(), key=lambda x: -len(x[1])):
    v8_ok = sum(1 for i in sub if v8[i]["type"] == t)
    v10_ok = sum(1 for i in sub if v10[i]["type"] == t)
    delta = v10_ok - v8_ok
    mark = "" if delta == 0 else (" ▲" if delta > 0 else " ▼")
    print(f"  {t:12s} n={len(sub):4d} | v8 {100*v8_ok/len(sub):5.1f}% | v10 {100*v10_ok/len(sub):5.1f}% ({delta:+d}){mark}")

# 4. 변경 요약
print("\n=== 판정 변경 ===")
changed = [i for i in ids if v8[i]["type"] != v10[i]["type"]]
print(f"type 변경: {len(changed)}/{len(ids)} ({100*len(changed)/len(ids):.1f}%)")

# 변경이 정답으로/오답으로
improved = sum(1 for i in changed if v10[i]["type"] == v10[i]["gold_type"] and v8[i]["type"] != v8[i]["gold_type"])
worsened = sum(1 for i in changed if v10[i]["type"] != v10[i]["gold_type"] and v8[i]["type"] == v8[i]["gold_type"])
flip_to_wrong = sum(1 for i in changed if v10[i]["type"] != v10[i]["gold_type"] and v8[i]["type"] != v8[i]["gold_type"] and v10[i]["type"] != v8[i]["type"])
print(f"  향상(wrong→right): {improved} | 악화(right→wrong): {worsened} | 둘 다 wrong: {len(changed)-improved-worsened}")

# 5. store 게이트 관점 (v10): SKIP = store NO_STORE & conf>=0.6
print("\n=== v10 게이트 (store NO_STORE & conf>=0.6) ===")
skip = [i for i in ids if v10[i]["store"] == "NO_STORE" and (v10[i].get("store_confidence") or 0) >= 0.6]
skip_gold_store = sum(1 for i in skip if v10[i]["gold_type"] != "NO_STORE")
print(f"SKIP {len(skip)}건 ({100*len(skip)/len(ids):.1f}%) | 그중 gold store(누락위험): {skip_gold_store}건")

# per-gold-type
skip_by_type = Counter(v10[i]["gold_type"] for i in skip)
print("  SKIP된 gold type 분포:", dict(skip_by_type.most_common()))