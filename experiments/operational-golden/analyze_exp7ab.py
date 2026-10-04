import json, sys
sys.stdout.reconfigure(encoding='utf-8')

# 1) A 재실행 (수정된 gold_rank 기준)
d7 = json.load(open('experiments/operational-golden/data/exp7a_A_rerun_raw.json', encoding='utf-8'))
rr = [r for r in d7['records'] if not r.get('err')]
n = len(rr)
abst = sum(1 for r in rr if r.get('abstain'))
hit1 = sum(1 for r in rr if r.get('hit1'))
hit3 = sum(1 for r in rr if r.get('gold_rank') is not None and r['gold_rank'] <= 3 and not r.get('abstain'))
hit3_all = sum(1 for r in rr if r.get('gold_rank') is not None and r['gold_rank'] <= 3)
print("=== 7차 A 재실행 (수정 gold_rank) ===")
print(f"n={n} | hit@1={hit1} ({hit1/n*100:.1f}%) | hit@3(답변)={hit3} ({hit3/n*100:.1f}%) | hit@3(abstain포함)={hit3_all} | abstain={abst} ({abst/n*100:.1f}%)")
print(f"corpus: {d7['corpus_n']}행 / hash={d7['corpus_hash']}")
print(f"lane: {d7['lane']}")

# 5차 A와 per-qid 대조
ab = json.load(open('experiments/operational-golden/data/ablation_2x2_raw.json', encoding='utf-8'))
op_a5 = [r for r in ab['results'] if r.get('src') == 'op' and r['cond'] == 'A']
print("\n=== 5차 A (본실험) ===")
n5 = len(op_a5)
print(f"n={n5} | hit@1={sum(1 for r in op_a5 if r.get('rank') is not None and r['rank']<=1)} | hit@3={sum(1 for r in op_a5 if r.get('rank') is not None and r['rank']<=3)} ({sum(1 for r in op_a5 if r.get('rank') is not None and r['rank']<=3)/n5*100:.1f}%) | abstain={sum(1 for r in op_a5 if r.get('abstain'))}")

by_q7 = {r['qid']: r for r in rr}
by_q5 = {r['qid']: r for r in op_a5}
common = set(by_q7) & set(by_q5)
flip = []
for q in common:
    r5, r7 = by_q5[q], by_q7[q]
    hit5 = r5.get('rank') is not None and r5['rank'] <= 3
    hit7 = r7.get('gold_rank') is not None and r7['gold_rank'] <= 3
    if hit5 != hit7:
        flip.append((q, r5.get('rank'), bool(r5.get('abstain')), r7.get('gold_rank'), bool(r7.get('abstain'))))
print(f"\nhit@3 변동 qid: {len(flip)}건")
for f in flip:
    print(f"  {f[0][:8]} | 5차 rank={f[1]} abstain={f[2]} | 7차 gold_rank={f[3]} abstain={f[4]}")

abst_flip = [q for q in common if bool(by_q5[q].get('abstain')) != bool(by_q7[q].get('abstain'))]
print(f"\nabstain 변동: {len(abst_flip)}건 (7차에서 abstain 추가: {sum(1 for q in abst_flip if by_q7[q].get('abstain'))} / 5차→7차 해제: {sum(1 for q in abst_flip if not by_q7[q].get('abstain'))})")

# 2) leave-gold-out
lgo = json.load(open('experiments/operational-golden/data/exp7b_lgo_raw.json', encoding='utf-8'))
lr = [r for r in lgo['records'] if not r.get('err') and r.get('max_score') is not None]
print("\n=== leave-gold-out (gold 제거 후 pointwise) ===")
print(f"n={len(lr)}")
for t in (0.5, 0.65):
    fp = sum(1 for r in lr if r[f'fp_tau{t}'])
    print(f"  τ={t}: 발동(오주입) {fp}/{len(lr)} = {fp/len(lr)*100:.1f}%  [가드레일 ≤5%: {'PASS' if fp/len(lr)<=0.05 else 'FAIL'}]")
ms = [r['max_score'] for r in lr]
print(f"  max_score: mean={sum(ms)/len(ms):.3f} max={max(ms):.3f}")
# 발동된 top1이 gold와 얼마나 가까운지 (같은 주제?)
print(f"  lane: {lgo['lane']} | corpus: {lgo['corpus_n']}행")