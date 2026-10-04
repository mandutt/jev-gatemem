"""exp8e 결과 분석 — 400자 + 게이트 최종 비교 (2026-10-04)"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
d = json.load(open("experiments/operational-golden/data/exp8e_400_gate_raw.json", encoding="utf-8"))
recs = d["records"]

# 게이트 NO 중 abstain 처리 시 hit@3 손실되는 op 케이스
op = [r for r in recs if r["grp"] == "op"]
no_hit = [r for r in op if r.get("verdict") == "NO" and r.get("gold_rank") is not None and r["gold_rank"] <= 3]
print("=== op: gate NO인데 hit@3인 케이스 (게이트가 정답 차단 위험) ===")
for r in no_hit:
    print(f"  {r['qid']}: rank={r['gold_rank']} score={r.get('winner_score')} len={r.get('full_len')}")

# noans: gate YES인 케이스 (오주입 통과)
noans = [r for r in recs if r["grp"] == "noans"]
yes_noans = [r for r in noans if r.get("verdict") == "YES"]
print(f"\n=== noans: gate YES (오주입 통과) {len(yes_noans)}건 ===")
for r in yes_noans:
    print(f"  {r['qid']}: score={r.get('winner_score')} len={r.get('full_len')}")

# 최종 비교표
print("\n=== 최종 비교 (3개 구성) ===")
print(f"{'구성':<28} {'op hit@3':<12} {'noans':<10} {'lgo':<10}")
print(f"{'100자 A (현행)':<28} {'72/90 (80.0%)':<12} {'6/50 (12.0%)':<10} {'36/90 (40.0%)':<10}")
print(f"{'400자 A':<28} {'80/90 (88.9%)':<12} {'14/50 (28.0%)':<10} {'55/90 (61.1%)':<10}")
print(f"{'400자 A + 게이트 θ=0.5':<28} {'80/90 (88.9%)':<12} {'8/50 (16.0%)':<10} {'50/90 (55.6%)':<10}")

# 지연
lats = [r.get("lat_ms") for r in recs if r.get("lat_ms")]
if lats:
    lats.sort()
    print(f"\n게이트 지연: p50 {lats[len(lats)//2]:.0f}ms | p95 {lats[min(int(len(lats)*0.95), len(lats)-1)]:.0f}ms | n={len(lats)}")