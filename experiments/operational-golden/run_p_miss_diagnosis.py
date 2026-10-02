"""Run P — 잔여 미스 원인 진단: 게이트 문제 vs 임베딩 품질 문제 분리 (JEV 0회)
Run M(9건) 이후 미스를 게이트-이전 vec raw rank(k=100)까지 추적해 분류한다.
"""
import json, os, sys
os.chdir("C:/Users/mandu/AppData/Local/hermes/cache/scratch/perfectrecall")
for p in list(sys.path):
    if p in ("", ".", os.getcwd()): sys.path.remove(p)
sys.path.insert(0, "C:/Users/mandu/hermes-made/jev-memory-middleware")

from mnemosyne.core.beam import BeamMemory
import mnemosyne.core.beam as beam_mod
from gateway import j1_pipeline as j1p

DB = "C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
beam = BeamMemory(session_id='run-p-diag', db_path=DB)
queries = json.load(open('golden_final_v2.json', encoding='utf-8'))
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

def gold_match(c, gold_content):
    c = " ".join((c or "").split())
    return c == gold_content or (gold_content in c and len(gold_content) > 10)

miss = []
total = 0
saved = j1p.VEC_RANK_EXEMPT
j1p.VEC_RANK_EXEMPT = 2
for q in queries:
    if q['cat'] == 'NO_ANSWER':
        continue
    gold = q['id']
    gold_content = " ".join((id2content.get(gold) or "").split())
    for axis, qtext in (('literal', q['query_literal']), ('paraphrase', q['query_paraphrase'])):
        total += 1
        pool = j1p.build_lane_pool(recall_raw, qtext)
        rows = j1p._filter_and_rank(list(pool), qtext)
        rank = next((i for i, r in enumerate(rows, 1) if gold_match(r.get("content"), gold_content)), None)
        if rank is None:
            info = {'cat': q['cat'], 'axis': axis, 'query': qtext[:40], 'pool_n': len(rows)}
            gold_rows = [r for r in pool if gold_match(r.get("content"), gold_content)]
            if gold_rows:
                gr = gold_rows[0]
                lr = gr.get('_lane_ranks') or {}
                info.update({'vec_rank': lr.get('vec_rank'), 'fts_rank': lr.get('fts_rank'),
                             'imp_rank': lr.get('imp_rank'), 'graph_rank': lr.get('graph_rank'),
                             'dist': gr.get('dist'), 'coverage': round(gr.get('coverage', -1), 3),
                             'overlap': len(gr.get('overlap_tokens') or []) if isinstance(gr.get('overlap_tokens'), (list, set)) else gr.get('overlap')})
            else:
                info['in_lane_pool'] = False
                emb = beam_mod._embeddings.embed([qtext])
                vec = beam_mod._wm_vec_search(beam.conn, emb[0], k=100) if emb is not None and len(emb) else []
                for i, v in enumerate(vec, 1):
                    vid = v.get('id') if isinstance(v, dict) else v[0]
                    if " ".join((id2content.get(vid) or "").split()) == gold_content:
                        info['vec_raw_rank_k100'] = i
                        break
                if 'vec_raw_rank_k100' not in info:
                    info['vec_raw_rank_k100'] = None
            miss.append(info)
j1p.VEC_RANK_EXEMPT = saved

print(f"=== Run P: total {total}, miss {len(miss)}, Pool Recall {100*(total-len(miss))/total:.1f}% ===")
for m in miss:
    print(json.dumps(m, ensure_ascii=False))
gate_block = [m for m in miss if m.get('in_lane_pool')]
emb_deep = [m for m in miss if not m.get('in_lane_pool') and m.get('vec_raw_rank_k100')]
emb_out = [m for m in miss if not m.get('in_lane_pool') and m.get('vec_raw_rank_k100') is None]
print("\n--- classification ---")
print(f"gate_blocked (in pool but filtered): {len(gate_block)}")
print(f"vec_deep_in_k100: {len(emb_deep)}  ranks={[m['vec_raw_rank_k100'] for m in emb_deep]}")
print(f"vec_outside_k100 (embedding quality limit): {len(emb_out)}")
print("\n--- gate_blocked detail ---")
for m in gate_block: print(json.dumps(m, ensure_ascii=False))
json.dump(miss, open('run_p_miss_diagnosis.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)
