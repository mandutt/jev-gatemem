"""Gate 스윕: min_distinctive x min_coverage → 회수 품질/노이즈 (Jev 없음, $0)
- 풀은 1회만 계산(임베딩 비용 절약), 게이트 파라미터만 바꿔 재평가
- 스크래치 DB 419 스팬, 쿼리 180
실행: [jev-mem venv] python gate_sweep.py  (cwd=scratch 루트)
"""
import sys, json, time
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'C:/Users/mandu/hermes-made/jev-memory-middleware')

DB = 'C:/Users/mandu/AppData/Local/hermes/cache/scratch/scratch_eval.db'
ITEMS = 'C:/Users/mandu/AppData/Local/hermes/cache/scratch/perfectrecall/scratch_items.json'
OUT = 'C:/Users/mandu/AppData/Local/hermes/cache/scratch/gate_sweep_nogev.json'

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

t0 = time.monotonic()
print('pool 사전계산(180쿼리, 1회)...', flush=True)
pools = [j1p.build_lane_pool(recall_raw, it['query']) for it in items]
print(f'완료 {time.monotonic()-t0:.1f}s, 평균 pool={sum(len(p) for p in pools)/len(pools):.1f}', flush=True)

def evaluate(md, mc):
    rows = []
    for it, pool in zip(items, pools):
        cands = it['pool'] if 'pool' in it else it['candidates']
        ans = cands[it['answer']]
        filt = j1p._filter_and_rank(pool, it['query'], min_distinctive=md, min_coverage=mc) if pool else []
        contents = [r.get('content', '') for r in filt]
        covered = ans in contents
        rank = (contents.index(ans) + 1) if covered else len(filt) + 1
        rows.append((it['dataset'].split('/')[0], 1 if rank == 1 else 0, 1.0 / rank, covered, len(filt)))
    n = len(rows)
    per = defaultdict(lambda: {'n': 0, 'acc': 0, 'cov': 0, 'size': 0})
    for ds, a, m, c, s in rows:
        per[ds]['n'] += 1; per[ds]['acc'] += a; per[ds]['cov'] += c; per[ds]['size'] += s
    return dict(acc=sum(r[1] for r in rows) / n, mrr=sum(r[2] for r in rows) / n,
                cov=sum(r[3] for r in rows), n=n, size=sum(r[4] for r in rows) / n,
                per={k: dict(v) for k, v in per.items()})

variants = [(2, 0.30), (1, 0.30), (2, 0.15), (1, 0.15), (1, 0.0), (0, 0.0)]
results = {}
for md, mc in variants:
    r = evaluate(md, mc)
    results[f'{md}/{mc}'] = r
    print(f'\n=== md={md} mc={mc}: Acc@1={r["acc"]:.4f} MRR={r["mrr"]:.4f} cov={r["cov"]}/{r["n"]} ({r["cov"]/r["n"]*100:.1f}%) pool={r["size"]:.1f}', flush=True)
    for ds, v in sorted(r['per'].items()):
        print(f'    {ds:15s} acc={v["acc"]/v["n"]:.3f} cov={v["cov"]}/{v["n"]} pool={v["size"]/v["n"]:.1f}', flush=True)

json.dump(results, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print(f'\n저장: {OUT}')