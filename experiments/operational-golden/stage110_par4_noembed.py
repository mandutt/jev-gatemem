# -*- coding: utf-8 -*-
"""stage110_par4_noembed.py — 임베딩 OFF 4병렬 ingest 프로브 (2026-10-10)

목적: 4병렬 5배 경합 원인 분리 — 임베딩 경합 vs sqlite/FTS I/O 경합.
임베딩 off (embeddings.available() -> False)면 remember()의 vec 저장부가
건너뛰므로 sqlite+FTS만 남는다. 그 상태로 4병렬 시간을 측정한다.

사용: python stage110_par4_noembed.py
"""
import os, sys, json, time, tempfile, subprocess

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
WORKER = os.path.join(REPO, "experiments", "operational-golden", "stage110_noembed_worker.py")
PY = os.path.join(os.environ["LOCALAPPDATA"], "jev-mem", "venv", "Scripts", "python.exe")

t0 = time.time()
procs = []
for i in range(4):
    p = subprocess.Popen([PY, WORKER], stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True)
    procs.append(p)
outs = []
for p in procs:
    out, _ = p.communicate()
    outs.append(out.strip().splitlines()[-1] if out.strip() else "no output")
total = time.time() - t0
print(f"[no-embed] 4병렬 전체 경과: {total:.1f}s")
for o in outs:
    print("   ", o)