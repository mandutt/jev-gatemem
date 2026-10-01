"""스크래치 DB에 a8m 임베딩 백필 v3 — 내 mnemosyne 경로 재사용
- memory_embeddings(embedding_json)을 채우고 _backfill_vec_working... 호출
"""
import sys, os, json
sys.path.insert(0, 'C:/Users/mandu/hermes-made/jev-memory-middleware')
sys.stdout.reconfigure(encoding='utf-8')

DB = 'C:/Users/mandu/AppData/Local/hermes/cache/scratch/scratch_eval.db'
from mnemosyne.core.beam import BeamMemory
import mnemosyne.core.beam as beam_mod

beam = BeamMemory(session_id='scratch-eval', db_path=DB)
n_rows = beam.conn.execute('SELECT COUNT(*) FROM working_memory').fetchone()[0]
print(f'working_memory: {n_rows}', flush=True)

emb = beam_mod._embeddings
rows = beam.conn.execute('SELECT id, content FROM working_memory ORDER BY id').fetchall()

B = 16
done = 0
for i in range(0, len(rows), B):
    batch = rows[i:i+B]
    batch_ids = [r[0] for r in batch]
    batch_texts = [r[1] for r in batch]
    vecs = emb.embed(batch_texts)
    for bid, v in zip(batch_ids, vecs):
        beam.conn.execute(
            'INSERT OR REPLACE INTO memory_embeddings (memory_id, embedding_json, model) VALUES (?,?,?)',
            (bid, json.dumps([round(float(x), 6) for x in v]), 'bench/bekko-a8m'))
    beam.conn.commit()
    done += len(batch_ids)
    if done % 64 == 0 or done == len(rows):
        print(f'  {done}/{len(rows)}', flush=True)

print('memory_embeddings:', beam.conn.execute('SELECT COUNT(*) FROM memory_embeddings').fetchone()[0], flush=True)
n = beam_mod._backfill_vec_working_from_memory_embeddings(beam.conn)
print('vec_working 백필:', n, flush=True)
print('vec_working 총:', beam.conn.execute('SELECT COUNT(*) FROM vec_working').fetchone()[0], flush=True)