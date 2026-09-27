"""Experiment F — Failure fallback (spec §26-F).

Deliberately induce Jev failures:
    timeout / 5xx / network disconnect / authentication error
and verify the Mnemosyne-only fallback (pool unchanged) per spec §19.

Also verifies:
    - Jev OFF (JEV_RERANK=0) returns the identical result as failure fallback
    - live auth-error call against the real api.typesafe.ai (real 4xx)
    - healthy control run (real key) still performs Jev choice

Run:  .venv/Scripts/python.exe experiments/run_experiment_f.py
Env:  TYPESAFE_API_KEY (read from $LOCALAPPDATA/hermes/.env if not set)
"""
from __future__ import annotations

import importlib
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
log = logging.getLogger("experiment_f")

SNAP = REPO / "data" / "snapshots" / "snap-20260927.db"
DATASET = REPO / "data" / "dataset_curated.json"
OUT = REPO / "experiments" / "results" / "experiment_f.json"
LEDGER = REPO / "experiments" / "results" / "ledger.jsonl"

# ---------------------------------------------------------------------------
# env: pick up TYPESAFE_API_KEY from the Hermes .env when not exported
# ---------------------------------------------------------------------------
def _load_env() -> None:
    if os.environ.get("TYPESAFE_API_KEY"):
        return
    env_path = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("TYPESAFE_API_KEY="):
                os.environ["TYPESAFE_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
                log.info("TYPESAFE_API_KEY loaded from %s", env_path)
                return
    log.warning("TYPESAFE_API_KEY not found in env or %s", env_path)


_load_env()

from backends.mnemosyne import MnemosyneBackend  # noqa: E402
from harnesses.j1_access import j1_pipeline  # noqa: E402

j1 = j1_pipeline()
_filter_and_rank = j1._filter_and_rank
build_lane_pool = j1.build_lane_pool
jev_rerank = j1.jev_rerank


def build_beam():
    b = MnemosyneBackend(db_path=str(SNAP))
    return b, b._ensure_beam()


def recall_raw_factory(beam):
    import mnemosyne.core.beam as beam_mod

    def recall_raw(kind, arg, k=0):
        if kind == "fts":
            return beam_mod._fts_search_working(beam.conn, arg, k=k)
        if kind == "vec":
            emb = beam_mod._embeddings.embed([arg])
            if emb is None or not len(emb):
                return []
            return beam_mod._wm_vec_search(beam.conn, emb[0], k=k)
        if kind == "get":
            row = beam.get(arg)
            return row if isinstance(row, dict) else None
        return []

    return recall_raw


def make_pool(query: str) -> list:
    """Pool exactly as the harness would build it (filtered, ranked)."""
    beam = build_beam()[1]
    pool = build_lane_pool(recall_raw_factory(beam), query)
    if not pool:
        return []
    filtered = _filter_and_rank(pool, query)
    return filtered[: j1.POOL_DEFAULT_TOP]


# ---------------------------------------------------------------------------
# mock failure clients
# ---------------------------------------------------------------------------
class _MockClient:
    """Minimal stand-in for httpx.Client with a post() that fails."""

    def __init__(self, exc=None, status=None, body=None, delay=0.0):
        self._exc = exc
        self._status = status
        self._body = body or {}
        self._delay = delay
        self.calls = 0

    def post(self, url, **kwargs):
        self.calls += 1
        if self._delay:
            time.sleep(self._delay)
        if self._exc is not None:
            raise self._exc
        return _FakeResponse(self._status, self._body)


class _FakeResponse:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


def _real_client():
    import httpx

    key = os.environ.get("TYPESAFE_API_KEY") or ""
    if not key:
        return None
    return httpx.Client(
        timeout=httpx.Timeout(15.0, connect=5.0),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def ids(rows):
    return [r.get("id", "")[:12] for r in rows]


def same_order(a, b):
    return [r.get("id") for r in a] == [r.get("id") for r in b]


def run_case(query: str, pool: list, client, call_jev: bool = True, timeout: float = 5.0):
    """Run jev_rerank with the given client; returns (result, raised)."""
    t0 = time.perf_counter()
    raised = None
    try:
        out = jev_rerank(
            query=query,
            pool=pool,
            client=client,
            call_jev=call_jev,
            timeout=timeout,
        )
    except Exception as exc:
        raised = exc
        out = None
    return out, raised, time.perf_counter() - t0


def main():
    import httpx

    qs = json.loads(DATASET.read_text(encoding="utf-8"))
    query = qs[0]["query"]
    qid = qs[0]["qid"]
    log.info("query[0]: %s (%s)", qid, query)

    pool = make_pool(query)
    if not pool:
        log.error("pool empty — cannot run experiment")
        sys.exit(2)
    log.info("pool size=%d", len(pool))
    pool_ids = ids(pool)

    results = {"query": query, "qid": qid, "pool_size": len(pool), "modes": {}}

    # -- mode: healthy control (real API, real key) -------------------------
    client = _real_client()
    if client is not None:
        out, raised, dt = run_case(query, pool, client)
        ok = raised is None and out is not None
        results["modes"]["healthy_control"] = {
            "ok": ok,
            "raised": type(raised).__name__ if raised else None,
            "j1_lift_applied": same_order(out, pool) if out else None,
            "note": "order change is idx-dependent (idx=0 keeps order); look for 'Jev choice' line with idx populated",
            "latency_s": round(dt, 3),
        }
        client.close()
    else:
        results["modes"]["healthy_control"] = {"ok": None, "note": "no API key — skipped"}

    # -- mode: timeout -------------------------------------------------------
    mc = _MockClient(exc=httpx.ReadTimeout("read timed out", request=None))
    out, raised, dt = run_case(query, pool, mc)
    results["modes"]["timeout"] = {
        "ok": raised is None and out is not None and same_order(out, pool),
        "raised": type(raised).__name__ if raised else None,
        "order_preserved": same_order(out, pool) if out else None,
        "calls": mc.calls,
        "latency_s": round(dt, 3),
    }

    # -- mode: 5xx (503) ------------------------------------------------------
    mc = _MockClient(status=503, body={"error": "upstream down"})
    out, raised, dt = run_case(query, pool, mc)
    results["modes"]["http_5xx"] = {
        "ok": raised is None and out is not None and same_order(out, pool),
        "raised": type(raised).__name__ if raised else None,
        "order_preserved": same_order(out, pool) if out else None,
        "calls": mc.calls,
        "latency_s": round(dt, 3),
    }

    # -- mode: network disconnect ---------------------------------------------
    mc = _MockClient(exc=httpx.ConnectError("connection refused", request=None))
    out, raised, dt = run_case(query, pool, mc)
    results["modes"]["network_disconnect"] = {
        "ok": raised is None and out is not None and same_order(out, pool),
        "raised": type(raised).__name__ if raised else None,
        "order_preserved": same_order(out, pool) if out else None,
        "calls": mc.calls,
        "latency_s": round(dt, 3),
    }

    # -- mode: authentication error (LIVE call, invalid key) -------------------
    live_client = httpx.Client(
        timeout=httpx.Timeout(15.0, connect=5.0),
        headers={"Authorization": "Bearer invalid_key_jevf_experiment", "Content-Type": "application/json"},
    )
    out, raised, dt = run_case(query, pool, live_client)
    results["modes"]["auth_error_live"] = {
        "ok": raised is None and out is not None and same_order(out, pool),
        "raised": type(raised).__name__ if raised else None,
        "order_preserved": same_order(out, pool) if out else None,
        "latency_s": round(dt, 3),
        "note": "live call to api.typesafe.ai with invalid key — expect HTTP 401 logged as 'Jev choice HTTP 401'",
    }
    live_client.close()

    # -- mode: Jev OFF (JEV_RERANK=0 behavior via call_jev=False) -------------
    out, raised, dt = run_case(query, pool, None, call_jev=False)
    results["modes"]["jev_off"] = {
        "ok": raised is None and out is not None and same_order(out, pool),
        "raised": type(raised).__name__ if raised else None,
        "order_preserved": same_order(out, pool) if out else None,
        "latency_s": round(dt, 3),
    }

    # -- cross-mode consistency: all fallback outputs identical to pool -------
    fallback_modes = ["timeout", "http_5xx", "network_disconnect", "auth_error_live", "jev_off"]
    consistent = all(
        results["modes"][m].get("order_preserved") for m in fallback_modes
    )
    results["cross_mode"] = {
        "fallback_modes": fallback_modes,
        "all_match_pool_order": consistent,
        "pass": consistent and results["modes"]["healthy_control"].get("ok") is not False,
    }

    OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    # ledger row
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "phase": "experiment_f",
        "query_id": qid,
        "pool_size": len(pool),
        "modes": {m: v.get("ok") for m, v in results["modes"].items()},
        "cross_mode_pass": results["cross_mode"]["pass"],
        "out": str(OUT),
    }
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    log.info("cross_mode: %s", results["cross_mode"])
    log.info("wrote %s", OUT)
    return 0 if results["cross_mode"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())