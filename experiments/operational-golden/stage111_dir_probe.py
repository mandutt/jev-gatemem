# -*- coding: utf-8 -*-
"""stage111_dir_probe.py — DB 디렉토리 분리 4병렬 실측 (2026-10-10)

가설: 4워커가 '같은 tmp_bench 디렉토리'에 각자 DB 생성 → 디렉토리 메타데이터 경합.
검증: 워커마다 완전히 별도 최상위 디렉토리(worker_i/)에 DB 생성 후 4병렬 ingest.
"""
import os, sys, json, time, subprocess, shutil

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
WORKER = os.path.join(REPO, "experiments", "operational-golden", "stage111_batch_worker.py")
PY = os.path.join(os.environ["LOCALAPPDATA"], "jev-mem", "venv", "Scripts", "python.exe")
BENCH_ROOT = os.path.join(REPO, "experiments", "operational-golden", "data", "tmp_bench")

# 워커별 별도 디렉토리 생성
for i in range(4):
    d = os.path.join(BENCH_ROOT, f"worker_{i}")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)

t0 = time.time()
procs = []
for i in range(4):
    p = subprocess.Popen([PY, WORKER, str(i)],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                         env={**os.environ, "LMEV_BENCH_DIR": os.path.join(BENCH_ROOT, f"worker_{i}")})
    procs.append(p)
outs = []
for p in procs:
    out, _ = p.communicate()
    outs.append(out.strip().splitlines()[-1] if out.strip() else "no output")
total = time.time() - t0
print(f"[별도 디렉토리] 4병렬 전체 경과: {total:.1f}s")
for o in outs:
    print("   ", o)