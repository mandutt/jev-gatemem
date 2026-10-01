"""Run C: 판정 차이 27건의 실체 규명
1) 27건 쿼리를 동일 조건으로 3회 반복 판정 → JEV 비결정성이 27건을 설명하는가?
2) 각 회차별 정답 순위/점수 변동 확인
3) 동점률 측정 (top1 점수가 여러 후보와 동점인가)
"""
import json, os, sys, time, re
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'perfectrecall'))
from mnemosyne.core import jev

os.environ['MNEMOSYNE_JEV_PROVIDER'] = 'typesafe'
KEY = os.environ.get('TYPESAFE_API_KEY', '')
if not KEY:
    import re
    for p in ('%LOCALAPPDATA%/jev-mem/.env', '%LOCALAPPDATA%/jev-mem/bench/run-20261001-s4/.env'):
        if os.path.exists(os.path.expandvars(p)):
            for line in open(os.path.expandvars(p), encoding='utf-8'):
                m = re.match(r'\s*TYPESAFE_API_KEY\s*=\s*(.+)', line)
                if m:
                    KEY = m.group(1).strip().strip('"\'')
                    break
        if KEY: break
os.environ['TYPESAFE_API_KEY'] = KEY

HERE = os.path.dirname(os.path.abspath(__file__))
SCRATCH = os.path.dirname(HERE)
items = json.load(open(os.path.join(SCRATCH, 'scratch_items.json'), encoding='utf-8'))
pools = json.load(open(os.path.join(SCRATCH, 'pools_relaxed.json'), encoding='utf-8'))
runA = json.load(open(os.path.join(HERE, 'runA_perquery.json'), encoding='utf-8'))
pr = json.load(open(os.path.join(HERE, 'pr_perquery.json'), encoding='utf-8'))['per_query']

def norm(s): return re.sub(r'[\s.,!?~\'\"()\[\]]', '', s)
# PR만 정답 & 풀 커버 = 27건
pr_correct = []
for qi, prq in enumerate(pr):
    ans = (items[qi].get('pool') or items[qi].get('candidates'))[items[qi]['answer']]
    n1, n2 = norm(prq['top1_content']), norm(ans)
    pr_correct.append(prq['top1_is_ans'] and (n1[:len(n2)]==n2 or n2[:len(n1)]==n1))
gap27 = [i for i in range(180) if pr_correct[i] and runA[i]['hit1'] != 1 and runA[i]['covered']]
print(f'판정 차이 쿼리: {len(gap27)}건', flush=True)

INSTR = ('Does candidate contain concrete information useful to answer state.query? '
         'Accept direct evidence, semantically equivalent wording, or a necessary supporting fact. '
         'Reject mere keyword overlap, unrelated subjects and claims that only say they are relevant.')

results = []
for qi in gap27:
    it = items[qi]
    q = it['query']
    ans = (it.get('pool') or it.get('candidates'))[it['answer']]
    contents = [c['content'] if isinstance(c, dict) else c for c in pools[qi]]
    runs = []
    for rep in range(3):
        scores = jev.judge_many({'query': q}, contents, INSTR)
        order = sorted(range(len(contents)), key=lambda i: -scores[i])
        rank = order.index(contents.index(ans)) + 1
        top_score = scores[order[0]]
        n_tie = sum(1 for s in scores if abs(s - top_score) < 1e-9)
        runs.append({'rank': rank, 'score_ans': round(scores[contents.index(ans)], 3),
                     'top_score': round(top_score, 3), 'ties_at_top': n_tie})
    ranks = [r['rank'] for r in runs]
    results.append({'idx': qi, 'dataset': it['dataset'], 'q': q[:40],
                    'ranks3': ranks, 'hit1_any': 1 in ranks, 'hit1_all': all(r == 1 for r in ranks),
                    'tie_rates': [r['ties_at_top'] for r in runs],
                    'scores_ans': [r['score_ans'] for r in runs],
                    'top_scores': [r['top_score'] for r in runs]})
    print(f"  idx={qi} {it['dataset']} ranks={ranks} ties={results[-1]['tie_rates']}", flush=True)

n_any = sum(1 for r in results if r['hit1_any'])
n_all = sum(1 for r in results if r['hit1_all'])
n_flaky = sum(1 for r in results if r['hit1_any'] and not r['hit1_all'])
n_never = sum(1 for r in results if not r['hit1_any'])
print()
print(f'=== 27건 3회 반복 결과 ===')
print(f'3회 모두 1위: {n_all}')
print(f'가끔 1위 (비결정성): {n_flaky}')
print(f'3회 전부 1위 실패 (결정적 실패): {n_never}')
print(f'→ 비결정성이 설명하는 건수: {n_flaky} / 결정적 문제: {n_never}')
json.dump(results, open(os.path.join(HERE, 'runC_repeat27.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('저장: runC_repeat27.json')