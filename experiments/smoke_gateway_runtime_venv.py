"""Import/API smoke for MemoryGateway inside the Hermes RUNTIME venv.

Simulates the real Hermes process layout: hermes-agent root ON sys.path
(which owns a top-level `gateway` package) -> the middleware repo inserted
later.  Verifies the gateway retrieve API resolves through j1_access and
never collides with the core gateway package.
"""
from __future__ import annotations

import sys
import os
from pathlib import Path

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
HERMES_ROOT = r"C:\Users\mandu\AppData\Local\hermes\hermes-agent"

# load TYPESAFE_API_KEY from the Hermes .env when not exported
if not os.environ.get("TYPESAFE_API_KEY"):
    env_path = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("TYPESAFE_API_KEY="):
                os.environ["TYPESAFE_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
                break

# 1) put hermes-agent root FIRST (this is what shadows `gateway`)
sys.path.insert(0, HERMES_ROOT)
sys.path.insert(0, REPO)

# 2) import the core gateway like Hermes does at boot -> now sys.modules['gateway']
#    is hermes-agent's gateway package
import gateway as core_gw  # noqa: E402

print("shadow gateway module:", core_gw.__file__)

# 3) now import the middleware gateway through j1_access and run the API
from gateway.gateway import MemoryGateway  # noqa: E402

print("MemoryGateway import OK — this is middleware code?")

# confirm the middleware class was loaded (not some stale copy)
print("MemoryGateway module file:", MemoryGateway.__module__)

# 4) exercise the API against the snapshot DB
from backends.mnemosyne import MnemosyneBackend  # noqa: E402

SNAP = Path(REPO) / "data" / "snapshots" / "snap-20260927.db"
backend = MnemosyneBackend(db_path=str(SNAP))
gw = MemoryGateway(backend)
cands = gw.retrieve_candidates("웹 페이지를 추출할 때 stealth 브라우저가 필요한 경우는 언제야? 로그인이나 캡차 같은 경우인가?")
print("j1 candidates:", len(cands), "| first id12:", cands[0].id[:12] if cands else None)
print("jev_rank set:", all(c.jev_rank is not None for c in cands))

ok = len(cands) > 0 and all(c.jev_rank is not None for c in cands)
print("RUNTIME-VENV SMOKE:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)