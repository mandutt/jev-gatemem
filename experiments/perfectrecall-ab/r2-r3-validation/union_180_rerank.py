"""union 풀 180쿼리 + Jev relevance rerank — PR venv (MNEMOSYNE_JEV_PROVIDER=typesafe)
- baseline: RRF k=60 + relevance (controlled_relevance 0.556) / RRF + choice (gate_relaxed 0.539)
- 비교: union (vec60+fts20+graph10+imp10) + relevance — 동일 프롬프트
- 메트릭: Acc@1 / MRR / 커버 / 토큰 / 요청
"""
import sys, os, json, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'C:/Users/mandu/AppData/Local/hermes/cache/scratch/perfectrecall')
os.environ['MNEMOSYNE_JEV_PROVIDER'] = 'typesafe'
from mnemosyne.core import jev
from mnemosyne.core.jev import judge_many

items = json.load(open('C:/Users/mandu/AppData/Local/hermes/cache/scratch/perfectrecall/scratch_items.json', encoding='utf-8'))
u = json.load(open('C:/Users/mandu/AppData/Local/hermes/cache/scratch/union_pools_180.json', encoding='utf-8'))
pools = {int(k): v for k, v in u['pools'].items()}

INSTR = ('Does candidate contain concrete information useful to answer state.query? '
         'Accept direct evidence, semantically equivalent wording, or a necessary supporting fact. '
         'Reject mere keyword overlap, unrelated subjects and claims that only say they are relevant.')

accs, mrrs, covers = [], [], []
t0 = time.monotonic()
for idx, it in enumerate(items):
    q, cands = it['query'], (it['pool'] if 'pool' in it else it['candidates'])
    ans = cands[it['answer']]
    contents = [c for c in pools[idx] if c]
    covered = ans in contents
    covers.append(covered)
    if not contents or not covered:
        accs.append(0); mrrs.append(0); continue
    scores = judge_many({'query': q}, contents, INSTR)
    order = sorted(range(len(contents)), key=lambda i: -scores[i])
    rank = order.index(contents.index(ans)) + 1
    accs.append(1 if rank == 1 else 0)
    mrrs.append(1.0 / rank)
    if (idx + 1) % 60 == 0:
        m = jev.client().metrics
        print(f'  {idx+1}/180 acc={sum(accs)/len(accs):.3f} cov={sum(covers)}/{idx+1} req={m.get("requests")} in_tok={m.get("input_tokens")} ({time.monotonic()-t0:.0f}s)', flush=True)

n = len(accs)
m = jev.client().metrics
print(f'\\n=== union(180) + relevance ===')
print(f'Acc@1={sum(accs)/n:.4f} MRR={sum(mrrs)/n:.4f} 커버={sum(covers)}/{n} ({sum(covers)/n*100:.1f}%)')
print(f'  HTTP 요청={m.get("requests")}  입력토큰={m.get("input_tokens")}  출력토큰={m.get("output_tokens")}  비용=${m.get("cost_usd")}')
out = {'engine': 'union-180-relevance', 'n': n, 'acc1': sum(accs)/n, 'mrr': sum(mrrs)/n,
       'cov': sum(covers), 'requests': m.get('requests'), 'input_tokens': m.get('input_tokens'),
       'output_tokens': m.get('output_tokens'), 'cost_usd': m.get('cost_usd'),
       'total_s': round(time.monotonic()-t0, 1)}
json.dump(out, open('C:/Users/mandu/AppData/Local/hermes/cache/scratch/union_180_result.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print('저장: union_180_result.json')