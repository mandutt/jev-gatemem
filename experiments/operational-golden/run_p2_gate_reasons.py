import json, os, sys
os.chdir("C:/Users/mandu/AppData/Local/hermes/cache/scratch/perfectrecall")
for p in list(sys.path):
    if p in ("", ".", os.getcwd()): sys.path.remove(p)
sys.path.insert(0, "C:/Users/mandu/hermes-made/jev-memory-middleware")
from gateway import j1_pipeline as j1p
from mnemosyne.core.beam import BeamMemory
import mnemosyne.core.beam as beam_mod
import sqlite3

DB = "C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
beam = BeamMemory(session_id='run-p-diag2', db_path=DB)
queries = json.load(open('golden_final_v2.json', encoding='utf-8'))
con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
id2content = {r[0]: r[1] for r in con.execute("SELECT id, content FROM working_memory")}
id2content.update({r[0]: r[1] for r in con.execute("SELECT id, content FROM episodic_memory")})
con.close()

def recall_raw(kind, arg, k):
    if kind == "fts": return beam_mod._fts_search_working(beam.conn, arg, k=k)
    if kind == "vec":
        emb = beam_mod._embeddings.embed([arg])
        if emb is None or not len(emb): return []
        return beam_mod._wm_vec_search(beam.conn, emb[0], k=k)
    if kind == "imp": return j1p._imp_search(beam.conn, k=k)
    if kind == "graph": return j1p._graph_lane_search(beam.conn, arg, k=k)
    if kind == "get":
        return {"id": arg, "content": id2content.get(arg, "")} if arg in id2content else None
    return []

def gm(c, g):
    c = " ".join((c or "").split()); return c == g or (g in c and len(g) > 10)

results = []
saved = j1p.VEC_RANK_EXEMPT
for q in queries:
    if q['cat'] == 'NO_ANSWER': continue
    gold_content = " ".join((id2content.get(q['id']) or "").split())
    for axis, qtext in (('literal', q['query_literal']), ('paraphrase', q['query_paraphrase'])):
        pool = j1p.build_lane_pool(recall_raw, qtext)
        q_tokens = j1p._tokenize(qtext) - j1p._STOPWORDS
        gold_rows = [r for r in pool if gm(r.get("content"), gold_content)]
        if not gold_rows: continue  # lane 부재 — 이미 분류됨
        gr = gold_rows[0]
        lr = gr.get('_lane_ranks') or {}
        vr = lr.get('vec_rank')
        content = (gr.get("content") or "").strip()
        overlap = q_tokens & j1p._tokenize(content)
        n_ov = len(overlap)
        cov = n_ov / len(q_tokens) if q_tokens else 0
        md, mc = 2, 0.30
        # VEC_RANK_EXEMPT=2 현행에서의 탈락 사유
        if n_ov >= md and cov >= mc:
            reason = 'PASS?'  # 통과했어야 — rank 밀림 아님; 실제로는 miss이므로 다른 원인
        elif n_ov < md:
            reason = f'overlap<{md} (n_ov={n_ov})'
        else:
            reason = f'coverage<{mc} (cov={cov:.3f}, n_ov={n_ov}/{len(q_tokens)})'
        # 예외 확장 시 회복 여부: vr<=k면 통과(overlap>=1 필요)
        results.append({'cat': q['cat'], 'axis': axis, 'query': qtext[:35], 'vec_rank': vr,
                        'fts_rank': lr.get('fts_rank'), 'n_overlap': n_ov, 'q_tokens': len(q_tokens),
                        'cov': round(cov,3), 'reason': reason})
j1p.VEC_RANK_EXEMPT = saved

print("=== Run P-2: 레인 풀 내 gold 8건의 게이트 탈락 사유 ===")
for r in results: print(json.dumps(r, ensure_ascii=False))
print("\n=== 예외 확장 시뮬 (vr<=k && overlap>=1 조건) ===")
for k in (2, 3, 5, 10, 25):
    rec = sum(1 for r in results if r['vec_rank'] is not None and r['vec_rank'] <= k and r['n_overlap'] >= 1)
    print(f"vec<={k}: {rec}/{len(results)} 회복")
print("\n=== 'overlap>=1' 요건 제거형 예외 (vr<=k 무조건) ===")
for k in (2, 5, 10):
    rec = sum(1 for r in results if r['vec_rank'] is not None and r['vec_rank'] <= k)
    print(f"vec<={k} 무조건: {rec}/{len(results)}")
json.dump(results, open('run_p2_gate_reasons.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)
