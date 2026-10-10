# -*- coding: utf-8 -*-
"""stage111_nofts_probe.py — FTS off insert 속도 실측 (2026-10-10)

목적: 500문항 단독 실행을 빠르게 하기 위해, FTS 트리거 끄면 insert가 얼마나 빨라지는가.
방법: mnemosyne DB 생성 후 fts_working 트리거 DROP → 임베딩 off remember bulk.
      (실제 러너에서는 벡터 lane만으로 pool 구성 — stage110에서 41 pool 중 vec 포함 확인)
비교: FTS on = 17ms/턴 (no-embed remember 단독)
"""
import os, sys, json, time, tempfile

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
os.chdir(REPO)
DATA = r"C:\Users\mandu\AppData\Local\hermes\cache\scratch\LongMemEval\data\longmemeval_s_cleaned.json"
BENCH = os.path.join(REPO, "experiments", "operational-golden", "data", "tmp_bench")
os.makedirs(BENCH, exist_ok=True)

from mnemosyne import Mnemosyne
import mnemosyne.core.embeddings as emb_mod

x = json.load(open(DATA, encoding="utf-8"))[0]
tmp = tempfile.mkdtemp(prefix="lmev_nf_", dir=BENCH)
mem = Mnemosyne(session_id="nf", db_path=os.path.join(tmp, "x.db"))
conn = mem.beam.conn

# FTS 트리거 DROP (테이블은 유지 — 나중에 재생성 가능)
for trig in ("wm_ai", "wm_au", "wm_ad"):
    try:
        conn.execute(f"DROP TRIGGER IF EXISTS {trig}")
    except Exception as e:
        print(f"  trigger drop fail {trig}: {e}")
conn.commit()

_orig = emb_mod.available
emb_mod.available = lambda: False
rows = [f"{t.get('role','user')}: {t['content']}"
        for sess in x["haystack_sessions"] for t in sess
        if t.get("content")]
t0 = time.time()
for content in rows:
    mem.remember(content, source="conversation", importance=0.5, extract=False)
conn.commit()
emb_mod.available = _orig
dt = time.time() - t0
print(f"[FTS OFF] {len(rows)}턴 insert: {dt:.1f}s ({dt/len(rows)*1000:.0f}ms/턴)", flush=True)
print(f"[FTS ON 비교] 17ms/턴 (stage110_par4_noembed 단독)")