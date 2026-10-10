# -*- coding: utf-8 -*-
"""stage110_par4_probe.py — 4병렬 ingest 경합 재현 프로브 (2026-10-10)

4개 프로세스가 동시에 150턴씩 ingest — threads 제한 유무 × 경합 측정.
사용: python stage110_par4_probe.py --threads N
"""
import os, sys, json, time, tempfile, subprocess

THREADS = sys.argv[1] if len(sys.argv) > 1 else "0"
REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
WORKER = os.path.join(REPO, "experiments", "operational-golden", "stage110_thread_probe.py")

t0 = time.time()
procs = []
for i in range(4):
    p = subprocess.Popen(
        [os.path.join(os.environ["LOCALAPPDATA"], "jev-mem", "venv", "Scripts", "python.exe"),
         WORKER, "--threads", THREADS],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    procs.append(p)
outs = []
for p in procs:
    out, _ = p.communicate()
    outs.append(out.strip().splitlines()[-1] if out.strip() else "no output")
total = time.time() - t0
print(f"[threads={THREADS}] 4병렬 전체 경과: {total:.1f}s")
for o in outs:
    print("   ", o)