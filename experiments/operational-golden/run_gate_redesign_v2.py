"""full-text 게이트 + score 조건 재시뮬레이션 (2026-10-04, 0콜)

exp7g(full-text gate) + 사람 판정(43건) + pointwise score 로 R2 규칙 재평가:

R2 = gate=YES → 주입
     gate=NO & score >= θ → 주입
     gate=NO & score < θ  → abstain
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
DATA = "experiments/operational-golden/data"

# 사람 판정
vp = os.path.expandvars(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data\wgate_3class_verdicts.json")
v = json.load(open(vp, encoding="utf-8"))

# exp7g full-text 게이트 결과 (43건)
g = json.load(open(os.path.join(DATA, "exp7g_gate_fulltext_raw.json"), encoding="utf-8"))
recs = g["records"]
for i, r in enumerate(recs):
    r["human"] = v[i]["v"]

# pointwise scores
lgo_ps = {r["qid"]: r.get("max_score") for r in json.load(open(os.path.join(DATA, "exp7b_lgo_raw.json"), encoding="utf-8"))["records"]}
noans_ps = {r["qid"]: r.get("max_score") for r in json.load(open(os.path.join(DATA, "exp7d_fresh_noans_raw.json"), encoding="utf-8"))["records"]}
op_ps = {r["qid"]: r.get("max_score") for r in json.load(open(os.path.join(DATA, "diag6_op_scores.json"), encoding="utf-8"))["records"]}

for r in recs:
    r["score"] = (lgo_ps if r["src"] == "lgo" else noans_ps).get(r["qid"], 0)

# LGO 전체 90건 구성 (gate 실험 37 + abstain 53)
lgo_all = [r for r in recs if r["src"] == "lgo"]
lgo_choice = json.load(open(os.path.join(DATA, "exp7b2_lgo_choice_raw.json"), encoding="utf-8"))["records"]
lgo_gate_qids = {r["qid"] for r in lgo_all}
for r in lgo_choice:
    if r.get("abstain") and r["qid"] not in lgo_gate_qids:
        lgo_all.append({"qid": r["qid"], "human": None, "new_verdict": "ABSTAIN", "score": lgo_ps.get(r["qid"], 0)})

noans_all = [r for r in recs if r["src"] == "noans"]
nd = json.load(open(os.path.join(DATA, "exp7d_fresh_noans_raw.json"), encoding="utf-8"))["records"]
noans_gate_qids = {r["qid"] for r in noans_all}
for r in nd:
    if r.get("choice_abstain") and r["qid"] not in noans_gate_qids:
        noans_all.append({"qid": r["qid"], "human": None, "new_verdict": "ABSTAIN", "score": r.get("max_score", 0)})

def simulate(rows, theta):
    inject_plaus = inject_valid = total = valid_blocked = 0
    for r in rows:
        gate = r.get("new_verdict"); score = r.get("score") or 0; human = r.get("human")
        if gate == "ABSTAIN":
            continue
        inject = (gate == "YES") or (gate == "NO" and score >= theta)
        if inject:
            total += 1
            if human == "PLAUS": inject_plaus += 1
            elif human == "VALID": inject_valid += 1
        else:
            if human == "VALID": valid_blocked += 1
    return inject_plaus, valid_blocked, inject_valid, total

print("=== full-text 게이트 + score (R2) 재시뮬레이션 ===")
print("LGO (90건):")
print(f"{'θ':<6} {'PLAUS주입':<10} {'VALID차단':<10} {'VALID주입':<10} {'총주입'}")
for th in [0.5, 0.55, 0.6, 0.65, 0.7, 0.75]:
    p, vb, vi, ti = simulate(lgo_all, th)
    print(f"{th:<6} {p:<10} {vb:<10} {vi:<10} {ti}")

print()
print("noans (50건):")
print(f"{'θ':<6} {'PLAUS주입':<10} {'VALID차단':<10} {'VALID주입':<10} {'총주입'}")
for th in [0.5, 0.55, 0.6, 0.65, 0.7, 0.75]:
    p, vb, vi, ti = simulate(noans_all, th)
    print(f"{th:<6} {p:<10} {vb:<10} {vi:<10} {ti}")