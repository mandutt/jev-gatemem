"""게이트 완화(mc=0.0) + Jev rerank — 180쿼리 전체 (요청 180)
- _filter_and_rank(pool, q, min_distinctive=1, min_coverage=0.0) — 게이트 최소화
- jev_rerank choice — 커버된 풀에서 1위 lift
"""
import sys, json, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'C:/Users/mandu/hermes-made/jev-memory-middleware')

DB = 'C:/Users/mandu/AppData/Local/hermes/cache/scratch/scratch_eval.db'
ITEMS = 'C:/Users/mandu/AppData/Local/hermes/cache/scratch/perfectrecall/scratch_items.json'

from mnemosyne.core.beam import BeamMemory
import mnemosyne.core.beam as beam_mod
from gateway import j1_pipeline as j1p
from core import j1_engine

beam = BeamMemory(session_id='scratch-eval', db_path=DB)
items = json.load(open(ITEMS, encoding='utf-8'))

def recall_raw(kind, arg, k):
    if kind == 'fts':
        return beam_mod._fts_search_working(beam.conn, arg, k=k)
    if kind == 'vec':
        emb = beam_mod._embeddings.embed([arg])
        if not len(emb):
            return []
        return beam_mod._wm_vec_search(beam.conn, emb[0], k=k)
    if kind == 'imp':
        return j1p._imp_search(beam.conn, k=k)
    if kind == 'graph':
        return j1p._graph_lane_search(beam.conn, arg, k=k)
    if kind == 'get':
        return j1_engine.hydration_get(beam, arg)
    return []

class _Client:
    def __init__(self, key):
        import httpx
        self._h = httpx.Client(headers={'Authorization': f'Bearer {key}'}, timeout=20)
        self.calls = 0
    def post(self, url, json=None, timeout=None):
        self.calls += 1
        return self._h.post(url, json=json, timeout=timeout or 20)
    def close(self):
        self._h.close()

# KEY
import os, re
KEY = os.environ.get('TYPESAFE_API_KEY', '')
if not KEY:
    for p in [os.path.expandvars('%LOCALAPPDATA%/jev-mem/.env'),
              os.path.expandvars('%LOCALAPPDATA%/jev-mem/bench/run-20261001-s4/.env')]:
        if os.path.exists(p):
            for line in open(p, encoding='utf-8'):
                m = re.match(r'\s*TYPESAFE_API_KEY\s*=\s*(.+)', line)
                if m:
                    KEY = m.group(1).strip().strip('"\'')
                    break
        if KEY:
            break
print('KEY:', 'OK' if KEY else 'FAIL', flush=True)
client = _Client(KEY)

accs, mrrs, covers = [], [], []
t0 = time.monotonic()
for idx, it in enumerate(items):
    q, cands = it['query'], (it['pool'] if 'pool' in it else it['candidates'])
    ans = cands[it['answer']]
    pool = j1p.build_lane_pool(recall_raw, q)
    filt = j1p._filter_and_rank(pool, q, min_distinctive=1, min_coverage=0.0) if pool else []
    rows = j1p.jev_rerank(query=q, pool=filt, client=client, call_jev=True, timeout=8.0)
    contents = [r.get('content', '') for r in rows]
    covered = ans in contents
    rank = (contents.index(ans) + 1) if covered else len(contents) + 1
    accs.append(1 if rank == 1 else 0)
    mrrs.append(1.0 / rank)
    covers.append(covered)
    if (idx + 1) % 60 == 0:
        print(f'  {idx+1}/{len(items)} acc={sum(accs)/len(accs):.3f} mrr={sum(mrrs)/len(mrrs):.3f} cov={sum(covers)}/{idx+1}', flush=True)

n = len(items)
print(f'\n=== 게이트 완화(md=1, mc=0) + Jev rerank — 180쿼리 ===')
print(f'Acc@1: {sum(accs)/n:.4f}  MRR: {sum(mrrs)/n:.4f}  정답커버: {sum(covers)}/{n} ({sum(covers)/n*100:.1f}%)')
print(f'Jev 요청: {client.calls}  총 {time.monotonic()-t0:.1f}s')

# 데이터셋별
from collections import defaultdict
per = defaultdict(lambda: [0, 0, 0])
for it, a, m, c in zip(items, accs, mrrs, covers):
    ds = it['dataset'].split('/')[0]
    per[ds][0] += a; per[ds][1] += m; per[ds][2] += c
for ds, (a, m, c) in sorted(per.items()):
    nn = sum(1 for it in items if it['dataset'].split('/')[0] == ds)
    print(f'  {ds:15s} Acc@1={a/nn:.3f} MRR={m/nn:.3f} cov={c}/{nn}')

out = {'engine': 'mine-gate-relaxed', 'n': n, 'acc1': sum(accs)/n, 'mrr': sum(mrrs)/n,
       'cov': sum(covers), 'jev_calls': client.calls, 'total_s': round(time.monotonic()-t0, 1)}
json.dump(out, open('C:/Users/mandu/AppData/Local/hermes/cache/scratch/gate_relaxed_jev.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print('저장: gate_relaxed_jev.json')