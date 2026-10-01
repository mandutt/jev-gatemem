"""Run D: 스캔 범위 모순의 직접 검증
같은 쿼리에 대해 (1) 풀 69개만 판정 (2) 전체 419 판정 → 정답 점수/순위 비교
샘플: 27건 중 대표 8건 (랭크 다양)
가설 검증: 419 스캔에서 정답 점수가 더 높게 나오는가? (점수 자체가 스캔 크기에 의존?)
"""
import json, os, sys, re
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
runC = json.load(open(os.path.join(HERE, 'runC_repeat27.json'), encoding='utf-8'))
runA = json.load(open(os.path.join(HERE, 'runA_perquery.json'), encoding='utf-8'))

# 코퍼스 419 (working_memory 전체 content)
import sqlite3
con = sqlite3.connect('C:/Users/mandu/AppData/Local/hermes/cache/scratch/scratch_eval.db')
corpus = [r[0] for r in con.execute('SELECT content FROM working_memory').fetchall()]
con.close()
print(f'코퍼스: {len(corpus)}', flush=True)

SAMPLE = [r['idx'] for r in runC[:8]]  # 앞 8건
INSTR = ('Does candidate contain concrete information useful to answer state.query? '
         'Accept direct evidence, semantically equivalent wording, or a necessary supporting fact. '
         'Reject mere keyword overlap, unrelated subjects and claims that only say they are relevant.')

out = []
for qi in SAMPLE:
    it = items[qi]
    q = it['query']
    ans = (it.get('pool') or it.get('candidates'))[it['answer']]
    contents = [c['content'] if isinstance(c, dict) else c for c in pools[qi]]

    # (1) 풀만 판정
    s_pool = jev.judge_many({'query': q}, contents, INSTR)
    order_pool = sorted(range(len(contents)), key=lambda i: -s_pool[i])
    rank_pool = order_pool.index(contents.index(ans)) + 1
    score_pool = s_pool[contents.index(ans)]
    top1_pool_score = s_pool[order_pool[0]]
    top1_pool = contents[order_pool[0]][:40]

    # (2) 전체 419 판정
    s_full = jev.judge_many({'query': q}, corpus, INSTR)
    order_full = sorted(range(len(corpus)), key=lambda i: -s_full[i])
    rank_full = order_full.index(corpus.index(ans)) + 1
    score_full = s_full[corpus.index(ans)]
    top1_full_score = s_full[order_full[0]]
    top1_full = corpus[order_full[0]][:40]

    out.append({'idx': qi, 'dataset': it['dataset'], 'q': q[:40],
                'rank_pool': rank_pool, 'score_pool': round(score_pool, 3),
                'rank_full': rank_full, 'score_full': round(score_full, 3),
                'top1_pool': top1_pool, 'top1_full': top1_full,
                'top1_score_pool': round(top1_pool_score, 3), 'top1_score_full': round(top1_full_score, 3)})
    print(f"idx={qi} {it['dataset']}: 풀 rank={rank_pool}(score {score_pool:.2f}) vs 419 rank={rank_full}(score {score_full:.2f})", flush=True)
    print(f"   풀 top1: {top1_pool} ({top1_pool_score:.2f}) | 419 top1: {top1_full} ({top1_full_score:.2f})", flush=True)

json.dump(out, open(os.path.join(HERE, 'runD_scope8.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('저장: runD_scope8.json')