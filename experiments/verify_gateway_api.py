"""Verify the completed MemoryGateway retrieve API (J1 path).

Checks (against the snapshot DB, real Jev API for the live path):
  1. use_j1=True (default): J1 pipeline runs — logs 'Jev choice', returns
     MemoryCandidate headers with jev_rank set.
  2. use_j1=False: Phase 0 surface — backend.recall + excerpts, no Jev.
  3. retrieve(ids): full hydration via public get() — ids round-trip.
  4. Fallback (spec §19): no key / failure -> pool-only, never raises.
  5. Shadowing safety: import path goes through harnesses.j1_access.

Run:  .venv/Scripts/python.exe experiments/verify_gateway_api.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("verify_gateway")

SNAP = REPO / "data" / "snapshots" / "snap-20260927.db"
DATASET = REPO / "data" / "dataset_curated.json"


def _load_env() -> None:
    if os.environ.get("TYPESAFE_API_KEY"):
        return
    env_path = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("TYPESAFE_API_KEY="):
                os.environ["TYPESAFE_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
                return


_load_env()

from backends.mnemosyne import MnemosyneBackend
from gateway.gateway import MemoryGateway
from gateway.types import MemoryCandidate, MemoryRecord

qs = json.loads(DATASET.read_text(encoding="utf-8"))
q = qs[0]
query = q["query"]

backend = MnemosyneBackend(db_path=str(SNAP))
gw = MemoryGateway(backend)

results = {}

# 1) J1 path (live Jev)
t0 = time.perf_counter()
cands = gw.retrieve_candidates(query)
dt = time.perf_counter() - t0
results["j1_path"] = {
    "n": len(cands),
    "all_candidates": all(isinstance(c, MemoryCandidate) for c in cands),
    "jev_rank_set": all(c.jev_rank is not None for c in cands),
    "first_id12": cands[0].id[:12] if cands else None,
    "latency_s": round(dt, 3),
    "note": "check log for 'Jev choice' line",
}

# 2) Phase 0 surface (use_j1=False)
cands0 = gw.retrieve_candidates(query, use_j1=False)
results["phase0_surface"] = {
    "n": len(cands0),
    "all_candidates": all(isinstance(c, MemoryCandidate) for c in cands0),
    "jev_rank_none": all(c.jev_rank is None for c in cands0),
}

# 3) retrieve(ids) hydration round-trip
ids = [c.id for c in cands[:3]]
recs = gw.retrieve(ids)
results["retrieve_hydration"] = {
    "requested": len(ids),
    "returned": len(recs),
    "all_records": all(isinstance(r, MemoryRecord) for r in recs),
    "ids_roundtrip": sorted(r.id for r in recs) == sorted(ids),
    "has_content": all(bool(r.content) for r in recs),
}

# 4) fallback: no key -> pool-only, never raises
key_backup = os.environ.pop("TYPESAFE_API_KEY", None)
try:
    t0 = time.perf_counter()
    cands_nk = gw.retrieve_candidates(query)
    dt = time.perf_counter() - t0
    results["fallback_no_key"] = {
        "n": len(cands_nk),
        "never_raised": True,
        "jev_rank_not_set": all(c.jev_rank is None for c in cands_nk),
        "latency_s": round(dt, 3),
    }
finally:
    if key_backup:
        os.environ["TYPESAFE_API_KEY"] = key_backup

# 5) shadowing safety: gateway is importable through the accessor in this
#    process too (jit — the middleware's gateway path was already exercised;
#    here we confirm the accessor resolves to the middleware module).
from harnesses.j1_access import j1_pipeline

j1 = j1_pipeline()
results["accessor_resolution"] = {
    "module": j1.__name__,
    "has_jev_rerank": hasattr(j1, "jev_rerank"),
    "has_build_lane_pool": hasattr(j1, "build_lane_pool"),
}

pass_all = (
    results["j1_path"]["n"] > 0
    and results["j1_path"]["all_candidates"]
    and results["j1_path"]["jev_rank_set"]
    and results["phase0_surface"]["n"] > 0
    and results["phase0_surface"]["jev_rank_none"]
    and results["retrieve_hydration"]["ids_roundtrip"]
    and results["retrieve_hydration"]["has_content"]
    and results["fallback_no_key"]["never_raised"]
    and results["accessor_resolution"]["has_jev_rerank"]
)
results["pass"] = pass_all

print(json.dumps(results, indent=2, ensure_ascii=False))
sys.exit(0 if pass_all else 1)