"""Run M 시뮬: Pool 탈락 9건(90→100% 커버리지)의 vec_rank 분포 + 예외 확장 시뮬레이션 (JEV 0회)

- Run J 골든셋 90 gold 쿼리를 라이브 DB에서 로컬 재현 (bench_regression_sweep.py 방식)
- 탈락 9건의 vec_rank / fts_rank / dist를 찾아 예외 확장(vec≤3, vec≤5, 무조건 vec상위k)이
  몇 건을 회복하는지 계산
"""
import json, os, sys
os.chdir("C:/Users/mandu/AppData/Local/hermes/cache/scratch/perfectrecall")
for p in list(sys.path):
    if p in ("", ".", os.getcwd()): sys.path.remove(p)
sys.path.insert(0, "C:/Users/mandu/hermes-made/jev-memory-middleware")
sys.stdout.reconfigure(encoding='utf-8')

from mnemosyne.core.beam import BeamMemory
import mnemosyne.core.beam as beam_mod
from gateway import j1_pipeline as j1p

DB = "C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
beam = BeamMemory(session_id='run-m-sim', db_path=DB)
# 운영 전체 코퍼스 (cross-session은 골든셋 gold들이 여러 세션에 분산)
queries = json.load(open('golden_final_v2.json', encoding='utf-8'))
# gold id → content 매핑 (working_memory)
import sqlite3
con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
id2content = {r[0]: r[1] for r in con.execute("SELECT id, content FROM working_memory")}
id2content.update({r[0]: r[1] for r in con.execute("SELECT id, content FROM episodic_memory")})
con.close()

def recall_raw(kind, arg, k):
    if kind == "fts":
        return beam_mod._fts_search_working(beam.conn, arg, k=k)
    if kind == "vec":
        emb = beam_mod._embeddings.embed([arg])
        if emb is None or not len(emb): return []
        return beam_mod._wm_vec_search(beam.conn, emb[0], k=k)
    if kind == "imp":
        return j1p._imp_search(beam.conn, k=k)
    if kind == "graph":
        return j1p._graph_lane_search(beam.conn, arg, k=k)
    if kind == "get":
        return {"id": arg, "content": id2content.get(arg, "")} if arg in id2content else None
    return []

saved = j1p.VEC_RANK_EXEMPT
j1p.VEC_RANK_EXEMPT = 2  # 현행
miss = []
for q in queries:
    if q['cat'] == 'NO_ANSWER':
        continue
    gold = q['id']
    for axis, qtext in (('literal', q['query_literal']), ('paraphrase', q['query_paraphrase'])):
        pool = j1p.build_lane_pool(recall_raw, qtext)
        rows = j1p._filter_and_rank(list(pool), qtext)
        # 골드 행 매칭 (content 기준 — Run J 방식)
        gold_content = " ".join((id2content.get(gold) or "").split())
        rank = None
        for i, r in enumerate(rows, 1):
            c = " ".join((r.get("content") or "").split())
            if c == gold_content or (gold_content in c and len(gold_content) > 10):
                rank = i; break
        if rank is None:
            # 탈락 — lane_ranks에서 vec_rank 등 확인
            gold_rows = [r for r in pool if " ".join((r.get("content") or "").split()) == gold_content
                         or (gold_content in (r.get("content") or "") and len(gold_content) > 10)]
            info = {'cat': q['cat'], 'axis': axis, 'query': qtext[:50], 'pool_n': len(rows)}
            if gold_rows:
                gr = gold_rows[0]
                lr = gr.get('_lane_ranks') or {}
                info.update({'vec_rank': lr.get('vec_rank'), 'fts_rank': lr.get('fts_rank'),
                             'imp_rank': lr.get('imp_rank'), 'graph_rank': lr.get('graph_rank'),
                             'dist': gr.get('dist'), 'coverage': gr.get('coverage'),
                             'overlap': len(gr.get('overlap_tokens') or []) if isinstance(gr.get('overlap_tokens'), (list, set)) else gr.get('overlap')})
            else:
                info['in_lane_pool'] = False
                # vec lane top-k 안에 있는지: raw vec 검색에서 gold content 찾기
                emb = beam_mod._embeddings.embed([qtext])
                vec = beam_mod._wm_vec_search(beam.conn, emb[0], k=60) if emb is not None and len(emb) else []
                for i, v in enumerate(vec, 1):
                    vid = v.get('id') if isinstance(v, dict) else v[0]
                    vc = " ".join((id2content.get(vid) or "").split())
                    if vc == gold_content:
                        info['vec_raw_rank_k60'] = i
                        break
            miss.append(info)
j1p.VEC_RANK_EXEMPT = saved

print(f"=== Run M: 탈락 {len(miss)}건 (90 gold 쿼리 × 2축) ===\n")
for m in miss:
    print(m)
# 예외 확장 시뮬
print("\n=== 예외 확장 시뮬 ===")
recov = lambda maxvr: sum(1 for m in miss if m.get('vec_rank') is not None and m['vec_rank'] <= maxvr and (m.get('dist') is None or m.get('dist', 0) >= 0))
print(f"vec≤3 확장: {recov(3)}/{len(miss)} 회복")
print(f"vec≤5 확장: {recov(5)}/{len(miss)} 회복")
print(f"vec≤10 확장: {recov(10)}/{len(miss)} 회복")
raw = sum(1 for m in miss if m.get('vec_raw_rank_k60'))
print(f"vec lane top-60 내부(레인 자체 미달): {raw}/{len(miss)}")
