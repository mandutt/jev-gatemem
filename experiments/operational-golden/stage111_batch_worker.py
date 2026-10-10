# -*- coding: utf-8 -*-
"""stage111_batch_worker.py — 배치 ingest 워커 (스레드/디렉토리 프로브용, 150턴)"""
import os, sys, json, time, tempfile

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
os.chdir(REPO)
DATA = r"C:\Users\mandu\AppData\Local\hermes\cache\scratch\LongMemEval\data\longmemeval_s_cleaned.json"

idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0

# 워커별 별도 디렉토리 (LMEV_BENCH_DIR env, 없으면 공용)
BENCH = os.environ.get("LMEV_BENCH_DIR", os.path.join(REPO, "experiments", "operational-golden", "data", "tmp_bench"))
os.makedirs(BENCH, exist_ok=True)

from mnemosyne import Mnemosyne
import mnemosyne.core.embeddings as emb_mod
from mnemosyne.core import beam as beam_mod

x = json.load(open(DATA, encoding="utf-8"))[idx]
tmp = tempfile.mkdtemp(prefix="lmev_th_", dir=BENCH)
mem = Mnemosyne(session_id=f"th{idx}", db_path=os.path.join(tmp, "x.db"))
conn = mem.beam.conn
t0 = time.time()

# 1) 임베딩 off remember (150턴)
_orig = emb_mod.available
emb_mod.available = lambda: False
rows = [f"{t.get('role','user')}: {t['content']}"
        for sess in x["haystack_sessions"] for t in sess
        if t.get("content")][:150]
for content in rows:
    mem.remember(content, source="conversation", importance=0.5, extract=False)
conn.commit()
emb_mod.available = _orig
t_insert = time.time() - t0

# 2) 배치 임베딩 (전체)
pool_rows = conn.execute("SELECT id, content FROM working_memory WHERE id IS NOT NULL").fetchall()
contents = [r["content"] for r in pool_rows]
BATCH = 64
for start in range(0, len(contents), BATCH):
    chunk = contents[start:start + BATCH]
    vecs = emb_mod.embed(chunk)
    if vecs is None:
        break
    for r, vec in zip(pool_rows[start:start + BATCH], vecs):
        try:
            beam_mod._store_working_embedding(conn, r["id"], vec.tolist() if hasattr(vec, "tolist") else list(vec), commit_vec=False)
        except Exception:
            pass
conn.commit()
t_total = time.time() - t0
print(f"[th{idx}] {len(rows)}턴: insert={t_insert:.1f}s embed={t_total-t_insert:.1f}s total={t_total:.1f}s", flush=True)