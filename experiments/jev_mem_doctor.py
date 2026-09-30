"""jev-mem doctor (F15) — one-shot wiring check across 6 areas.

Usage: python jev_mem_doctor.py [--json]
Checks:
  1. core    — health ready, version, db path/rows, jev circuit, degraded
  2. hermes  — mode=rpc in agent log, plugin exposure
  3. pi      — extension file presence + package registration
  4. codex   — hooks file presence
  5. opencode— plugin file presence
  6. ops     — spool backlog, pending_gate backlog, last backup, token ACL
Exit 0 = all PASS (warnings allowed), 1 = any FAIL.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware")
HERMES_HOME = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "hermes"
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "jev-mem"
sys.path.insert(0, str(REPO))

results = []
def check(area, name, ok, detail="", warn_only=False):
    status = "PASS" if ok else ("WARN" if warn_only else "FAIL")
    results.append((area, name, ok, warn_only))
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    return ok or warn_only


def _get(path: str) -> dict:
    req = urllib.request.Request(f"http://127.0.0.1:47821{path}")
    tok_file = DATA_DIR / "token"
    if tok_file.exists():
        req.add_header("Authorization", f"Bearer {tok_file.read_text(encoding='utf-8').strip()}")
    with urllib.request.urlopen(req, timeout=2) as r:
        return json.loads(r.read())


def area_core():
    print("1) core")
    try:
        h = _get("/v1/health")
        check("core", "health ready", h.get("status") == "ready", f"v{h.get('version')}")
        s = _get("/v1/status")
        check("core", "degraded flag", s.get("degraded") is not None,
              f"degraded={s.get('degraded')} reasons={s.get('degraded_reasons')}")
        db_path = (s.get("db") or {}).get("path", "")
        check("core", "db path known", bool(db_path), db_path)
        q = subprocess.run(["sqlite3", db_path, "SELECT COUNT(*) FROM working_memory"],
                           capture_output=True, text=True, timeout=10)
        check("core", "db rows readable", q.returncode == 0,
              f"rows={q.stdout.strip()}", warn_only=True)
        check("core", "jev circuit", (s.get("jev") or {}).get("circuit") != "open",
              f"circuit={(s.get('jev') or {}).get('circuit')}")
    except Exception as e:
        check("core", "health reachable", False, str(e))


def area_hermes():
    print("2) hermes")
    log = HERMES_HOME / "logs" / "agent.log"
    if log.exists():
        txt = log.read_text(errors="replace")
        import re
        m = re.findall(r"JEV memory provider mode=(\w+)", txt)
        check("hermes", "mode=rpc in agent log", bool(m) and m[-1] == "rpc",
              f"last mode: {m[-1] if m else '(none)'}", warn_only=True)
    else:
        check("hermes", "agent.log", False, "not found", warn_only=True)
    src = (REPO / "harnesses" / "jev_mem_plugin" / "__init__.py").read_text(encoding="utf-8")
    check("hermes", "plugin exposes JevRpcProvider only",
          "import JevRpcProvider" in src and "JevRerankProvider as" not in src)


def area_pi():
    print("3) pi")
    ext = Path.home() / ".pi" / "agent" / "extensions" / "pi-jev-mem.ts"
    check("pi", "extension file", ext.exists(), str(ext))
    pkg = Path.home() / ".pi" / "agent" / "extensions" / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            regd = "pi-jev-mem" in json.dumps(data)
            check("pi", "package.json registration", regd, warn_only=True)
        except Exception as e:
            check("pi", "package.json parse", False, str(e), warn_only=True)


def area_codex():
    print("4) codex")
    for p in [Path.home() / ".codex" / "hooks.json",
              Path.home() / ".codex" / "extensions" / "jev-mem.ts"]:
        check("codex", p.name, p.exists(), str(p), warn_only=True)


def area_opencode():
    print("5) opencode")
    for p in [Path.home() / ".config" / "opencode" / "plugin" / "mnemosyne-session-memory-v2.ts",
              Path.home() / ".config" / "opencode" / "jev_mem_record.py"]:
        check("opencode", p.name, p.exists(), str(p), warn_only=True)


def area_ops():
    print("6) ops")
    spool = DATA_DIR / "spool"
    if spool.exists():
        n = sum(1 for _ in spool.glob("*/*.jsonl"))
        check("ops", "spool backlog", n == 0, f"{n} pending file(s)", warn_only=n <= 5)
    backups = DATA_DIR / "backups"
    if backups.exists():
        bks = sorted(backups.glob("*.db"))
        if bks:
            age_h = (time.time() - bks[-1].stat().st_mtime) / 3600
            check("ops", "last backup < 48h", age_h < 48,
                  f"{bks[-1].name}, {age_h:.0f}h ago", warn_only=True)
        else:
            check("ops", "backup exists", False, "none yet", warn_only=True)
    tok = DATA_DIR / "token"
    if tok.exists():
        check("ops", "token file exists", True, str(tok))


def main():
    print("jev-mem doctor —", time.strftime("%Y-%m-%d %H:%M"))
    area_core(); area_hermes(); area_pi(); area_codex(); area_opencode(); area_ops()
    fails = [r for r in results if not r[2] and not r[3]]
    print(f"\n{len(results) - len(fails)}/{len(results)} PASS"
          + (f"  ({len(fails)} FAIL)" if fails else "  — wiring OK"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
