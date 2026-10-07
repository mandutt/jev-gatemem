"""Gate 재설계 오프라인 시뮬레이션 — gate NO + pointwise score 결합 규칙 (2026-10-04)

문제: Winner Entailment Gate 단독은 과다거부 80% (VALID 24건 희생 / PLAUS 6건 차단)
관찰: gate NO + 사람 VALID(오탐)의 pointwise max_score가 높음 (0.52~0.9)
     gate NO + 사람 PLAUS(정탐)는 점수 분포가 낮음 (0.28~0.72, 혼재)

재설계 규칙 후보:
  R1 (gate 단독):       gate=NO → abstain (기존, 과다거부)
  R2 (gate+score):      gate=NO AND score < θ → abstain,  gate=NO AND score ≥ θ → 주입
  R3 (gate+score 역):   gate=NO AND score < θ → abstain (θ 스윕)
  R4 (gate+score 정):   gate=YES → 주입 / gate=NO → score 기반 판단 (θ 스윕)

측정 (사람 판정 기준, LGO 90 + noans 50):
  - 해로운 오주입률 = PLAUS 주입 / 전체  (낮을수록 좋음)
  - VALID 차단률 = VALID abstain / 전체 VALID  (낮을수록 좋음)
  - 파레토: PLAUS 차단 vs VALID 보존

0콜 (기존 raw + 사람 판정만 사용)
"""
import json
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
DATA = "experiments/operational-golden/data"

# --- 데이터 로드 ---
vp = os.path.expandvars(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data\wgate_3class_verdicts.json")
v = json.load(open(vp, encoding="utf-8"))
d = json.load(open(os.path.join(DATA, "exp7f_winner_gate_raw.json"), encoding="utf-8"))
recs = d["records"]
for i, r in enumerate(recs):
    r["human"] = v[i]["v"]

# pointwise 점수 매핑 (op: diag6, LGO: exp7b, noans: exp7d 자체)
op_ps = {r["qid"]: r.get("max_score") for r in json.load(open(os.path.join(DATA, "diag6_op_scores.json"), encoding="utf-8"))["records"]}
lgo_ps = {r["qid"]: r.get("max_score") for r in json.load(open(os.path.join(DATA, "exp7b_lgo_raw.json"), encoding="utf-8"))["records"]}
noans_ps = {r["qid"]: r.get("max_score") for r in json.load(open(os.path.join(DATA, "exp7d_fresh_noans_raw.json"), encoding="utf-8"))["records"]}

# LGO: 전체 90건 = gate 실험 37(주입) + abstain 53. 나머지 53건은 base A abstain (안전)
# noans: 전체 50건 = gate 실험 6(주입) + abstain 44. 나머지 44건은 base A abstain (안전)
# op: 전체 90건 — gate 미실행이므로 gate=UNKNOWN. base A 결과 그대로 (gate 미적용 시나리오)

def lgo_score(qid):
    return lgo_ps.get(qid)

def noans_score(qid):
    return noans_ps.get(qid)

# LGO 90건 구성
lgo_all = []
for r in recs:
    if r["src"] == "lgo":
        lgo_all.append({"qid": r["qid"], "human": r["human"], "gate": r.get("verdict"),
                        "score": lgo_score(r["qid"])})
# abstain 53건 추가 (base A abstain — 사람 판정 없음, 안전 처리)
lgo_gate_qids = {r["qid"] for r in lgo_all}
lgo_choice = json.load(open(os.path.join(DATA, "exp7b2_lgo_choice_raw.json"), encoding="utf-8"))["records"]
for r in lgo_choice:
    if r.get("abstain") and r["qid"] not in lgo_gate_qids:
        lgo_all.append({"qid": r["qid"], "human": None, "gate": "ABSTAIN", "score": lgo_score(r["qid"])})

noans_all = []
for r in recs:
    if r["src"] == "noans":
        noans_all.append({"qid": r["qid"], "human": r["human"], "gate": r.get("verdict"),
                          "score": noans_score(r["qid"])})
nd = json.load(open(os.path.join(DATA, "exp7d_fresh_noans_raw.json"), encoding="utf-8"))["records"]
noans_gate_qids = {r["qid"] for r in noans_all}
for r in nd:
    if r.get("choice_abstain") and r["qid"] not in noans_gate_qids:
        noans_all.append({"qid": r["qid"], "human": None, "gate": "ABSTAIN", "score": r.get("max_score")})

# --- 규칙 시뮬레이션 ---
def simulate(rows, rule, theta=None):
    """rule: 'gate_only' | 'score_only' | 'gate_or_score' | 'gate_and_score'
    반환: 주입된 건 중 PLAUS 수, VALID 차단 수, VALID 주입 수, 총 주입 수
    """
    inject_plaus = inject_valid = total_inject = 0
    valid_blocked = 0
    for r in rows:
        gate = r["gate"]; score = r["score"] or 0; human = r["human"]
        if gate == "ABSTAIN":
            continue  # base A abstain — 어차피 안전
        # 주입 결정
        inject = False
        if rule == "gate_only":
            inject = (gate == "YES")
        elif rule == "score_only":
            inject = (score >= theta)
        elif rule == "gate_or_score":
            inject = (gate == "YES") or (score >= theta)
        elif rule == "gate_and_score":
            inject = (gate == "YES") and (score >= theta)
        elif rule == "gate_no_score_abstain":  # gate NO + score < θ → abstain, 아니면 주입
            inject = not (gate == "NO" and score < theta)
        if inject:
            total_inject += 1
            if human == "PLAUS":
                inject_plaus += 1
            elif human == "VALID":
                inject_valid += 1
        else:
            if human == "VALID":
                valid_blocked += 1
    return inject_plaus, valid_blocked, inject_valid, total_inject

print("=== LGO (90건) — 규칙별 결과 ===")
print("규칙                          PLAUS주입  VALID차단  VALID주입  총주입")
for rule in ["gate_only", "score_only", "gate_no_score_abstain"]:
    if rule == "gate_only":
        p, vb, vi, ti = simulate(lgo_all, "gate_only")
        print(f"{rule:<28} {p:>4}/90   {vb:>4}/90   {vi:>4}/90   {ti:>4}/90")
    elif rule == "score_only":
        for th in [0.5, 0.6, 0.65, 0.7]:
            p, vb, vi, ti = simulate(lgo_all, "score_only", th)
            print(f"score_only θ={th:<4}            {p:>4}/90   {vb:>4}/90   {vi:>4}/90   {ti:>4}/90")
    else:
        for th in [0.5, 0.6, 0.65, 0.7]:
            p, vb, vi, ti = simulate(lgo_all, "gate_no_score_abstain", th)
            print(f"gateNO+score<θ={th:<4}          {p:>4}/90   {vb:>4}/90   {vi:>4}/90   {ti:>4}/90")

print()
print("=== noans (50건) — 규칙별 결과 ===")
print("규칙                          PLAUS주입  VALID차단  VALID주입  총주입")
for rule in ["gate_only", "gate_no_score_abstain"]:
    if rule == "gate_only":
        p, vb, vi, ti = simulate(noans_all, "gate_only")
        print(f"{rule:<28} {p:>4}/50   {vb:>4}/50   {vi:>4}/50   {ti:>4}/50")
    else:
        for th in [0.5, 0.6, 0.65, 0.7]:
            p, vb, vi, ti = simulate(noans_all, "gate_no_score_abstain", th)
            print(f"gateNO+score<θ={th:<4}          {p:>4}/50   {vb:>4}/50   {vi:>4}/50   {ti:>4}/50")