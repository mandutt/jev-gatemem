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
from .ops import backup_vacuum_into, checkpoint_passive
from .pipeline import CircuitBreaker
from .redact import active as _redact_active
from .redact import get_patterns as _redact_patterns
from .server import CoreServer
from .spool import SpoolScanner, SpoolWriter
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
        # P2: operational state
        self.scanner: Optional[SpoolScanner] = None
        self.spool_writer: Optional[SpoolWriter] = None
        self.last_backup_at = 0.0
        self.last_checkpoint_at = 0.0
        self.synced_folder_warning = False
        self._last_pending_check = 0.0
        self._last_tick = time.monotonic()
        # D-5 (idle shutdown): last non-probe activity. /health and /metrics
        # do NOT refresh this — only real work (prefetch/turns/tools) does.
        self.last_activity_at = time.monotonic()
        # F11: consecutive fail-open KEEP verdicts (degraded signal)
        self.fail_open_streak = 0
        # P1 (S4 2026-10-01): embedding model state — set at startup warmup,
        # exposed via /v1/status so a silent MiniLM fallback is impossible.
        self.embedding: Dict[str, Any] = {
            "model": None,         # actual loaded model name (alias or raw)
            "dim": None,           # embedding dimension (env-aware)
            "warmup_ok": False,    # startup warmup succeeded
            "warmup_error": None,  # str(e) when warmup failed / unavailable
        }
        self.stats: Dict[str, Any] = {
            "jev_calls": 0, "jev_failures": 0,
            "turns": {"stored": 0, "skipped": 0, "pending_gate": 0, "failed": 0},
            "dedup_count": 0, "spool_replayed": 0,
            "embed_ms": 0.0, "rss_mb": 0.0,
            "prefetch_degraded": 0, "prefetch_total": 0,
        }

    def touch_activity(self) -> None:
        self.last_activity_at = time.monotonic()

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


async def _check_synced_folder(cfg: Config) -> bool:
    """B §13: warn when DB sits under a sync-folder (OneDrive/Dropbox/…)."""
    db = cfg.mnemosyne_db.resolve()
    markers = ("onedrive", "dropbox", "google drive", "iCloudDrive", "icloud")
    try:
        parts = [p.name.lower() for p in db.parents]
    except Exception:
        return False
    return any(m in part for part in parts for m in markers)


async def _op_loop(ctx: CoreContext, pipeline) -> None:
    """P2 periodic ops: pending_gate re-judge, checkpoint, backup, spool scan."""
    cfg = ctx.cfg
    pending_iv = cfg.pending_gate_retry_interval_s
    check_iv = cfg.checkpoint_idle_interval_s
    backup_iv = cfg.backup_interval_h * 3600
    while True:
        # 1 min tick — cheap, keeps loops aligned. Watchdog measures the
        # OVERRUN of this sleep (true event-loop block), not the tick
        # interval itself: a sleep(60) that returns on time logs nothing,
        # while a loop blocked for >5s past the wakeup is a real stall.
        tick_start = time.monotonic()
        await asyncio.sleep(60)
        now = time.monotonic()

        # 1) pending_gate re-judge (only while circuit closed) — B §8.2
        if now - ctx._last_pending_check >= pending_iv:
            ctx._last_pending_check = now
            if not ctx.breaker.is_open:
                try:
                    r = await pipeline.requeue_pending_gate(
                        max_age_h=cfg.pending_gate_max_age_h,
                        batch=cfg.pending_gate_batch)
                    if r.get("rejudged") or r.get("expired"):
                        log.info("pending_gate: rejudged=%s expired=%s left=%s",
                                 r["rejudged"], r["expired"], r["left"])
                except Exception:
                    log.exception("pending_gate rejudge loop error")

        # 2) WAL checkpoint (idle) — B §13
        if now - ctx.last_checkpoint_at >= check_iv:
            ctx.last_checkpoint_at = now
            try:
                chk = await asyncio.to_thread(checkpoint_passive, cfg.mnemosyne_db)
                if not chk.get("ok"):
                    log.warning("wal_checkpoint PASSIVE: %s", chk.get("detail"))
            except Exception:
                log.exception("checkpoint error")

        # 3) daily backup (VACUUM INTO, keep N) — B §13
        if now - ctx.last_backup_at >= backup_iv:
            ctx.last_backup_at = now
            try:
                bkp = await asyncio.to_thread(
                    backup_vacuum_into, cfg.mnemosyne_db,
                    cfg.data_dir / "backups", cfg.backup_keep,
                    cfg.backup_lock_retries)
                if bkp is None:
                    log.warning("backup failed — will retry next cycle")
                    ctx.last_backup_at = 0.0
            except Exception:
                log.exception("backup error")
                ctx.last_backup_at = 0.0

        # 4) spool scan (10 min) — B §9.3
        if ctx.scanner is not None:
            try:
                r = await asyncio.to_thread(ctx.scanner.maybe_scan)
                if r and r.get("files"):
                    log.info("spool scan: %s", r)
                    ctx.stats["spool_replayed"] += r.get("lines", 0)
            except Exception:
                log.exception("spool scan error")

        # 5) watchdog: event-loop lag > 5s (B §14) — overrun of the 60s tick
        lag = time.monotonic() - tick_start - 60.0
        if lag > 5.0:
            log.warning("event loop lag %.1fs (watchdog)", lag)
        ctx._last_tick = time.monotonic()

        # 6) D-5 idle shutdown: graceful exit when idle for idle_shutdown_min.
        # Conditions (ALL required, review F10):
        #   - no non-probe activity for N minutes
        #   - writer queue empty
        #   - no pending_gate backlog and no spool files
        idle_min = cfg.idle_shutdown_min
        if idle_min > 0 and now - ctx.last_activity_at >= idle_min * 60:
            queue_depth = -1
            pending = -1
            spool_files = -1
            try:
                queue_depth = ctx.writer.depth() if ctx.writer else 0
            except Exception:
                queue_depth = -1
            try:
                from . import ledger as _ledger
                pending = await asyncio.to_thread(
                    _ledger.pending_gate_count, ctx.writer.state) if ctx.writer else 0
            except Exception:
                pending = -1
            try:
                spool_files = (len(list((cfg.data_dir / "spool").glob("*.jsonl")))
                               if (cfg.data_dir / "spool").exists() else 0)
            except Exception:
                spool_files = -1
            if queue_depth == 0 and pending == 0 and spool_files == 0:
                log.info("idle shutdown: no activity for %s min, queues empty — exiting",
                         idle_min)
                raise SystemExit(0)
            log.info("idle shutdown deferred: queue=%s pending=%s spool=%s",
                     queue_depth, pending, spool_files)


async def _apply_data_dir_acl(cfg: Config) -> None:
    """B §5.3 승인 1번: %LOCALAPPDATA%/jev-mem 사용자 전용 ACL (best-effort).

    token 파일과 동일 정책(icacls /inheritance:r /grant:r <user>:F)을
    data_dir 전체에 적용. 기본 data_dir에서만 실행(테스트 스크래치 제외 +
    시스템 폴더 회피를 위해 항상 시도하되 실패는 무시).
    """
    try:
        import subprocess
        user = os.environ.get("USERNAME") or os.environ.get("USER")
        if not user:
            return
        d = str(cfg.data_dir)
        subprocess.run(
            ["icacls", d, "/inheritance:r", "/grant:r", f"{user}:F",
             "/T", "/Q"], capture_output=True, timeout=30)
        log.info("data dir ACL applied (user-only): %s", d)
    except Exception as e:
        log.warning("data dir ACL failed: %s", e)


def _verify_db_identity(wctx, cfg: Config, accept_change: bool) -> None:
    """F8: record db_path + working_memory row count in core_meta; refuse
    start when the DB identity changed (path moved or rows collapsed to 0
    vs recorded) unless --accept-db-change. Guards silent DB forks.
    Runs INSIDE the writer thread via submit (owns core_state.db conn)."""
    import hashlib
    conn = wctx.state
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS core_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
    except Exception:
        return  # state conn unusable — skip guard (writer will surface errors)
    db_norm = str(cfg.mnemosyne_db.resolve()).lower()
    db_id = hashlib.sha256(db_norm.encode()).hexdigest()[:16]
    row = conn.execute(
        "SELECT value FROM core_meta WHERE key='db_identity'").fetchone()
    prev = json.loads(row[0]) if row else None
    # current row count (read-only on the memory DB)
    try:
        mconn = sqlite3.connect(f"file:{cfg.mnemosyne_db}?mode=ro", uri=True, timeout=5)
        n_rows = mconn.execute("SELECT COUNT(*) FROM working_memory").fetchone()[0]
        mconn.close()
    except Exception:
        n_rows = -1
    if prev and not accept_change:
        if prev.get("db_path") != db_norm:
            log.error("DB identity changed: recorded=%s now=%s — refusing "
                      "(--accept-db-change to override)", prev.get("db_path"), db_norm)
            sys.exit(5)
        if prev.get("rows", 0) > 100 and n_rows == 0:
            log.error("working_memory collapsed: %s -> 0 rows — refusing "
                      "(--accept-db-change to override)", prev.get("rows"))
            sys.exit(5)
    conn.execute(
        "INSERT INTO core_meta (key, value) VALUES ('db_identity', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (json.dumps({"db_path": db_norm, "db_id": db_id,
                     "rows": n_rows, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}),))
    conn.commit()
    log.info("db identity: id=%s rows=%s", db_id, n_rows)


async def _serve(cfg: Config) -> None:
    token = make_token(cfg)

    # F8 (2026-09-30, review): DB identity check BEFORE anything touches the
    # DB. Refuse to start when the configured DB file is missing (silent fork
    # risk — measured: auto-started core once created an empty DB); allow
    # --init-db to override. Also record db_path+row count in core_meta and
    # refuse on path change / row collapse unless --accept-db-change.
    init_db = "--init-db" in sys.argv
    accept_change = "--accept-db-change" in sys.argv
    if not cfg.mnemosyne_db.exists() and not init_db:
        log.error("mnemosyne.db not found at %s — refusing to start "
                  "(silent-fork guard; pass --init-db to create)", cfg.mnemosyne_db)
        sys.exit(4)
    if not cfg.mnemosyne_db.exists() and init_db:
        cfg.mnemosyne_db.parent.mkdir(parents=True, exist_ok=True)
        import sqlite3 as _sq
        _c = _sq.connect(str(cfg.mnemosyne_db))
        _c.close()
        log.info("--init-db: created empty DB at %s (Beam initializes schema)", cfg.mnemosyne_db)

    # singleton: try binding the port first — EADDRINUSE -> probe existing core
    ctx = build_context(cfg)
    server = CoreServer(cfg, ctx, token)
    ctx.jev_sem = asyncio.Semaphore(cfg.jev_max_concurrency)

    # writer thread + warmup + recovery BEFORE accepting traffic
    ctx.writer.start(timeout=60)
    await asyncio.to_thread(_warmup_embedding, ctx, cfg)
    # P1 (S4): a failed embedding warmup means the daemon would silently
    # serve the fastembed default (MiniLM) — refuse to start unless
    # JEV_MEM_EMBED_WARMUP=warn explicitly demotes it to a warning.
    if not ctx.embedding.get("warmup_ok") and os.environ.get("JEV_MEM_EMBED_WARMUP", "fail") != "warn":
        if ctx.embedding.get("warmup_error"):
            log.error("embedding warmup failed: %s — refusing to start "
                      "(JEV_MEM_EMBED_WARMUP=warn to demote to warning)",
                      ctx.embedding["warmup_error"])
            ctx.writer.stop()
            sys.exit(9)

    # F8: record/verify DB identity in core_state.db core_meta (writer thread)
    try:
        await ctx.writer.submit(
            lambda w: _verify_db_identity(w, cfg, accept_change), "db_identity")
    except SystemExit:
        ctx.writer.stop()
        raise

    # F14 (2026-09-30, review): durability parity — ledger(core_state.db) is
    # WAL+NORMAL; promote the memory DB to synchronous=FULL so a power loss /
    # BSOD can't leave ledger 'stored' while the memory write rolls back
    # (re-send would hit dedup -> permanent loss). Cost: slower commits.
    try:
        await ctx.writer.submit(
            lambda w: w.beam.conn.execute("PRAGMA synchronous=FULL"),
            "pragma_full")
        log.info("mnemosyne.db synchronous=FULL (F14 durability parity)")
    except Exception as e:
        log.warning("synchronous=FULL set failed: %s", e)

    # B §5.3 (승인): user-only ACL on the data dir + redaction notice
    await _apply_data_dir_acl(cfg)
    if _redact_active():
        log.info("redaction ACTIVE (patterns: %s)", ", ".join(_redact_patterns()))

    # synced-folder warning (B §13)
    ctx.synced_folder_warning = await _check_synced_folder(cfg)
    if ctx.synced_folder_warning:
        log.warning("mnemosyne.db is under a sync folder (OneDrive/Dropbox…) — "
                    "WAL/SHM corruption risk; see /v1/status")

    # spool scanner (B §9.3): startup scan + 10-min interval
    pipeline = server.pipeline
    ctx.scanner = SpoolScanner(
        cfg.data_dir / "spool", pipeline.process_turn,
        asyncio.get_running_loop(),
        interval_s=cfg.spool_replay_interval_s,
        skip_fresh_s=cfg.spool_skip_fresh_s)
    try:
        sr = await asyncio.to_thread(ctx.scanner.scan_once)
        if sr.get("files"):
            log.info("startup spool replay: %s", sr)
    except Exception:
        log.exception("startup spool scan failed")

    # recover pending rows
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

    # P2 background ops loop
    op_task = asyncio.ensure_future(_op_loop(ctx, pipeline))

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
        op_task.cancel()
        try:
            await op_task
        except asyncio.CancelledError:
            pass
        try:
            await server.stop()
        finally:
            ctx.writer.stop()  # on_close: wal_checkpoint(TRUNCATE) + close
            try:
                ctx.readers.close()
            except Exception:
                pass
            try:
                cfg.core_json_path.unlink(missing_ok=True)
            except Exception:
                pass
            log.info("bye")


def _warmup_embedding(ctx: "CoreContext", cfg: Config) -> None:
    """Load the embedding model once (v1.1 D14: process-global).

    Records the outcome on ``ctx.embedding`` so /v1/status can expose the
    ACTUAL model in use. Without this, a failed warmup silently falls back to
    the fastembed default (MiniLM) — the S4 MiniLM-1-row incident — and the
    only detection was a post-hoc DB model-tag check.
    """
    emb = ctx.embedding
    import mnemosyne.core.embeddings as _emb_mod

    try:
        # env-aware dim (MNEMOSYNE_EMBEDDING_DIM or catalog fallback)
        try:
            dim = _emb_mod._get_embedding_dim(_emb_mod._DEFAULT_MODEL)
        except Exception:
            dim = None
        emb["dim"] = dim
        emb["model"] = _emb_mod._DEFAULT_MODEL

        import mnemosyne.core.beam as beam_mod
        if not beam_mod._embeddings.available():
            # disabled (MNEMOSYNE_NO_EMBEDDINGS etc.) or API-mode — not a failure
            emb["warmup_error"] = "disabled or api-mode (MNEMOSYNE_*_EMBEDDINGS_OFF/API)"
            emb["warmup_ok"] = False
            return
        beam_mod._embeddings.embed(["warmup"])
        # success: capture the model the embedding object actually resolved,
        # including the fastembed alias if it loaded through one
        try:
            m = _emb_mod._get_model()
            if m is not None and hasattr(m, "model_name"):
                emb["model"] = m.model_name
        except Exception:
            pass  # status still shows _DEFAULT_MODEL
        emb["warmup_ok"] = True
        emb["warmup_error"] = None
    except Exception as e:
        emb["warmup_ok"] = False
        emb["warmup_error"] = str(e)[:300]
        log.warning("embedding warmup failed: %s", e)


def _apply_api_url_override() -> None:
    """JEV_API_URL env override (test/chaos use). write_gate reads the module
    constant at call time, so patching it here before any gate call works."""
    url = os.environ.get("JEV_API_URL")
    if not url:
        return
    try:
        import gateway.write_gate as wg
        wg.API_URL = url
        log.info("JEV_API_URL override -> %s (write_gate)", url)
    except Exception as e:
        log.warning("JEV_API_URL override failed: %s", e)


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
    p.add_argument("--init-db", action="store_true",
                   help="create the configured mnemosyne.db if missing (F8 guard override)")
    p.add_argument("--accept-db-change", action="store_true",
                   help="accept a changed DB identity (F8 guard override)")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    cfg = Config.load(args.config)

    # core.log daily rotation (B §14) — recent 14 days
    log_dir = cfg.log_dir or (cfg.data_dir / "logs")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        from logging.handlers import TimedRotatingFileHandler
        fh = TimedRotatingFileHandler(log_dir / "core.log", when="midnight",
                                      backupCount=14, encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(fh)
    except Exception as e:
        log.warning("core.log setup failed: %s", e)

    if args.check:
        ok = asyncio.run(_probe_health(cfg))
        print("ready" if ok else "down")
        sys.exit(0 if ok else 1)

    if not args.serve:
        p.print_help()
        sys.exit(0)

    _apply_api_url_override()

    try:
        asyncio.run(_serve(cfg))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()