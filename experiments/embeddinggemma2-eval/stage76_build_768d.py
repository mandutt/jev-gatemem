# -*- coding: utf-8 -*-
"""stage76: 768d vec lane 교정 준비 — 스냅샷 DB 복사본에 gemma2 768d 벡터 구축 (0콜)

stage74 치명적 결함 교정: vec lane이 384d 고정이어서 gemma2(768d) 쿼리는
sqlite-vec/fallback 모두 0건 → stage74는 'vec lane 제거' 상태를 측정했다.

이 스크립트:
1. 스냅샷 DB 복사 (work DB)
2. working_memory 전체를 gemma2-q4f16으로 임베딩 (doc 프롬프트)
3. memory_embeddings를 768d로 교체 + vec_working 테이블을 768d로 재생성
   (sqlite-vec int8[768] — 운영 마이그레이션과 동일한 형태)
4. 베리파이: 768d 쿼리로 _wm_vec_search가 결과 반환

주의: work DB만 수정. 원본 스냅샷/라이브 불변.
"""
import os, sys, json, sqlite3, shutil, time
import numpy as np

REPO = r"C:/Users/mandu/hermes-made/jev-memory-middleware"
sys.path.insert(0, REPO)
SNAP = os.path.join(REPO, "experiments", "operational-golden", "snapshots", "mnemosyne_snapshot_20261006.db")
WORK = os.path.join(REPO, "experiments", "operational-golden", "snapshots", "mnemosyne_snapshot_20261006_gemma2.db")

sys.path.insert(0, os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20261006-embedgemma2"))
from embgemma2_runner import EmbGemma2Runner

if os.path.exists(WORK):
    print("work DB exists -> resume mode: reuse memory_embeddings, rebuild vec_working only", flush=True)
else:
    print("copying snapshot ...", flush=True)
    shutil.copy2(SNAP, WORK)
    if os.path.exists(WORK + "-shm"): os.remove(WORK + "-shm")
    if os.path.exists(WORK + "-wal"): os.remove(WORK + "-wal")

conn = sqlite3.connect(WORK)
conn.row_factory = sqlite3.Row
# sqlite-vec 로드
conn.enable_load_extension(True)
try:
    import sqlite_vec
    sqlite_vec.load(conn)
    print("sqlite_vec loaded", flush=True)
except Exception as e:
    print("sqlite_vec load fail:", e, flush=True)
    sys.exit(1)

# working_memory id 목록 (superseded 제외와 무관하게 전부 — mine은 유지)
rows = conn.execute("SELECT id, content FROM working_memory WHERE content IS NOT NULL AND length(content) > 0 ORDER BY id").fetchall()
print("working_memory:", len(rows), flush=True)

# gemma2 임베딩 (doc 프롬프트)
_g2 = EmbGemma2Runner(os.path.join(os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20261006-embedgemma2"), "model-src"), model_file="model_q4f16.onnx")
t0 = time.time()
vecs = {}
B = 4
for i in range(0, len(rows), B):
    chunk = rows[i:i+B]
    texts = [r["content"] for r in chunk]
    emb = np.array(_g2.embed(texts, doc=True), dtype=np.float32)
    for j, r in enumerate(chunk):
        vecs[r["id"]] = emb[j]
    if (i//B) % 25 == 0:
        print(f"  {i}/{len(rows)} ({time.time()-t0:.0f}s)", flush=True)
print("embedding done:", len(vecs), f"({time.time()-t0:.0f}s)", flush=True)

# memory_embeddings 교체 (768d)
print("rebuilding memory_embeddings ...", flush=True)
conn.execute("DELETE FROM memory_embeddings")
for mid, v in vecs.items():
    conn.execute(
        "INSERT INTO memory_embeddings (memory_id, embedding_json, model) VALUES (?, ?, ?)",
        (mid, json.dumps(v.tolist()), "gemma2-q4f16")
    )
conn.commit()

# vec_working 테이블 768d로 재생성 (rowid = working_memory.rowid)
print("rebuilding vec_working ...", flush=True)
conn.execute("DROP TABLE IF EXISTS vec_working")
conn.execute("CREATE VIRTUAL TABLE vec_working USING vec0(embedding int8[768])")
# rowid 매핑 (working_memory.rowid)
id2rowid = {r["id"]: r["rowid"] for r in conn.execute("SELECT id, rowid FROM working_memory").fetchall()}
t1 = time.time()
for mid, v in vecs.items():
    rid = id2rowid.get(mid)
    if rid is None:
        continue
    # int8 양자화 (unit 정규화 후 *127 반올림 — sqlite-vec 관례: vec_quantize_int8(x, 'unit')과 동일)
    vn = v / (np.linalg.norm(v) + 1e-12)
    qi = np.clip(np.round(vn * 127).astype(np.int8), -128, 127)
    # vec0 int8 컬럼은 JSON 문자열 입력 + vec_quantize_int8(?, 'unit') 변환이 정석
    conn.execute("INSERT INTO vec_working (rowid, embedding) VALUES (?, vec_quantize_int8(?, 'unit'))",
                 (rid, json.dumps(vn.tolist())))
conn.commit()
print(f"vec_working rebuilt: {time.time()-t1:.0f}s", flush=True)

# 베리파이: 768d 쿼리 검색
from datetime import datetime
where = 'wm.superseded_by IS NULL AND (wm.valid_until IS NULL OR wm.valid_until > ?)'
wp = (datetime.now().isoformat(),)
for q in ("코덱스 앱이 PC 느려지게 한 원인 뭐였어?", "게이트웨이 텔레그램 수신 문제 해결"):
    qemb = np.array(_g2.embed([q])[0], dtype=np.float32)
    res = None
    # 직접 sqlite-vec 쿼리
    qnorm = qemb / (np.linalg.norm(qemb) + 1e-12)
    qj = json.dumps(qnorm.tolist())
    try:
        rws = conn.execute(f"SELECT wm.id FROM vec_working vw JOIN working_memory wm ON wm.rowid=vw.rowid WHERE vw.embedding MATCH vec_quantize_int8(?, 'unit') AND k=5 AND {where} ORDER BY vw.distance", (qj, *wp)).fetchall()
        print(f"verify '{q[:20]}' -> {len(rws)} results:", [(r['id'] or '')[:12] for r in rws])
    except Exception as e:
        print(f"verify EXC: {type(e).__name__} {str(e)[:200]}")

conn.close()
print("WORK DB READY:", WORK)