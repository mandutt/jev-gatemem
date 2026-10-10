# -*- coding: utf-8 -*-
"""stage110_noembed_worker.py — 임베딩 off 상태로 150턴 ingest (4병렬 경합 분리용)"""
import os, sys, json, time, tempfile

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
os.chdir(REPO)
DATA = r"C:\Users\mandu\AppData\Local\hermes\cache\scratch\LongMemEval\data\longmemeval_s_cleaned.json"

import mnemosyne.core.embeddings as emb_mod
_orig_available = emb_mod.available


def _disabled_available():
    return False


emb_mod.available = _disabled_available

from mnemosyne import Mnemosyne

x = json.load(open(DATA, encoding="utf-8"))[0]
tmp = tempfile.mkdtemp(prefix="lmev_ne_", dir=r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data/tmp_bench")  # noqa
mem = Mnemosyne(session_id="ne", db_path=os.path.join(tmp, "x.db"))
t0 = time.time()
n = 0
for sess in x["haystack_sessions"]:
    for turn in sess:
        c = turn.get("content", "")
        if c:
            mem.remember(f"{turn.get('role','user')}: {c}", source="conversation",
                         importance=0.5, extract=False)
            n += 1
        if n >= 150:
            break
    if n >= 150:
        break
dt = time.time() - t0
print(f"[no-embed] 150턴 ingest: {dt:.1f}s ({dt/n*1000:.0f}ms/턴)", flush=True)