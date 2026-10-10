# -*- coding: utf-8 -*-
"""stage111_thread_probe.py — MNEMOSYNE_EMBEDDING_THREADS 제한 효과 실측 (2026-10-10)

가설: 워커별 onnxruntime 기본 스레드 = cpu_count(12). 4워커 = 48스레드 경합 → 5배 느림.
검증: MNEMOSYNE_EMBEDDING_THREADS=N 로 4병렬 배치 ingest 시간 측정.
사용: python stage111_thread_probe.py [N]   (N=0 기본, N=3 권장)
"""
import os, sys, json, time, tempfile, subprocess

N = sys.argv[1] if len(sys.argv) > 1 else "0"
REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
WORKER = os.path.join(REPO, "experiments", "operational-golden", "stage111_batch_worker.py")
PY = os.path.join(os.environ["LOCALAPPDATA"], "jev-mem", "venv", "Scripts", "python.exe")

env = dict(os.environ)
if N != "0":
    env["MNEMOSYNE_EMBEDDING_THREADS"] = N

t0 = time.time()
procs = []
for i in range(4):
    p = subprocess.Popen([PY, WORKER, str(i)], stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, env=env)
    procs.append(p)
outs = []
for p in procs:
    out, _ = p.communicate()
    outs.append(out.strip().splitlines()[-1] if out.strip() else "no output")
total = time.time() - t0
print(f"[threads={N}] 4병렬 배치 전체 경과: {total:.1f}s")
for o in outs:
    print("   ", o)