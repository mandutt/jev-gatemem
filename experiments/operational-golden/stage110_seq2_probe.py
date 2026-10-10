# -*- coding: utf-8 -*-
"""stage110_seq2_probe.py — 단독 프로세스 2문항 순차 ingest (2026-10-10)

목적: 4병렬 5배 경합이 '프로세스당 모델 로드' 문제인지 확인.
- 같은 프로세스에서 문항 2건을 순차 ingest → 모델 로드는 1회만.
- 4병렬(4개 프로세스, 각 모델 로드 1회) vs 단독 2문항(모델 로드 1회) 비교.
"""
import os, sys, json, time, tempfile

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
os.chdir(REPO)
DATA = r"C:\Users\mandu\AppData\Local\hermes\cache\scratch\LongMemEval\data\longmemeval_s_cleaned.json"

from mnemosyne import Mnemosyne

data = json.load(open(DATA, encoding="utf-8"))


def ingest_one(x, tag):
    tmp = tempfile.mkdtemp(prefix="lmev_seq_", dir=r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data\tmp_bench")
    mem = Mnemosyne(session_id=tag, db_path=os.path.join(tmp, "x.db"))
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
    print(f"[seq-{tag}] 150턴 ingest: {dt:.1f}s ({dt/n*1000:.0f}ms/턴)", flush=True)
    return n, dt


t_all = time.time()
for i in range(2):
    ingest_one(data[i], f"q{i}")
print(f"[총] 2문항 순차: {time.time()-t_all:.1f}s")