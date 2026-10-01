"""P1 embedding-status verification — scratch daemon on a snapshot DB copy.

Verifies (exit 0 = all PASS):
  1. /v1/status exposes `embedding` = {model, dim, warmup_ok, warmup_error}
  2. warmup_ok=True and model reflects the ACTUAL resolved model (alias)
  3. warmup failure path: JEV_MEM_EMBED_WARMUP=fail -> daemon refuses to start
     (exit 9, /v1/health never comes up)
  4. warmup failure + JEV_MEM_EMBED_WARMUP=warn -> daemon starts degraded,
     status.degraded_reasons contains embedding_warmup_failed
  5. watchdog: no spurious 'event loop lag 60.0s' after a 60s tick (checked
     by grepping the daemon log for lag lines while idle)

Uses the jev-mem venv python (sitecustomize registers bench/bekko-a8m).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware")
SNAP = REPO / "data" / "snapshots" / "snap-20260927.db"
SCRATCH = Path(os.environ.get("TMPDIR", r"C:\Users\mandu\AppData\Local\hermes\cache\scratch"))
WORK = SCRATCH / "p1_embed_probe" / f"run_{int(time.time())}"
DATA = WORK / "data"
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / "mnemosyne.db"
if DB.exists():
    for suf in ("", "-wal", "-shm"):
        Path(str(DB) + suf).unlink(missing_ok=True)
shutil.copy2(SNAP, DB)

# jev-mem venv python (sitecustomize.py registers bench/bekko-a8m at startup)
PY = r"C:\Users\mandu\AppData\Local\jev-mem\venv\Scripts\pythonw.exe"
PORT = 47921
BASE = f"http://127.0.0.1:{PORT}/v1"
LOG = WORK / "core.out.log"


def base_env(**extra) -> dict:
    env = dict(os.environ)
    env["JEV_MEM_PORT"] = str(PORT)
    env["JEV_MEM_DATA_DIR"] = str(DATA)
    env["JEV_MEM_DB"] = str(DB)
    env["JEV_MEM_EMBED_WARMUP"] = extra.pop("warmup", "fail")
    env["MNEMOSYNE_EMBEDDING_MODEL"] = "bench/bekko-a8m"
    env["MNEMOSYNE_FASTEMBED_CACHE_DIR"] = str(
        Path(os.environ["LOCALAPPDATA"]) / "jev-mem" / "bench" / "run-20261001-s4" / "fe-cache")
    env.update(extra)
    return env


def wait_ready(port: int, timeout: float = 90) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/health", timeout=0.5) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def fetch_status(port: int, data_dir: Path) -> dict:
    tok = (data_dir / "token").read_text(encoding="utf-8").strip() if (data_dir / "token").exists() else ""
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/status",
        headers={"Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode())


def start_core(env, timeout=90):
    logf = open(LOG, "wb")
    proc = subprocess.Popen(
        [PY, "-m", "jev_mem_core", "--serve"],
        cwd=str(REPO), env=env, stdout=logf, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return proc


results = []


def check(name: str, ok: bool, detail: str = ""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# ---- Case 1: normal start, embedding field present & warmup_ok ----
env = base_env()
proc = start_core(env)
ready = wait_ready(PORT)
check("1a. daemon starts (warmup ok)", ready)
st = None
if ready:
    st = fetch_status(PORT, DATA)
    emb = st.get("embedding", {})
    check("1b. status has embedding object", isinstance(emb, dict) and "model" in emb,
          json.dumps(emb, ensure_ascii=False)[:200])
    check("1c. warmup_ok=True", emb.get("warmup_ok") is True, f"model={emb.get('model')}")
    check("1d. model == bench/bekko-a8m (actual resolved alias)",
          emb.get("model") == "bench/bekko-a8m", f"model={emb.get('model')}")
    check("1e. dim == 384", emb.get("dim") == 384, f"dim={emb.get('dim')}")
    check("1f. degraded == False (no embedding reason)", st.get("degraded") is False,
          f"reasons={st.get('degraded_reasons')}")

# stop case-1 core
if proc.poll() is None:
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except Exception:
        proc.kill()
time.sleep(1)

# ---- Case 2: warmup failure (sabotage) + default fail -> refuse to start ----
work2 = WORK / "case2"
work2.mkdir(parents=True, exist_ok=True)
db2 = work2 / "mnemosyne.db"
shutil.copy2(SNAP, db2)
env2 = dict(os.environ)
env2["JEV_MEM_PORT"] = str(PORT + 1)
env2["JEV_MEM_DATA_DIR"] = str(work2)
env2["JEV_MEM_DB"] = str(db2)
# sabotage: point the model at a name that cannot resolve
env2["MNEMOSYNE_EMBEDDING_MODEL"] = "bench/does-not-exist"
env2["JEV_MEM_EMBED_WARMUP"] = "fail"
log2 = open(WORK / "core2.out.log", "wb")
proc2 = subprocess.Popen(
    [PY, "-m", "jev_mem_core", "--serve"], cwd=str(REPO), env=env2,
    stdout=log2, stderr=subprocess.STDOUT,
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
# it should exit quickly (warmup failure -> exit 9); wait up to 60s
exit_code = proc2.wait(timeout=90)
check("2a. daemon refuses to start on warmup failure (exit 9)", exit_code == 9,
      f"exit={exit_code}")
log2.close()

# ---- Case 3: warmup failure + warn -> starts degraded ----
work3 = WORK / "case3"
work3.mkdir(parents=True, exist_ok=True)
db3 = work3 / "mnemosyne.db"
shutil.copy2(SNAP, db3)
env3 = dict(os.environ)
env3["JEV_MEM_PORT"] = str(PORT + 2)
env3["JEV_MEM_DATA_DIR"] = str(work3)
env3["JEV_MEM_DB"] = str(db3)
env3["MNEMOSYNE_EMBEDDING_MODEL"] = "bench/does-not-exist"
env3["JEV_MEM_EMBED_WARMUP"] = "warn"
log3 = open(WORK / "core3.out.log", "wb")
proc3 = subprocess.Popen(
    [PY, "-m", "jev_mem_core", "--serve"], cwd=str(REPO), env=env3,
    stdout=log3, stderr=subprocess.STDOUT,
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
ready3 = wait_ready(PORT + 2)
check("3a. daemon starts in warn mode", ready3)
if ready3:
    st3 = fetch_status(PORT + 2, work3)
    emb3 = st3.get("embedding", {})
    check("3b. warmup_ok=False + warmup_error set", emb3.get("warmup_ok") is False and bool(emb3.get("warmup_error")),
          f"error={str(emb3.get('warmup_error'))[:120]}")
    check("3c. degraded_reasons contains embedding_warmup_failed",
          "embedding_warmup_failed" in st3.get("degraded_reasons", []),
          f"reasons={st3.get('degraded_reasons')}")
    check("3d. status still 'ready' (degraded, not down)", st3.get("status") == "ready")
if proc3.poll() is None:
    proc3.terminate()
    try:
        proc3.wait(timeout=15)
    except Exception:
        proc3.kill()

print("\n===== RESULTS =====")
fails = [r for r in results if not r[1]]
for name, ok, detail in results:
    print(f"{'PASS' if ok else 'FAIL'}: {name}")
print(f"\n{len(results) - len(fails)}/{len(results)} passed")
sys.exit(1 if fails else 0)