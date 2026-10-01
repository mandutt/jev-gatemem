"""PerfectRecall 평가 하네스 v2 (격리): full-corpus Jev _rank 직접 호출
- 같은 스크래치 DB(코퍼스 419) + 같은 쿼리 180
- _rank(query, corpus) = jev.relevance(query, texts) 전체 배치 — 내 rerank와 대칭
"""
import json, os, sys, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'perfectrecall'))

DB = sys.argv[1] if len(sys.argv) > 1 else 'C:/Users/mandu/AppData/Local/hermes/cache/scratch/scratch_eval.db'
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 0
HERE = 'C:/Users/mandu/AppData/Local/hermes/cache/scratch/perfectrecall'

from mnemosyne.core import jev, jev_recall
from mnemosyne.core.beam import BeamMemory

# PR은 env 기반 provider 설정 (typesafe + 내 키) — 내 구현과 동일 엔드포인트
os.environ['MNEMOSYNE_JEV_PROVIDER'] = 'typesafe'
# JevClient는 client() 게터로 lazy 생성 — env만 설정하면 된다
KEY = os.environ.get('TYPESAFE_API_KEY', '')
if not KEY:
    import re
    cands_env = [os.path.expandvars(p) for p in
                 ('%LOCALAPPDATA%/jev-mem/.env', '%LOCALAPPDATA%/jev-mem/bench/run-20261001-s4/.env',
                  '%USERPROFILE%/.config/jev-mem/.env')]
    for p in cands_env:
        if os.path.exists(p):
            for line in open(p, encoding='utf-8'):
                m = re.match(r'\s*TYPESAFE_API_KEY\s*=\s*(.+)', line)
                if m:
                    KEY = m.group(1).strip().strip('"\'')
                    break
        if KEY:
            break
os.environ['TYPESAFE_API_KEY'] = KEY
print('KEY 로드:', 'OK' if KEY else 'FAIL', flush=True)

def main():
    beam = BeamMemory(session_id='scratch-eval', db_path=DB)
    items = json.load(open(os.path.join(HERE, 'scratch_items.json'), encoding='utf-8'))
    if LIMIT:
        items = items[:LIMIT]
    print(f'쿼리: {len(items)}', flush=True)

    # 코퍼스 = visible_memories 전부 (PR full-scan)
    rows = list(jev_recall.visible_memories(beam, jev_recall._filters()))
    print(f'코퍼스 스팬: {len(rows)}', flush=True)

    accs, mrrs = [], []
    t_total, reqs_total = 0.0, 0
    t0_all = time.monotonic()
    for idx, it in enumerate(items):
        q = it['query']
        cands = it['pool'] if 'pool' in it else it['candidates']
        t0 = time.monotonic()
        try:
            ranked, scanned = jev_recall._rank(q, rows, threshold=0.0)  # cutoff 0 → 전부 후보 유지
        except Exception as e:
            print(f'  오류 idx={idx}: {e}', flush=True)
            ranked, scanned = [], len(rows)
        dt = time.monotonic() - t0
        t_total += dt
        # score 기반 후보 순위
        score_map = {r['content']: r['score'] for r in ranked}
        srt = sorted(cands, key=lambda c: -score_map.get(c, -1.0))
        rank = srt.index(cands[it['answer']]) + 1 if it['answer'] < len(cands) else len(cands)
        accs.append(1 if rank == 1 else 0)
        mrrs.append(1.0 / rank)
        reqs_total = jev.client().metrics['requests']
        if (idx + 1) % 30 == 0:
            print(f'  {idx+1}/{len(items)} acc={sum(accs)/len(accs):.3f} mrr={sum(mrrs)/len(mrrs):.3f} '
                  f't={t_total:.1f}s reqs={reqs_total}', flush=True)
    t_all = time.monotonic() - t0_all
    m = jev.client().metrics
    print(f'\n=== PR(_rank) 결과 ===')
    print(f'Acc@1: {sum(accs)/len(accs):.4f}')
    print(f'MRR:   {sum(mrrs)/len(mrrs):.4f}')
    print(f'총: {t_all:.1f}s ({t_all/len(items):.2f}s/쿼리)')
    print(f'요청: {m.get("requests")} / 캐시: {m.get("cache_hits")} / 실패: {m.get("failures")} / $: {m.get("cost_usd")}')
    out = {'engine': 'perfectrecall', 'n': len(items), 'corpus': len(rows),
           'acc1': sum(accs)/len(accs), 'mrr': sum(mrrs)/len(mrrs),
           'total_s': round(t_all, 1), 'per_query_s': round(t_all/len(items), 2),
           'jev_requests': m.get('requests'), 'cache_hits': m.get('cache_hits'),
           'cost_usd': m.get('cost_usd')}
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pr_result.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print('저장: pr_result.json')

if __name__ == '__main__':
    main()