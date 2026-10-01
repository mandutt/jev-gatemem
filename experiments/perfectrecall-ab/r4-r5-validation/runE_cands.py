"""Run E: kodialog 판정 차이 26건 — 'cands 5개만 판정' 재현 (PR 조건)
가설: 같은 내 점수라도 후보 집합을 cands(5)로 좁히면 PR과 동일하게 1위가 나오는가?
→ 격차의 본질이 '판정기 품질'이 아니라 '평가 후보 집합 크기'임을 검증
"""
import json, os, sys, re, random
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'perfectrecall'))
from mnemosyne.core import jev

os.environ['MNEMOSYNE_JEV_PROVIDER'] = 'typesafe'
KEY = os.environ.get('TYPESAFE_API_KEY', '')
if not KEY:
    for p in ('%LOCALAPPDATA%/jev-mem/.env', '%LOCALAPPDATA%/jev-mem/bench/run-20261001-s4/.env'):
        if os.path.exists(os.path.expandvars(p)):
            for line in open(os.path.expandvars(p), encoding='utf-8'):
                m = re.match(r'\s*TYPESAFE_API_KEY\s*=\s*(.+)', line)
                if m:
                    KEY = m.group(1).strip().strip('"\'')
                    break
        if KEY: break
os.environ['TYPESAFE_API_KEY'] = KEY
print('KEY:', 'OK' if KEY else 'FAIL', flush=True)

HERE = os.path.dirname(os.path.abspath(__file__))
runA = json.load(open(os.path.join(HERE, 'runA_perquery.json'), encoding='utf-8'))
pr = json.load(open(os.path.join(HERE, 'pr_perquery.json'), encoding='utf-8'))['per_query']
items = json.load(open('C:/Users/mandu/AppData/Local/hermes/cache/scratch/scratch_items.json', encoding='utf-8'))

def norm(s): return re.sub(r'[\s.,!?~\'\"()\[\]]', '', s)
pr_correct = []
for qi, prq in enumerate(pr):
    ans = (items[qi].get('pool') or items[qi].get('candidates'))[items[qi]['answer']]
    n1, n2 = norm(prq['top1_content']), norm(ans)
    pr_correct.append(prq['top1_is_ans'] and (n1[:len(n2)]==n2 or n2[:len(n1)]==n1))
gap_kd = [qi for qi in range(180) if items[qi]['dataset'].startswith('kodialog')
          and pr_correct[qi] and not runA[qi]['hit1'] and runA[qi]['covered']]
print('kodialog 판정차이(풀커버):', len(gap_kd), flush=True)

INSTR = ('Does candidate contain concrete information useful to answer state.query? '
         'Accept direct evidence, semantically equivalent wording, or a necessary supporting fact. '
         'Reject mere keyword overlap, unrelated subjects and claims that only say they are relevant.')

random.seed(7)
sample = random.sample(gap_kd, min(12, len(gap_kd)))
h1 = 0
out = []
for qi in sample:
    it = items[qi]
    cands = it.get('pool') or it.get('candidates')
    ans = cands[it['answer']]
    scores = jev.judge_many({'query': it['query']}, cands, INSTR)
    order = sorted(range(len(cands)), key=lambda i: -scores[i])
    rank = order.index(cands.index(ans)) + 1
    h1 += (rank == 1)
    out.append({'idx': qi, 'rank_cands': rank})
    print(f'  idx={qi}: cands-only rank={rank}', flush=True)

print()
print(f'=== cands 5개만 판정 (내 스코어러) hit@1: {h1}/{len(sample)} ===')
print(f'(PR 동일 조건Acc@1 = 0.817 참고)')
json.dump(out, open(os.path.join(HERE, 'runE_cands12.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)