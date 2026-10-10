# -*- coding: utf-8 -*-
"""stage110_thread_probe.py — fastembed 스레드 제한 효과 실측 (2026-10-10)

가설: 워커별 onnxruntime이 코어 전체(12) 스레드를 잡아 4워커 경합 폭증.
검증: OMP_NUM_THREADS / fastembed thread 설정 시 100턴 ingest 시간.
"""
import os, sys, json, time, tempfile

# --- 스레드 제한 (실행 전 설정) ---
import argparse
ap = argparse.ArgumentParser()
ap.add_argument("--threads", type=int, default=0, help="0=제한 없음, N=OMP/ORT 스레드")
args = ap.parse_args()
if args.threads:
    os.environ["OMP_NUM_THREADS"] = str(args.threads)
    os.environ["OMP_WAIT_POLICY"] = "PASSIVE"

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
os.chdir(REPO)
DATA = r"C:\Users\mandu\AppData\Local\hermes\cache\scratch\LongMemEval\data\longmemeval_s_cleaned.json"

# fastembed 스레드 설정 시도
try:
    import fastembed
except ImportError:
    fastembed = None

from mnemosyne import Mnemosyne

def run_one(index):
    x = json.load(open(DATA, encoding="utf-8"))[index]
    tmp = tempfile.mkdtemp(prefix="lmev_t_")
    mem = Mnemosyne(session_id=f"t{index}", db_path=os.path.join(tmp, "x.db"))
    t0 = time.time()
    n = 0
    for sess in x["haystack_sessions"]:
        for turn in sess:
            c = turn.get("content", "")
            if c:
                mem.remember(f"{turn.get('role','user')}: {c}", source="conversation",
                             importance=0.5, extract=False)
                n += 1
            if n >= 150:  # 150턴까지만 (probe 속도)
                break
        if n >= 150:
            break
    return n, time.time() - t0

n, dt = run_one(0)
print(f"[threads={args.threads}] 150턴 ingest: {dt:.1f}s ({dt/n*1000:.0f}ms/턴)", flush=True)