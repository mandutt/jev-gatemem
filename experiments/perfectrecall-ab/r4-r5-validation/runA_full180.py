"""Run A: 180쿼리 전수 — 현행 파이프라인 (pool + JEV relevance) 쿼리별 판정 저장
- pools_relaxed.json (RRF k60 풀, 평균 69) 사용 — 기존 0.556 실행과 동일 조건
- 목적: (1) hit@1/hit@5 쿼리별 확보 (2) PR과의 교차표 (3) 28건 불일치 식별
"""
import json, os, sys, time
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
print('KEY 로드:', 'OK' if KEY else 'FAIL', flush=True)

HERE = os.path.dirname(os.path.abspath(__file__))
SCRATCH = os.path.dirname(HERE)
items = json.load(open(os.path.join(SCRATCH, 'scratch_items.json'), encoding='utf-8'))
pools = json.load(open(os.path.join(SCRATCH, 'pools_relaxed.json'), encoding='utf-8'))

INSTR = ('Does candidate contain concrete information useful to answer state.query? '
         'Accept direct evidence, semantically equivalent wording, or a necessary supporting fact. '
         'Reject mere keyword overlap, unrelated subjects and claims that only say they are relevant.')

results = []
t0 = time.monotonic()
for qi, it in enumerate(items):
    q = it['query']
    cands = it.get('pool') or it.get('candidates')
    ans = cands[it['answer']]
    contents = [c['content'] if isinstance(c, dict) else c for c in pools[qi]]
    covered = ans in contents
    rec = {'idx': qi, 'dataset': it['dataset'], 'covered': covered}
    if covered:
        try:
            scores = jev.judge_many({'query': q}, contents, INSTR)
        except Exception as e:
            print(f'  idx={qi} JEV 오류: {e}', flush=True)
            rec.update({'hit1': 0, 'hit5': 0, 'rank': None, 'score_ans': None})
            results.append(rec); continue
        order = sorted(range(len(contents)), key=lambda i: -scores[i])
        rank = order.index(contents.index(ans)) + 1
        rec.update({'hit1': 1 if rank == 1 else 0, 'hit5': 1 if rank <= 5 else 0,
                    'rank': rank, 'score_ans': round(scores[contents.index(ans)], 3)})
    else:
        rec.update({'hit1': 0, 'hit5': 0, 'rank': None, 'score_ans': None})
    results.append(rec)
    if (qi + 1) % 30 == 0:
        done = [r for r in results if r['rank'] is not None]
        h1 = sum(r['hit1'] for r in done); h5 = sum(r['hit5'] for r in done)
        print(f'  {qi+1}/180 hit1={h1} hit5={h5} cov={sum(r["covered"] for r in results)} ({time.monotonic()-t0:.0f}s)', flush=True)

n = len(results)
cov = sum(r['covered'] for r in results)
judged = [r for r in results if r['rank'] is not None]
h1 = sum(r['hit1'] for r in judged); h5 = sum(r['hit5'] for r in judged)
m = jev.client().metrics
print()
print('=== Run A 결과 (pool + JEV relevance) ===')
print(f'Acc@1 = {h1}/180 = {h1/180:.3f}')
print(f'hit@5 = {h5}/180 = {h5/180:.3f}  (미커버 자동 0 포함)')
print(f'커버 내 hit@1 = {h1}/{cov} = {h1/cov:.3f}')
print(f'커버 내 hit@5 = {h5}/{cov} = {h5/cov:.3f}')
print(f'HTTP 요청={m.get("requests")} 입력토큰={m.get("input_tokens")} 출력토큰={m.get("output_tokens")} ${m.get("cost_usd")}')
json.dump(results, open(os.path.join(HERE, 'runA_perquery.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('저장: runA_perquery.json')