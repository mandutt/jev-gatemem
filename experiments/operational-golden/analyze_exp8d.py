"""exp8d 결과 분석 — excerpt 100/240/400 비교 (2026-10-04)"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

def load(f):
    d = json.load(open(f"experiments/operational-golden/data/{f}", encoding="utf-8"))
    return d["records"]

base = load("exp8a_rerun_choice_winner.json")
e240 = load("exp8d_excerpt240_raw.json")
e400 = load("exp8d_excerpt400_raw.json")

print("=== excerpt 길이별 결과 비교 ===")
print(f"{'':<8} {'100자':<18} {'240자':<18} {'400자':<18}")

def stats(recs, grp):
    sub = [r for r in recs if r["grp"] == grp]
    abs_n = sum(1 for r in sub if r.get("choice_abstain"))
    non = len(sub) - abs_n
    if grp == "op":
        h3 = sum(1 for r in sub if r.get("gold_rank") is not None and r["gold_rank"] <= 3)
        return f"{h3}/90 ({h3/90*100:.1f}%)", f"abs {abs_n}"
    return f"{non}/90 ({non/90*100:.1f}%)", f"abs {abs_n}"

for grp, label in [("op", "hit@3"), ("lgo", "non-abs"), ("noans", "non-abs")]:
    b = stats(base, grp)
    a = stats(e240, grp)
    c = stats(e400, grp)
    print(f"{label:<8} {b[0]:<18} {a[0]:<18} {c[0]:<18}")

# abstain
print()
for grp in ["op", "lgo", "noans"]:
    b_abs = sum(1 for r in base if r["grp"] == grp and r.get("choice_abstain"))
    a_abs = sum(1 for r in e240 if r["grp"] == grp and r.get("choice_abstain"))
    c_abs = sum(1 for r in e400 if r["grp"] == grp and r.get("choice_abstain"))
    print(f"abstain {grp:<6}: {b_abs:>2} → {a_abs:>2} → {c_abs:>2}")

# 지연
print()
for name, recs in [("100자", base), ("240자", e240), ("400자", e400)]:
    lats = [r.get("lat_ms") for r in recs if r.get("lat_ms")]
    if lats:
        lats.sort()
        p50 = lats[len(lats)//2]
        p95 = lats[min(int(len(lats)*0.95), len(lats)-1)]
        print(f"지연 {name}: p50 {p50:.0f}ms | p95 {p95:.0f}ms | n={len(lats)}")

# op hit@3 상세 변화 (100→400에서 새로 맞춘 쿼리)
print()
base_op = {r["qid"]: r for r in base if r["grp"] == "op"}
e400_op = {r["qid"]: r for r in e400 if r["grp"] == "op"}
improved = []
for qid in base_op:
    b = base_op[qid]
    c = e400_op.get(qid)
    if not c:
        continue
    b_hit = b.get("gold_rank") is not None and b["gold_rank"] <= 3
    c_hit = c.get("gold_rank") is not None and c["gold_rank"] <= 3
    if not b_hit and c_hit:
        improved.append(qid)
print(f"\n400자에서 새로 hit@3 달성: {len(improved)}건")
for qid in improved:
    print(f"  {qid}: {base_op[qid].get('gold_rank')} → {e400_op[qid].get('gold_rank')} (abstain: {base_op[qid].get('choice_abstain')} → {e400_op[qid].get('choice_abstain')})")