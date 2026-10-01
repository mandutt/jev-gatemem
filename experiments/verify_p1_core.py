"""P1 verification — golden test: embedded path vs core RPC path (B §16.1).

Runs against a COPY of the snapshot DB (never production):
  1. Start jev-mem-core as a subprocess on a scratch data dir.
  2. Embedded: j1_engine.run() against the same DB.
  3. RPC: POST /v1/prefetch.
  4. Compare the two Context blocks (JEV skipped in both — determinism).
  5. Turn path: POST /v1/turns (async) with idempotency_key; verify ledger
     + working_memory rows appear with v1.1 D12 metadata.

Exit 0 = all PASS.
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
WORK = SCRATCH / "p1_probe" / f"run_{int(time.time())}"
DATA = WORK / "data"
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / "mnemosyne.db"
if DB.exists():
    for suf in ("", "-wal", "-shm"):
        p = Path(str(DB) + suf)
        p.unlink(missing_ok=True)
shutil.copy2(SNAP, DB)

PY = r"C:\Users\mandu\AppData\Local\hermes\installs\315db7b763fb0d0a\environments\746564964b1042b79add42260378503b\venv\Scripts\python.exe"
PORT = 47901
BASE = f"http://127.0.0.1:{PORT}/v1"

env = dict(os.environ)
env["JEV_MEM_PORT"] = str(PORT)
env["JEV_MEM_DATA_DIR"] = str(DATA)
env["JEV_MEM_DB"] = str(DB)
env["JEV_WRITE_GATE"] = "0"  # gate off for determinism in golden test (JEV skip)
# P1 (2026-10-01): embedding warmup fail-fast guard — this golden test does
# not exercise embeddings (JEV skipped, DB-only), so demote warmup failure
# to a warning instead of letting the new default fail-fast exit(9).
env["JEV_MEM_EMBED_WARMUP"] = "warn"


def wait_ready(timeout=25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(f"{BASE}/health", timeout=0.5) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def post(path, body, token=None, raw=False):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read().decode()
            return r.status, (data if raw else json.loads(data))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def main():
    # 1. embedded baseline
    sys.path.insert(0, str(REPO))
    os.environ["JEV_WRITE_GATE"] = "0"

    procs = subprocess.Popen(
        [PY, "-m", "jev_mem_core", "--serve"],
        cwd=str(REPO), env=env,
        stdout=open(WORK / "core.log", "wb"), stderr=subprocess.STDOUT,
    )
    try:
        if not wait_ready():
            out = (WORK / "core.log").read_text(errors="replace")
            print("FAIL: core did not become ready")
            print(out[-2000:])
            return 1

        # token
        tok = (DATA / "token").read_text().strip()

        # 2. embedded golden (no JEV)
        from core import j1_engine
        from gateway import j1_pipeline
        from mnemosyne.core.beam import BeamMemory
        import sqlite3

        beam = BeamMemory(session_id="golden", db_path=DB)
        queries = [
            "메모리 아키텍처 설명",
            "타입세이프 API 사용법",
            "파이 확장 코드그래프",
        ]
        embedded_blocks = {}
        for q in queries:
            block = j1_engine.run(beam, q, pipeline=j1_pipeline, client=None, top_k=5)
            embedded_blocks[q] = block
        beam.conn.close()

        # 3. RPC /v1/prefetch (same DB, JEV off)
        rpc_blocks = {}
        metas = {}
        for q in queries:
            st, resp = post("/prefetch", {
                "agent": "test", "session_id": "golden-session", "query": q,
                "options": {"rerank": False, "timeout_ms": 2000},
            }, token=tok)
            if st != 200:
                print(f"FAIL: prefetch {q} -> {st} {resp}")
                print(f"  meta: {metas}")
                return 1
            rpc_blocks[q] = resp.get("context", "")
            metas[q] = resp.get("meta", {})
        print(f"prefetch metas: {metas}")

        # 4. compare
        fails = []
        for q in queries:
            e, r = embedded_blocks.get(q, ""), rpc_blocks.get(q, "")
            if e != r:
                fails.append(f"golden mismatch [{q}]: embedded len={len(e)} rpc len={len(r)}")
                fails.append(f"  embedded head: {e[:80]!r}")
                fails.append(f"  rpc head:      {r[:80]!r}")
        print(f"golden: {'PASS' if not fails else 'FAIL'} "
              f"({sum(1 for q in queries if embedded_blocks[q] == rpc_blocks[q])}/{len(queries)} identical)")
        for f in fails:
            print(" ", f)

        # 5. turn path
        st, resp = post("/turns", {
            "agent": "test", "session_id": "golden-session", "turn_seq": 1,
            "idempotency_key": "test:golden-session:1",
            "user_content": "P1 integration test user turn",
            "assistant_content": "P1 integration test assistant turn",
            "mode": "async",
        }, token=tok)
        print(f"turns async: st={st} resp={resp}")
        turn_ok = st == 202 and resp.get("status") in ("stored", "skipped", "pending_gate")

        # wait for writer to finish
        time.sleep(1.5)
        # verify ledger + working_memory with metadata
        import sqlite3 as sq
        state = sq.connect(DATA / "core_state.db")
        state.row_factory = sq.Row
        lrow = state.execute("SELECT * FROM ingest_ledger WHERE idem_key=?", ("test:golden-session:1",)).fetchone()
        state.close()
        ledger_ok = lrow is not None and lrow["status"] in ("stored", "skipped")
        mem = sq.connect(DB)
        mem.row_factory = sq.Row
        mrow = mem.execute(
            "SELECT id, content, metadata_json FROM working_memory WHERE metadata_json LIKE ?",
            ('%"idem_key": "test:golden-session:1"%',),
        ).fetchone()
        meta_ok = mrow is not None
        mem.close()

        # 6. duplicate retry (idempotency)
        st2, resp2 = post("/turns", {
            "agent": "test", "session_id": "golden-session", "turn_seq": 1,
            "idempotency_key": "test:golden-session:1",
            "user_content": "P1 integration test user turn",
            "assistant_content": "P1 integration test assistant turn",
            "mode": "async",
        }, token=tok)
        dup_ok = st2 in (200, 202) and resp2.get("deduplicated") is True

        print(f"ledger: {'PASS' if ledger_ok else 'FAIL'} (status={lrow['status'] if lrow else None})")
        print(f"metadata(D12): {'PASS' if meta_ok else 'FAIL'} content={mrow['content'][:40] if mrow else None!r}")
        print(f"idempotency: {'PASS' if dup_ok else 'FAIL'} st={st2} dedup={resp2.get('deduplicated') if isinstance(resp2, dict) else None}")

        # 7. auth guard
        st_a, resp_a = post("/turns", {"agent": "x", "session_id": "s", "user_content": "a",
                                       "assistant_content": "", "idempotency_key": "x:s:1"})
        auth_ok = st_a == 401

        # 8. missing idempotency key -> 400 (D5)
        st_m, resp_m = post("/turns", {"agent": "x", "session_id": "s", "user_content": "a",
                                       "assistant_content": ""}, token=tok)
        idem_required_ok = st_m == 400

        all_ok = (not fails) and turn_ok and ledger_ok and meta_ok and dup_ok and auth_ok and idem_required_ok
        print(f"\nauth-guard: {'PASS' if auth_ok else 'FAIL'}")
        print(f"idem-required: {'PASS' if idem_required_ok else 'FAIL'}")
        print(f"\n=== P1 {'ALL PASS' if all_ok else 'FAILURES'} ===")

        # shutdown
        try:
            post("/admin/shutdown", {}, token=tok)
        except Exception:
            pass
        return 0 if all_ok else 1
    finally:
        procs.terminate()
        try:
            procs.wait(timeout=5)
        except subprocess.TimeoutExpired:
            procs.kill()


if __name__ == "__main__":
    sys.exit(main())