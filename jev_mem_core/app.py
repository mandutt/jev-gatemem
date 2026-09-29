"""jev-mem-core app bootstrap: config, singleton, context wiring, run (P1).

Usage:
    python -m jev_mem_core --serve            # detached
    python -m jev_mem_core --check            # health probe
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import signal
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from . import PROTOCOL, __version__
from .config import Config
from .ledger import init_schema as init_ledger_schema
from .ledger import recover_incomplete
from .pipeline import CircuitBreaker
from .server import CoreServer
from .writer import ReaderPool, SingleWriter, WriterContext

log = logging.getLogger("jev_mem.app")

# stdlib sqlite3 busy timeout for core_state (own DB, no contention)
_STATE_BUSY_MS = 5000


class CoreContext:
    """Everything the pipelines need. Owned by the event loop + threads."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.started_at = time.monotonic()
        self.breaker = CircuitBreaker(failures=5, open_s=30.0)
        self.jev_sem = None  # asyncio.Semaphore — set in run()
        self.writer: Optional[SingleWriter] = None
        self.readers: Optional[ReaderPool] = None
        self._session_locks: Dict[str, asyncio.Lock] = {}
        self._session_locks_lru: list = []
        self._embed_pool = None  # ThreadPoolExecutor for embedding (D3a)

    def session_lock(self, key: str) -> asyncio.Lock:
        lock = self._session_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[key] = lock
            self._session_locks_lru.append(key)
            # bound the map (LRU-ish)
            if len(self._session_locks_lru) > 2000:
                old = self._session_locks_lru.pop(0)
                self._session_locks.pop(old, None)
        return lock


def make_token(cfg: Config) -> str:
    """Load or create the bearer token (B §10)."""
    tp = cfg.token_path
    if tp.exists():
        tok = tp.read_text(encoding="utf-8").strip()
        if tok:
            return tok
    tok = secrets.token_hex(32)
    tp.parent.mkdir(parents=True, exist_ok=True)
    tp.write_text(tok, encoding="utf-8")
    try:  # best-effort ACL: user-only read
        import subprocess
        subprocess.run(
            ["icacls", str(tp), "/inheritance:r", "/grant:r", f"{os.environ.get('USERNAME','')}:F"],
            capture_output=True, timeout=10)
    except Exception:
        pass
    return tok


def _make_beam(db_path: Path, session_id: str = "default"):
    """Thread-local BeamMemory factory (writer thread)."""
    from mnemosyne.core.beam import BeamMemory
    return BeamMemory(session_id=session_id, db_path=db_path)


def _make_ro_beam(db_path: Path, session_id: str = "ro"):
    """Read-only Beam shim (v1.1 D13) — j1_engine uses beam.conn only."""
    conn = sqlite3.connect(
        f"file:{Path(db_path).as_posix()}?mode=ro", uri=True,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")  # WAL readers never block long
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
    except Exception:
        pass
    beam = type("ROBeam", (), {})()
    beam.conn = conn
    beam.session_id = session_id
    return beam


def _make_state_conn(db_path: Path):
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={_STATE_BUSY_MS}")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def build_context(cfg: Config) -> CoreContext:
    ctx = CoreContext(cfg)
    cfg.mnemosyne_db.parent.mkdir(parents=True, exist_ok=True)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)

    def writer_factory() -> WriterContext:
        beam = _make_beam(cfg.mnemosyne_db, session_id="core-writer")
        st = _make_state_conn(cfg.state_db)
        init_ledger_schema(st)
        return WriterContext(beam=beam, state=st)

    def reader_factory():
        return _make_ro_beam(cfg.mnemosyne_db)

    def on_close(wctx: Optional[WriterContext]) -> None:
        if wctx is None:
            return
        try:
            wctx.beam.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        try:
            wctx.beam.conn.close()
        except Exception:
            pass
        try:
            wctx.state.close()
        except Exception:
            pass

    ctx.writer = SingleWriter(writer_factory, max_depth=cfg.writer_max_queue_depth,
                              slow_job_warn_ms=cfg.writer_slow_job_warn_ms,
                              on_close=on_close)
    ctx.readers = ReaderPool(reader_factory, workers=cfg.readers_workers)
    return ctx


async def _recover_pending(ctx: CoreContext, pipeline) -> int:
    """Requeue received/gated/pending_gate rows (B §6.4) — v1.1 D12 check."""
    from . import ledger, store

    rows = await ctx.writer.submit(lambda w: recover_incomplete(w.state), "recover_scan")
    if not rows:
        return 0
    requeued = 0
    for r in rows:
        idem_key = r["idem_key"]
        payload = r["payload"]
        if payload is None:
            # payload cleared — nothing to replay; mark failed
            await ctx.writer.submit(
                lambda w, k=idem_key: ledger.ledger_mark(w.state, k, "failed",
                                                         last_error="payload_lost", clear_payload=True),
                "recover_fail")
            continue
        # D12: crash window — already stored?
        already = await ctx.writer.submit(
            lambda w, k=idem_key: store.find_stored_by_idem(w.beam.conn, k) or
                                  store.find_stored_by_idem_episodic(w.beam.conn, k),
            "recover_idem_check")
        if already:
            await ctx.writer.submit(
                lambda w, k=idem_key: ledger.ledger_mark(w.state, k, "stored",
                                                         memory_ids=[already], clear_payload=True),
                "recover_stored")
            continue
        # requeue through the normal pipeline (async fire-and-forget)
        asyncio.ensure_future(_guard_requeue(pipeline, payload, idem_key))
        requeued += 1
    return requeued


async def _guard_requeue(pipeline, payload: Dict, idem_key: str) -> None:
    try:
        payload["idempotency_key"] = idem_key
        await pipeline.process_turn(payload, recovery=True)
    except Exception:
        log.exception("replay turn failed for %s", idem_key)


async def _serve(cfg: Config) -> None:
    token = make_token(cfg)

    # singleton: try binding the port first — EADDRINUSE -> probe existing core
    ctx = build_context(cfg)
    server = CoreServer(cfg, ctx, token)
    ctx.jev_sem = asyncio.Semaphore(cfg.jev_max_concurrency)

    # writer thread + warmup + recovery BEFORE accepting traffic
    ctx.writer.start(timeout=60)
    await asyncio.to_thread(_warmup_embedding, cfg)

    # recover pending rows
    pipeline = server.pipeline
    try:
        n = await _recover_pending(ctx, pipeline)
        if n:
            log.info("recovered %d pending turn(s)", n)
    except Exception:
        log.exception("recovery failed")

    try:
        await server.start()
    except OSError as e:
        # port in use
        ok = await _probe_health(cfg)
        if ok:
            log.info("another jev-mem-core is already serving on :%d — exiting", cfg.port)
            ctx.writer.stop()
            return
        log.error("port %d occupied by a non-responsive process (EADDRINUSE: %s) — exit 3", cfg.port, e)
        ctx.writer.stop()
        sys.exit(3)

    # write core.json
    cfg.core_json_path.write_text(json.dumps({
        "port": cfg.port, "pid": os.getpid(), "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "protocol": PROTOCOL, "version": __version__,
    }), encoding="utf-8")

    log.info("jev-mem-core %s ready (protocol %d, writing %s)",
             __version__, PROTOCOL, cfg.mnemosyne_db)

    stop_evt = server._shutdown_evt
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_evt.set)
        except NotImplementedError:
            pass  # Windows: no add_signal_handler for SIGTERM — handled below

    try:
        await stop_evt.wait()
    finally:
        log.info("shutting down…")
        try:
            await server.stop()
        finally:
            ctx.writer.stop()
            try:
                ctx.core_json_path.unlink(missing_ok=True)
            except Exception:
                pass
            log.info("bye")


def _warmup_embedding(cfg: Config) -> None:
    """Load the embedding model once (v1.1 D14: process-global)."""
    try:
        import mnemosyne.core.beam as beam_mod
        if not beam_mod._embeddings.available():
            return
        beam_mod._embeddings.embed(["warmup"])
    except Exception as e:
        log.warning("embedding warmup failed: %s", e)


async def _probe_health(cfg: Config) -> bool:
    try:
        import httpx
        async with httpx.AsyncClient(timeout=0.5) as c:
            r = await c.get(f"http://{cfg.host}:{cfg.port}/v1/health")
            return r.status_code == 200
    except Exception:
        return False


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="jev-mem-core")
    p.add_argument("--serve", action="store_true", help="run the core server")
    p.add_argument("--check", action="store_true", help="probe health of a running core")
    p.add_argument("--config", type=Path, default=None, help="config.toml path")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    cfg = Config.load(args.config)

    if args.check:
        ok = asyncio.run(_probe_health(cfg))
        print("ready" if ok else "down")
        sys.exit(0 if ok else 1)

    if not args.serve:
        p.print_help()
        sys.exit(0)

    try:
        asyncio.run(_serve(cfg))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()