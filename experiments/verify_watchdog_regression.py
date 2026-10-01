"""Watchdog regression: after idle 60s ticks, no spurious lag warning.

The old code measured the interval between op_loop ticks and warned at
>5s — since the tick IS 60s, every tick logged 'event loop lag 60.0s'.
The fixed code measures the OVERRUN of the sleep(60) only.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware")
SNAP = REPO / "data" / "snapshots" / "snap-20260927.db"
SCRATCH = Path(os.environ.get("TMPDIR", r"C:\Users\mandu\AppData\Local\hermes\cache\scratch"))
WORK = SCRATCH / "wd_probe" / f"run_{int(time.time())}"
DATA = WORK / "data"
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / "mnemosyne.db"
shutil.copy2(SNAP, DB)
PY = r"C:\Users\mandu\AppData\Local\jev-mem\venv\Scripts\pythonw.exe"
PORT = 47931
LOG = WORK / "core.out.log"

env = dict(os.environ)
env["JEV_MEM_PORT"] = str(PORT)
env["JEV_MEM_DATA_DIR"] = str(DATA)
env["JEV_MEM_DB"] = str(DB)
env["JEV_MEM_EMBED_WARMUP"] = "fail"
env["MNEMOSYNE_EMBEDDING_MODEL"] = "bench/bekko-a8m"
env["MNEMOSYNE_FASTEMBED_CACHE_DIR"] = str(
    Path(os.environ["LOCALAPPDATA"]) / "jev-mem" / "bench" / "run-20261001-s4" / "fe-cache")

proc = subprocess.Popen(
    [PY, "-m", "jev_mem_core", "--serve"], cwd=str(REPO), env=env,
    stdout=open(LOG, "wb"), stderr=subprocess.STDOUT,
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

t0 = time.time()
while time.time() - t0 < 60:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/v1/health", timeout=0.5) as r:
            if r.status == 200:
                break
    except Exception:
        time.sleep(0.4)
print("ready in", round(time.time() - t0, 1), "s")

# wait for at least two 60s ticks (idle — no traffic)
time.sleep(125)
lag_lines = []
with open(LOG, "r", encoding="utf-8", errors="replace") as f:
    for line in f:
        if "event loop lag" in line:
            lag_lines.append(line.strip())
print("lag lines:", len(lag_lines))
for l in lag_lines[:5]:
    print(" ", l)
ok = len(lag_lines) == 0
print("RESULT:", "PASS" if ok else "FAIL")
proc.terminate()
try:
    proc.wait(timeout=15)
except Exception:
    proc.kill()
sys.exit(0 if ok else 1)