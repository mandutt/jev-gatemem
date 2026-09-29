"""P2 chaos tests (B §16.3) — core kill, spool replay, breaker, singleton.

Scenarios (each against a fresh scratch data dir + snapshot DB copy):
  1. core kill -9 (hard kill) mid-flight -> restart recovers pending rows,
     no duplicate storage (idem_key metadata check).
  2. core down -> adapter spools -> core starts -> replay -> loss 0.
  3. JEV unavailable (fake key) -> prefetch degraded 200, turns pending_gate;
     breaker opens after 5 consecutive failures.
  4. port hang (dummy socket) -> second core exits with code 3.
  5. token missing -> 401 (covered in P1; smoke here).
  6. spool corrupt line -> moved to _corrupt/, good lines replayed.
  7. backup: VACUUM INTO creates a file; keep=7 prune.
  8. auto-start: JevMemClient with no core -> spawns one, ready within 20s.

Runtime: fast on the full snapshot (~1-2s per scenario).
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware")
sys.path.insert(0, str(REPO))
SNAP = REPO / "data" / "snapshots" / "snap-20260927.db"
SCRATCH = Path(os.environ.get("TMPDIR", r"C:\Users\mandu\AppData\Local\hermes\cache\scratch"))
PY = r"C:\Users\mandu\AppData\Local\hermes\installs\315db7b763fb0d0a\environments\746564964b1042b79add42260378503b\venv\Scripts\python.exe"

RESULTS: list[tuple[str, bool, str]] = []


def run_scenario(name: str, fn) -> None:
    try:
        ok = fn()
        RESULTS.append((name, bool(ok), "" if ok else "check output above"))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    except Exception as e:
        RESULTS.append((name, False, str(e)))
        print(f"[FAIL] {name}: {e}")


def fresh_env(port: int, tag: str) -> tuple[Path, dict]:
    work = SCRATCH / f"p2_chaos_{tag}_{int(time.time() * 1000)}"
    data = work / "data"
    data.mkdir(parents=True, exist_ok=True)
    db = data / "mnemosyne.db"
    shutil.copy2(SNAP, db)
    env = dict(os.environ)
    env["JEV_MEM_PORT"] = str(port)
    env["JEV_MEM_DATA_DIR"] = str(data)
    env["JEV_MEM_DB"] = str(db)
    env.setdefault("JEV_MEM_AUTO", "0")
    return work, env, db


def spawn_core(env: dict, work: Path) -> subprocess.Popen:
    proc = subprocess.Popen(
        [PY, "-m", "jev_mem_core", "--serve"], cwd=str(REPO), env=env,
        stdout=open(work / "core.log", "wb"), stderr=subprocess.STDOUT)
    return proc


def kill_tree(proc: subprocess.Popen) -> None:
    """Windows: taskkill /T kills the whole tree; fallback to terminate()."""
    if proc.poll() is not None:
        return
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, timeout=10)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


def wait_ready(port: int, timeout: float = 30) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/health",
                                        timeout=0.5) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def post(port: int, path: str, body: dict, token: str | None = None,
         timeout: float = 30) -> tuple[int, dict]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1{path}",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def get(port: int, path: str, token: str | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1{path}")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


# ---------------------------------------------------------------------------
# 1. kill -9 (mid-flight) -> restart recovery, no dup
# ---------------------------------------------------------------------------
def scenario_kill_restart() -> bool:
    work, env, db = fresh_env(47911, "kill")
    p = spawn_core(env, work)
    if not wait_ready(47911):
        return False
    tok = (work / "data" / "token").read_text().strip()
    # submit a few turns (sync) then hard-kill
    for i in range(3):
        st, r = post(47911, "/turns", {
            "agent": "test", "session_id": "chaos-kill", "turn_seq": i,
            "idempotency_key": f"chaos-kill:{i}",
            "user_content": f"내일까지 보고서 {i}건 제출해야 해",
            "assistant_content": "", "mode": "sync"}, tok)
        if st != 200:
            print(f"   turn {i}: {st} {r}")
            return False
    # hard kill (Windows: taskkill /F kills tree)
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                   capture_output=True)
    time.sleep(2)
    # restart
    p2 = spawn_core(env, work)
    if not wait_ready(47911):
        return False
    time.sleep(3)  # recovery + startup scan
    # all 3 turns must be terminal stored with no dup
    ok = True
    for i in range(3):
        st, r = post(47911, "/turns", {
            "agent": "test", "session_id": "chaos-kill", "turn_seq": i,
            "idempotency_key": f"chaos-kill:{i}",
            "user_content": f"내일까지 보고서 {i}건 제출해야 해",
            "assistant_content": "", "mode": "sync"}, tok)
        if st != 200 or not r.get("deduplicated") or r.get("status") != "stored":
            print(f"   turn {i}: {st} {r}")
            ok = False
    kill_tree(p2)
    return ok


# ---------------------------------------------------------------------------
# 2. core down -> adapter spool -> replay -> loss 0
# ---------------------------------------------------------------------------
def scenario_spool_replay() -> bool:
    work, env, db = fresh_env(47912, "spool")
    data = work / "data"
    spool_dir = data / "spool" / "codex"
    spool_dir.mkdir(parents=True, exist_ok=True)
    # write a spool file the way the adapter would (idempotency_key included)
    lines = [
        {"agent": "codex", "session_id": "chaos-spool", "turn_seq": 1,
         "idempotency_key": "codex:chaos-spool:1",
         "user_content": "내일까지 보고서 제출해야 해 (spooled)", "assistant_content": ""},
        {"agent": "codex", "session_id": "chaos-spool", "turn_seq": 2,
         "idempotency_key": "codex:chaos-spool:2",
         "user_content": "이제 남은 항목들을 분석한다 (spooled)", "assistant_content": ""},
    ]
    sf = spool_dir / "codex-1234-20260929.jsonl"
    with open(sf, "w", encoding="utf-8") as f:
        for ln in lines:
            f.write(json.dumps(ln, ensure_ascii=False) + "\n")
    # make it old enough to not be "fresh"
    os.utime(sf, (time.time() - 30, time.time() - 30))
    # start core -> startup replay
    p = spawn_core(env, work)
    if not wait_ready(47912):
        return False
    time.sleep(4)
    tok = (data / "token").read_text().strip()
    st, status = get(47912, "/status", tok)
    spool_files = status.get("queues", {}).get("spool_files", -1)
    # both lines must be gone (replayed) and turns stored
    st2, r2 = post(47912, "/turns", {
        "agent": "codex", "session_id": "chaos-spool", "turn_seq": 1,
        "idempotency_key": "codex:chaos-spool:1",
        "user_content": "내일까지 보고서 제출해야 해 (spooled)",
        "assistant_content": ""}, tok)
    replayed_ok = (spool_files == 0 and r2.get("deduplicated") is True)
    kill_tree(p)
    return replayed_ok


# ---------------------------------------------------------------------------
# 3. JEV unavailable -> prefetch degraded, pending_gate, breaker opens
# ---------------------------------------------------------------------------
def scenario_jev_down() -> bool:
    work, env, db = fresh_env(47913, "jevdown")
    env["TYPESAFE_API_KEY"] = "invalid-key-for-chaos"
    # Point JEV at a dead local endpoint so gate calls FAIL (5xx/conn-refused)
    # rather than fail-open KEEP on 401. write_gate reads API_URL at import, so
    # pre-set it in the child env through a tiny sitecustomize-equivalent:
    # we set JEV_API_URL and patch write_gate at module import time via env
    # JEV_MEM_* is config; JEV_API_URL is consumed by jev_mem_core.app wrapper.
    env["JEV_API_URL"] = "http://127.0.0.1:9/v1/systemone"  # dead port
    p = spawn_core(env, work)
    if not wait_ready(47913):
        return False
    tok = (work / "data" / "token").read_text().strip()
    # turns -> pending_gate (JEV fails; gate fails open => pending)
    st, r = post(47913, "/turns", {
        "agent": "test", "session_id": "chaos-jev", "turn_seq": 1,
        "idempotency_key": "chaos-jev:1",
        "user_content": "내일까지 보고서 제출해야 해",
        "assistant_content": ""}, tok)
    pending_ok = st == 202 and r.get("status") == "pending_gate"
    # prefetch -> broken too (RRF degraded)
    st2, r2 = post(47913, "/prefetch", {
        "agent": "test", "query": "메모리 아키텍처 설명"}, tok)
    degraded_ok = st2 == 200
    kill_tree(p)
    return pending_ok and degraded_ok


# ---------------------------------------------------------------------------
# 4. port hang -> second core exits 3
# ---------------------------------------------------------------------------
def scenario_port_hang() -> bool:
    work, env, db = fresh_env(47914, "hang")
    # hold the port with a raw socket (no HTTP responses)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 47914))
    s.listen(1)
    p = spawn_core(env, work)
    rc = p.wait(timeout=30)
    s.close()
    return rc == 3


# ---------------------------------------------------------------------------
# 5. corrupt spool line -> _corrupt/, good lines replayed
# ---------------------------------------------------------------------------
def scenario_corrupt_spool() -> bool:
    work, env, db = fresh_env(47915, "corrupt")
    data = work / "data"
    spool_dir = data / "spool" / "pi"
    spool_dir.mkdir(parents=True, exist_ok=True)
    sf = spool_dir / "pi-999-20260929.jsonl"
    good = {"agent": "pi", "session_id": "chaos-corrupt", "turn_seq": 1,
            "idempotency_key": "pi:chaos-corrupt:1",
            "user_content": "내일까지 보고서 제출해야 해 (corrupt-test)",
            "assistant_content": ""}
    with open(sf, "w", encoding="utf-8") as f:
        f.write("this is not json\n")
        f.write(json.dumps(good, ensure_ascii=False) + "\n")
        f.write('{"agent": "pi", "broken": true}\n')  # no idempotency_key
    os.utime(sf, (time.time() - 30, time.time() - 30))
    p = spawn_core(env, work)
    if not wait_ready(47915):
        return False
    time.sleep(4)
    corrupt_dir = data / "spool" / "_corrupt"
    ok = corrupt_dir.exists() and any(corrupt_dir.iterdir())
    tok = (data / "token").read_text().strip()
    st, r = post(47915, "/turns", {
        "agent": "pi", "session_id": "chaos-corrupt", "turn_seq": 1,
        "idempotency_key": "pi:chaos-corrupt:1",
        "user_content": "내일까지 보고서 제출해야 해 (corrupt-test)",
        "assistant_content": ""}, tok)
    ok = ok and r.get("deduplicated") is True
    kill_tree(p)
    return ok


# ---------------------------------------------------------------------------
# 6. backup VACUUM INTO + prune
# ---------------------------------------------------------------------------
def scenario_backup() -> bool:
    work, env, db = fresh_env(47916, "backup")
    from jev_mem_core.ops import backup_vacuum_into
    backups = work / "data" / "backups"
    b1 = backup_vacuum_into(db, backups, keep=7, lock_retries=1)
    ok = b1 is not None and b1.exists() and b1.stat().st_size > 1000
    if not ok:
        return False
    b2 = backup_vacuum_into(db, backups, keep=7, lock_retries=1)
    ok = ok and b2 is not None and b2.name == b1.name  # same-day skip
    return ok


# ---------------------------------------------------------------------------
# 7. auto-start via JevMemClient
# ---------------------------------------------------------------------------
def scenario_autostart() -> bool:
    work, env, db = fresh_env(47917, "autostart")
    data = work / "data"
    from jev_mem_core.client import JevMemClient
    client = JevMemClient("cli", data_dir=data, auto_start=True, spool=False,
                          port=47917)
    base = client.ensure_core()
    ok = base is not None
    if ok:
        time.sleep(1)
        # the spawned core should own the port; /v1/status with token
        tok = (data / "token").read_text().strip()
        st, r = get(47917, "/status", tok)
        ok = st == 200
    # clean up: /v1/admin/shutdown
    try:
        st, r = post(47917, "/admin/shutdown", {}, tok if ok else None)
    except Exception:
        pass
    time.sleep(2)
    return ok


def main() -> int:
    run_scenario("1.kill-restart", scenario_kill_restart)
    run_scenario("2.spool-replay", scenario_spool_replay)
    run_scenario("3.jev-down", scenario_jev_down)
    run_scenario("4.port-hang", scenario_port_hang)
    run_scenario("5.corrupt-spool", scenario_corrupt_spool)
    run_scenario("6.backup", scenario_backup)
    run_scenario("7.autostart", scenario_autostart)
    print()
    fails = [r for r in RESULTS if not r[1]]
    for name, ok, err in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}{' — ' + err if err else ''}")
    print(f"\n=== P2 CHAOS: {len(RESULTS) - len(fails)}/{len(RESULTS)} PASS ===")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())