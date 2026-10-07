# -*- coding: utf-8 -*-
"""stage76b: vec_working 768d 재구축만 (resume — memory_embeddings 이미 768d 완료)"""
import os, sys, json, sqlite3, time
import numpy as np

REPO = r"C:/Users/mandu/hermes-made/jev-memory-middleware"
WORK = os.path.join(REPO, "experiments", "operational-golden", "snapshots", "mnemosyne_snapshot_20261006_gemma2.db")

conn = sqlite3.connect(WORK)
conn.row_factory = sqlite3.Row
conn.enable_load_extension(True)
import sqlite_vec
sqlite_vec.load(conn)

# memory_embeddings 확인 (768d?)
row = conn.execute("SELECT embedding_json FROM memory_embeddings LIMIT 1").fetchone()
v0 = json.loads(row[0])
print("memory_embeddings dim:", len(v0), flush=True)

# rowid 매핑
id2rowid = {r["id"]: r["rowid"] for r in conn.execute("SELECT id, rowid FROM working_memory").fetchall()}
rows = conn.execute("SELECT memory_id, embedding_json FROM memory_embeddings").fetchall()
print("memory_embeddings rows:", len(rows), flush=True)

conn.execute("DROP TABLE IF EXISTS vec_working")
conn.execute("CREATE VIRTUAL TABLE vec_working USING vec0(embedding int8[768])")
t0 = time.time()
n = 0
for r in rows:
    rid = id2rowid.get(r["memory_id"])
    if rid is None:
        continue
    v = np.array(json.loads(r["embedding_json"]), dtype=np.float32)
    vn = v / (np.linalg.norm(v) + 1e-12)
    conn.execute("INSERT INTO vec_working (rowid, embedding) VALUES (?, vec_quantize_int8(?, 'unit'))",
                 (rid, json.dumps(vn.tolist())))
    n += 1
conn.commit()
print(f"vec_working rebuilt: {n} rows ({time.time()-t0:.0f}s)", flush=True)

# 검증
from datetime import datetime
import sys as _s
_s.path.insert(0, os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20261006-embedgemma2"))
from embgemma2_runner import EmbGemma2Runner
_g2 = EmbGemma2Runner(os.path.join(os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20261006-embedgemma2"), "model-src"), model_file="model_q4f16.onnx")
where = 'wm.superseded_by IS NULL AND (wm.valid_until IS NULL OR wm.valid_until > ?)'
wp = (datetime.now().isoformat(),)
for q in ("코덱스 앱이 PC 느려지게 한 원인 뭐였어?", "게이트웨이 텔레그램 수신 문제 해결", "임베딩 모델 교체 실험"):
    qemb = np.array(_g2.embed([q])[0], dtype=np.float32)
    qnorm = qemb / (np.linalg.norm(qemb) + 1e-12)
    qj = json.dumps(qnorm.tolist())
    try:
        rws = conn.execute(f"SELECT wm.id FROM vec_working vw JOIN working_memory wm ON wm.rowid=vw.rowid WHERE vw.embedding MATCH vec_quantize_int8(?, 'unit') AND k=5 AND {where} ORDER BY vw.distance", (qj, *wp)).fetchall()
        print(f"verify '{q[:20]}' -> {len(rws)} results:", [(r['id'] or '')[:12] for r in rws], flush=True)
    except Exception as e:
        print(f"verify EXC: {type(e).__name__} {str(e)[:200]}", flush=True)

conn.close()
print("STAGE76B DONE")