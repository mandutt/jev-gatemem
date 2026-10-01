"""union 풀 생성 (180쿼리 전체) — 내 venv
vec top-60 + FTS top-20 + graph top-10 + importance top-10 단순 union/dedupe (게이트 완화)
- RRF k=60 현행 (gate_relaxed_jev 0.539)과 동일 조건: 같은 lane 예산, 같은 쿼리 180
- union_pools_180.json 저장
"""
import sys, json, sqlite3
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
conn = sqlite3.connect(DB)
content_by_id = {r[0]: r[1] for r in conn.execute('SELECT id, content FROM working_memory')}
conn.close()

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
        return None  # union 풀은 아이디 기반이라 hydration 불필요
    return []

union_pools = {}
sizes = []
for i, it in enumerate(items):
    q = it['query']
    ids, contents = [], []
    for kind, k in [('vec', 60), ('fts', 20), ('graph', 10), ('imp', 10)]:
        try:
            for r in recall_raw(kind, q, k):
                rid = r.get('id')
                if rid and rid not in ids:
                    ids.append(rid)
                    contents.append(content_by_id.get(rid, ''))
        except Exception:
            continue
    union_pools[i] = contents
    sizes.append(len(contents))

json.dump({'pools': {str(k): v for k, v in union_pools.items()}},
          open('C:/Users/mandu/AppData/Local/hermes/cache/scratch/union_pools_180.json', 'w', encoding='utf-8'),
          ensure_ascii=False)
print(f'union 풀 180쿼리 저장 완료')
print(f'평균 풀 크기: {sum(sizes)/len(sizes):.1f} (min {min(sizes)}, max {max(sizes)})')
print(f'전체 후보: {sum(sizes)}')