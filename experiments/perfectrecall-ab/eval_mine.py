"""내 구현(jev-memory-middleware) 평가 하네스 (격리)
- 같은 스크래치 DB(코퍼스 419) + 같은 쿼리 180
- pipeline._retrieve + _rerank 그대로 (lane pool + Jev choice rerank)
- PR(_rank full-scan)과 동등 조건: 동일 키/엔드포인트
"""
import json, os, sys, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'C:/Users/mandu/hermes-made/jev-memory-middleware')
# 주의: PR 클론 경로를 sys.path에 넣지 않는다 — 내 venv site-packages의 mnemosyne를 쓴다.

DB = sys.argv[1] if len(sys.argv) > 1 else 'C:/Users/mandu/AppData/Local/hermes/cache/scratch/scratch_eval.db'
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 0
HERE = 'C:/Users/mandu/AppData/Local/hermes/cache/scratch/perfectrecall'

from mnemosyne.core.beam import BeamMemory
import mnemosyne.core.beam as beam_mod
from gateway import j1_pipeline as j1p

# 내 j1_engine typesafe_client (기존 키 사용)
sys.path.insert(0, 'C:/Users/mandu/hermes-made/jev-memory-middleware/core')
from core import j1_engine
KEY = os.environ.get('TYPESAFE_API_KEY', '')
if not KEY:
    import re
    for p in [os.path.expandvars('%LOCALAPPDATA%/jev-mem/.env'),
              os.path.expandvars('%LOCALAPPDATA%/jev-mem/bench/run-20261001-s4/.env'),
              os.path.expandvars('%USERPROFILE%/.config/jev-mem/.env')]:
        if os.path.exists(p):
            for line in open(p, encoding='utf-8'):
                m = re.match(r'\s*TYPESAFE_API_KEY\s*=\s*(.+)', line)
                if m:
                    KEY = m.group(1).strip().strip('"\'')
                    break
        if KEY:
            break
print('KEY 로드:', 'OK' if KEY else 'FAIL', flush=True)

class _Client:
    """내 파이프라인이 쓰는 httpx 클라이언트 (j1_engine.typesafe_client 대체)."""
    def __init__(self, key):
        import httpx
        self._h = httpx.Client(headers={'Authorization': f'Bearer {key}'}, timeout=20)
        self.calls = 0
    def post(self, url, json=None, timeout=None):
        self.calls += 1
        return self._h.post(url, json=json, timeout=timeout or 20)
    def close(self):
        self._h.close()

def main():
    beam = BeamMemory(session_id='scratch-eval', db_path=DB)
    items = json.load(open(os.path.join(HERE, 'scratch_items.json'), encoding='utf-8'))
    if LIMIT:
        items = items[:LIMIT]
    print(f'쿼리: {len(items)}', flush=True)

    client = _Client(KEY)
    # 임베딩: a8m (내 구현 S4 모델) — mnemosyne core가 로드 (스크래치 venv엔 없으면 로드 시도)
    # lane vec에 필요. a8m이 없으면 vec lane은 빈 결과 (FTS/imp/graph로 진행)

    accs, mrrs = [], []
    t_total = 0.0
    t0_all = time.monotonic()
    for idx, it in enumerate(items):
        q = it['query']
        cands = it['pool'] if 'pool' in it else it['candidates']
        t0 = time.monotonic()
        try:
            rows = _retrieve(beam, q)
            if idx < 5:
                ans = cands[it['answer']]
                contents = [r.get('content','') for r in rows]
                print(f'  [진단 {idx}] {it["dataset"]} pool={len(rows)} ans_in={ans in contents}', flush=True)
            rows, _ = j1p.jev_rerank(query=q, pool=rows, client=client,
                                     call_jev=True, timeout=8.0)
        except Exception as e:
            print(f'  오류 idx={idx}: {e}', flush=True)
            rows = []
        dt = time.monotonic() - t0
        t_total += dt
        # rows(회수+rerank)에서 후보 순위 — pool에 없으면 rank = len+1
        order = [r['content'] for r in rows]
        try:
            rank = order.index(cands[it['answer']]) + 1
        except ValueError:
            rank = len(order) + 1
        accs.append(1 if rank == 1 else 0)
        mrrs.append(1.0 / rank if rank else 0.0)
        if (idx + 1) % 30 == 0:
            print(f'  {idx+1}/{len(items)} acc={sum(accs)/len(accs):.3f} mrr={sum(mrrs)/len(mrrs):.3f} '
                  f't={t_total:.1f}s jev_calls={client.calls}', flush=True)
    t_all = time.monotonic() - t0_all
    print(f'\n=== 내 구현 결과 ===')
    print(f'Acc@1: {sum(accs)/len(accs):.4f}')
    print(f'MRR:   {sum(mrrs)/len(mrrs):.4f}')
    print(f'총: {t_all:.1f}s ({t_all/len(items):.2f}s/쿼리)')
    print(f'Jev 호출: {client.calls}')
    out = {'engine': 'mine', 'n': len(items), 'corpus': 419,
           'acc1': sum(accs)/len(accs), 'mrr': sum(mrrs)/len(mrrs),
           'total_s': round(t_all, 1), 'per_query_s': round(t_all/len(items), 2),
           'jev_requests': client.calls}
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mine_result.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print('저장: mine_result.json')

def _retrieve(beam, query):
    """pipeline._retrieve와 동일 로직 (스크래치 beam 바인딩)."""
    from gateway import j1_pipeline as j1p
    from core import j1_engine

    def recall_raw(kind, arg, k):
        if kind == 'fts':
            return beam_mod._fts_search_working(beam.conn, arg, k=k)
        if kind == 'vec':
            try:
                emb = beam_mod._embeddings.embed([arg])
            except Exception:
                emb = None
            if emb is None or not len(emb):
                return []
            return beam_mod._wm_vec_search(beam.conn, emb[0], k=k)
        if kind == 'imp':
            return j1p._imp_search(beam.conn, k=k)
        if kind == 'graph':
            return j1p._graph_lane_search(beam.conn, arg, k=k)
        if kind == 'get':
            try:
                return j1_engine.hydration_get(beam, arg)
            except Exception:
                return None
        return []

    pool = j1p.build_lane_pool(recall_raw, query)
    return j1p._filter_and_rank(pool, query) if pool else []

if __name__ == '__main__':
    main()