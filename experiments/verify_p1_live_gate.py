"""P1 verification 2 — live JEV gate path through the core (JEV ON)."""
import json, os, shutil, subprocess, sys, time
import urllib.error, urllib.request
from pathlib import Path

REPO = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware")
SNAP = REPO / "data" / "snapshots" / "snap-20260927.db"
SCRATCH = Path(os.environ.get("TMPDIR", r"C:\Users\mandu\AppData\Local\hermes\cache\scratch"))
WORK = SCRATCH / "p1_live" / f"run_{int(time.time())}"
DATA = WORK / "data"; DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / "mnemosyne.db"
for suf in ("", "-wal", "-shm"):
    Path(str(DB) + suf).unlink(missing_ok=True)
shutil.copy2(SNAP, DB)

PY = r"C:\Users\mandu\AppData\Local\hermes\installs\315db7b763fb0d0a\environments\746564964b1042b79add42260378503b\venv\Scripts\python.exe"
PORT = 47902
BASE = f"http://127.0.0.1:{PORT}/v1"
env = dict(os.environ)
env["JEV_MEM_PORT"] = str(PORT); env["JEV_MEM_DATA_DIR"] = str(DATA); env["JEV_MEM_DB"] = str(DB)
# TYPESAFE_API_KEY 부재 시 Hermes .env에서 주입 (core가 os.environ에서 읽음)
if "TYPESAFE_API_KEY" not in env or not env.get("TYPESAFE_API_KEY"):
    _envf = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / ".env"
    if _envf.exists():
        for line in _envf.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("TYPESAFE_API_KEY="):
                env["TYPESAFE_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
print("JEV key injected:", bool(env.get("TYPESAFE_API_KEY")))

def wait_ready(timeout=25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(f"{BASE}/health", timeout=0.5) as r:
                if r.status == 200: return True
        except Exception: time.sleep(0.3)
    return False

def post(path, body, token=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    if token: req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())

procs = subprocess.Popen([PY, "-m", "jev_mem_core", "--serve"], cwd=str(REPO), env=env,
                         stdout=open(WORK / "core.log", "wb"), stderr=subprocess.STDOUT)
try:
    if not wait_ready():
        print("FAIL: not ready"); print((WORK/"core.log").read_text()[-1500:]); sys.exit(1)
    tok = (DATA / "token").read_text().strip()

    # gate: user "내일까지 보고서 제출해야 해" (gold KEEP), asst "이제 ...분석한다" (gold SKIP)
    st, resp = post("/turns", {
        "agent": "test", "session_id": "live-sess", "turn_seq": 1,
        "idempotency_key": "test:live-sess:1",
        "user_content": "내일까지 보고서 제출해야 해",
        "assistant_content": "이제 남은 항목들을 분석한다",
        "mode": "sync",
    }, token=tok)
    print("sync turn:", st, json.dumps(resp, ensure_ascii=False)[:400])
    d = resp.get("decisions", {})
    user_keep = d.get("user", {}).get("keep")
    asst_keep = d.get("assistant", {}).get("keep")
    ok = st == 200 and user_keep is True and asst_keep is False
    print(f"live gate: {'PASS' if ok else 'FAIL'} (user KEEP={user_keep}, asst SKIP={asst_keep})")

    # runtime latency
    print("gate lat:", d.get("user", {}).get("latency_ms"), d.get("assistant", {}).get("latency_ms"))
    sys.exit(0 if ok else 1)
finally:
    procs.terminate()
    try: procs.wait(timeout=5)
    except subprocess.TimeoutExpired: procs.kill()