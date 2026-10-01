"""운영 골든셋 평가 (Run G) — stage1 풀 재현 + /v1/prefetch (라이브 데몬)

측정 축 (AI 리뷰 합의안):
- Top-40 Pool Recall: 정답 id가 stage1 풀(40)에 들어오는가
- 무답 오주입률: NO_ANSWER 쿼리에서 prefetch 반환 여부
- hit@5/MRR은 JEV choice가 top1 lift이므로 pool에서 정답 순위 + rerank pick으로 측정

실행: jev-mem venv에서. scratch의 PR clone mnemosyne/ shadowing 방지 위해
sys.path에서 cwd 제거 후 repo 루트 삽입.
"""
import json, os, sys, time

os.chdir("C:/Users/mandu/AppData/Local/hermes/cache/scratch/perfectrecall")
for p in list(sys.path):
    if p in ("", ".", os.getcwd()): sys.path.remove(p)
sys.path.insert(0, "C:/Users/mandu/hermes-made/jev-memory-middleware")
os.environ.setdefault("MNEMOSYNE_DB", os.path.expandvars(r"%LOCALAPPDATA%/hermes/mnemosyne/data/mnemosyne.db"))

import urllib.request
import mnemosyne.core.beam as bm
from mnemosyne.core import embeddings as emb_mod
import gateway.j1_pipeline as j1p
from core import j1_engine

JEV = "http://127.0.0.1:47821"
TOKEN = open(os.path.expandvars(r'%LOCALAPPDATA%/jev-mem/token')).read().strip()

def prefetch(query):
    req = urllib.request.Request(JEV + "/v1/prefetch",
        data=json.dumps({"agent": "golden-eval", "query": query[:8000],
                         "options": {"rerank": True, "max_chars": 0}}).encode('utf-8'),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))

_b = None
def get_beam():
    global _b
    if _b is None:
        _b = bm.BeamMemory(session_id='golden-eval')
    return _b

def recall_raw(kind, arg, k_):
    b = get_beam()
    if kind == "fts": return bm._fts_search_working(b.conn, arg, k=k_)
    if kind == "vec":
        e = emb_mod.embed([arg])
        if e is None or not len(e): return []
        return bm._wm_vec_search(b.conn, e[0], k=k_)
    if kind == "imp": return j1p._imp_search(b.conn, k=k_)
    if kind == "graph": return j1p._graph_lane_search(b.conn, arg, k=k_)
    if kind == "get":
        row = j1_engine.hydration_get(b, arg)
        return row if isinstance(row, dict) else None
    return []

def stage1_rank(query, k=40):
    pool = j1p.build_lane_pool(recall_raw, query)
    ranked = j1p._filter_and_rank(pool, query) if pool else []
    return ranked[:k]

def main():
    queries = json.load(open(sys.argv[1] if len(sys.argv) > 1 else 'golden_final.json', encoding='utf-8'))
    results = []
    t0 = time.time()
    for i, q in enumerate(queries, 1):
        axis = 'NO_ANSWER' if q['cat'] == 'NO_ANSWER' else q['cat']
        for axis_name, qtext in (('literal', q['query_literal']),
                                 ('paraphrase', q['query_paraphrase'])):
            if axis == 'NO_ANSWER' and axis_name == 'paraphrase':
                continue  # 무답은 1회만
            gold_id = q['id'] if axis != 'NO_ANSWER' else None
            try:
                t1 = time.time()
                pool = stage1_rank(qtext, k=40)
                ids = [str(r.get('id', '')) for r in pool]
                rank = ids.index(gold_id) + 1 if gold_id in ids else None
                # prefetch (라이브 데몬, JEV rerank 포함)
                pr = prefetch(qtext)
                meta = pr.get('meta', {})
                results.append({
                    'gold_id': gold_id, 'cat': axis, 'axis': axis_name,
                    'query': qtext, 'pool_size': len(pool),
                    'pool_rank': rank, 'pool_latency_ms': round((time.time()-t1)*1000),
                    'prefetch_rerank': meta.get('rerank'),
                    'prefetch_degraded': meta.get('degraded'),
                    'prefetch_latency_ms': meta.get('latency_ms'),
                })
            except Exception as e:
                results.append({'gold_id': gold_id, 'cat': axis, 'axis': axis_name,
                                'query': qtext, 'error': repr(e)[:150]})
        if i % 10 == 0:
            print(f"  {i}/{len(queries)} ({time.time()-t0:.0f}s)", flush=True)
    json.dump(results, open('golden_eval_results.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    # 집계
    ok = [r for r in results if 'error' not in r]
    gold = [r for r in ok if r['cat'] != 'NO_ANSWER']
    na = [r for r in ok if r['cat'] == 'NO_ANSWER']
    import statistics
    def pct(x): return f"{100*x:.1f}%"
    pool_hits = [r for r in gold if r['pool_rank'] is not None]
    hit5 = [r for r in gold if r['pool_rank'] is not None and r['pool_rank'] <= 5]
    rr = [1/r['pool_rank'] for r in gold if r['pool_rank'] is not None]
    print(f"\n=== 골든셋 결과 (n={len(gold)} gold + {len(na)} no-answer) ===")
    print(f"Top-40 Pool Recall: {pct(len(pool_hits)/len(gold))}")
    print(f"Pool hit@5: {pct(len(hit5)/len(gold))}")
    print(f"Pool MRR: {statistics.mean(rr):.3f}" if rr else "MRR: n/a")
    if na:
        # 무답 쿼리에서 풀이 비어있거나 매우 작으면 오주입 아님
        injected = [r for r in na if (r['pool_size'] or 0) > 5]
        print(f"무답 오주입률 (풀>5): {pct(len(injected)/len(na))}")
    lat = [r['prefetch_latency_ms'] for r in ok if r.get('prefetch_latency_ms')]
    if lat:
        lat.sort()
        print(f"prefetch p50: {lat[len(lat)//2]}ms / p95: {lat[int(len(lat)*0.95)]}ms")

if __name__ == '__main__':
    main()