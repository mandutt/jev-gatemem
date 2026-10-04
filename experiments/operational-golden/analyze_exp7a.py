import json, sys
sys.stdout.reconfigure(encoding='utf-8')

d7 = json.load(open('experiments/operational-golden/data/exp7a_A_rerun_raw.json', encoding='utf-8'))
rr = [r for r in d7['records'] if not r.get('err')]
n = len(rr)
abst = sum(1 for r in rr if r.get('abstain'))
hit1 = sum(1 for r in rr if r.get('hit1'))
hit3 = sum(1 for r in rr if r.get('gold_rank') is not None and r['gold_rank'] <= 3)
print("=== 7차 A 재실행 ===")
print(f"n={n} | hit@1={hit1} ({hit1/n*100:.1f}%) | hit@3={hit3} ({hit3/n*100:.1f}%) | abstain={abst} ({abst/n*100:.1f}%)")
print(f"corpus: {d7['corpus_n']}행 / hash={d7['corpus_hash']}")
print(f"lane: {d7['lane']}")

ab = json.load(open('experiments/operational-golden/data/ablation_2x2_raw.json', encoding='utf-8'))
op_a5 = [r for r in ab['results'] if r.get('src') == 'op' and r['cond'] == 'A']
n5 = len(op_a5)
h15 = sum(1 for r in op_a5 if r.get('rank') is not None and r['rank'] <= 1)
h35 = sum(1 for r in op_a5 if r.get('rank') is not None and r['rank'] <= 3)
a5 = sum(1 for r in op_a5 if r.get('abstain'))
print("\n=== 5차 A (본실험) ===")
print(f"n={n5} | hit@1={h15} ({h15/n5*100:.1f}%) | hit@3={h35} ({h35/n5*100:.1f}%) | abstain={a5}")

by_q7 = {r['qid']: r for r in rr}
by_q5 = {r['qid']: r for r in op_a5}
common = set(by_q7) & set(by_q5)
print(f"\n공통 qid: {len(common)}")
flip = []
for q in common:
    r5, r7 = by_q5[q], by_q7[q]
    hit5 = r5.get('rank') is not None and r5['rank'] <= 3
    hit7 = r7.get('gold_rank') is not None and r7['gold_rank'] <= 3
    if hit5 != hit7:
        flip.append((q, r5.get('rank'), r7.get('gold_rank'), r7.get('abstain'), r5.get('abstain')))
print(f"hit@3 변동 qid: {len(flip)}건")
for f in flip[:10]:
    print(f"  {f[0][:8]} | 5차 rank={f[1]} abstain={f[4]} | 7차 gold_rank={f[2]} abstain={f[3]}")

abst_flip = [q for q in common if bool(by_q5[q].get('abstain')) != bool(by_q7[q].get('abstain'))]
print(f"\nabstain 변동 qid: {len(abst_flip)}건")
for q in abst_flip[:8]:
    print(f"  {q[:8]} | 5차 abstain={by_q5[q].get('abstain')} | 7차 abstain={by_q7[q].get('abstain')}")