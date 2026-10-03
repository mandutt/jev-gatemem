"""SingleWriter — DB write-dedicated thread + queue (B §7.2, v1.1 D14).

- The ONLY writer connection owner (BeamMemory instance + core_state conn).
- Jobs = short DB transactions only. No JEV calls, no embedding math
  outside remember() (which does embed+INSERT as one unit — v1.1 D14).
- QueueFull -> HTTP 503 QUEUE_FULL; WriterStopped -> 503 SHUTTING_DOWN.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

log = logging.getLogger("jev_mem.writer")


class QueueFull(Exception):
    pass


class WriterStopped(Exception):
    pass


@dataclass
class WriterContext:
    """Resources owned by the writer thread. Never touched elsewhere."""
    beam: Any
    state: Any  # sqlite3.Connection (core_state.db)


@dataclass
class _Job:
    fn: Callable[[WriterContext], Any]
    fut: Future
    label: str
    enqueued_at: float


_STOP = object()


class SingleWriter:
    def __init__(self, context_factory: Callable[[], WriterContext],
                 max_depth: int = 500, slow_job_warn_ms: int = 500,
                 on_close: Optional[Callable[[WriterContext], None]] = None):
        self._factory = context_factory
        self._on_close = on_close
        self._q: "queue.Queue[Any]" = queue.Queue(maxsize=max_depth)
        self._slow_ms = slow_job_warn_ms
        self._accepting = True
        self._ready = threading.Event()
        self._init_error: Optional[BaseException] = None
        self._thread = threading.Thread(target=self._run, name="db-writer", daemon=True)

    # ---- lifecycle ---------------------------------------------------
    def start(self, timeout: float = 60.0) -> None:
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("writer init timeout")
        if self._init_error:
            raise self._init_error

    def stop(self, timeout: float = 10.0) -> None:
        self._accepting = False
        try:
            self._q.put_nowait(_STOP)
        except queue.Full:
            pass  # drain below will surface it
        self._thread.join(timeout)
        if self._thread.is_alive():
            log.error("writer did not stop within %.1fs", timeout)

    # ---- API (event loop side) ----------------------------------------
    @property
    def depth(self) -> int:
        return self._q.qsize()

    def submit(self, fn: Callable[[WriterContext], Any], label: str = "job"):
        """이벤트 루프 스레드면 wrap_future(await 가능), 아니면 raw Future."""
        fut = self.submit_sync(fn, label)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return fut
        return asyncio.wrap_future(fut)

    def submit_sync(self, fn: Callable[[WriterContext], Any],
                    label: str = "job") -> Future:
        """동기 대기(.result()) 전용 — 컨텍스트 무관 raw concurrent Future.

        이벤트 루프 스레드에서 .result()로 대기하면 그동안 루프가 블록되므로
        (짧은 DB 작업 한정 — JEV 등 네트워크 작업 금지) 루프 경로는
        asyncio.to_thread 워커 안에서 호출하라. P3a 라이브 실측(2026-10-03):
        submit()이 루프 스레드에서 wrap_future를 반환하는데 recover.py가
        즉시 .result()를 불러 InvalidStateError — 회복 감지/streak 기록이
        매 tick 실패했다 (core.log 'recovery_ready_incidents failed').
        """
        if not self._accepting:
            raise WriterStopped()
        fut: "Future[Any]" = Future()
        try:
            self._q.put_nowait(_Job(fn, fut, label, time.monotonic()))
        except queue.Full:
            raise QueueFull() from None
        return fut

    # ---- writer thread ------------------------------------------------
    def _run(self) -> None:
        ctx: Optional[WriterContext] = None
        try:
            ctx = self._factory()
        except BaseException as e:  # noqa: BLE001
            self._init_error = e
            self._ready.set()
            return
        self._ready.set()
        try:
            while True:
                job = self._q.get()
                if job is _STOP:
                    break
                if not job.fut.set_running_or_notify_cancel():
                    continue  # caller cancelled
                t0 = time.monotonic()
                try:
                    job.fut.set_result(job.fn(ctx))
                except BaseException as e:  # noqa: BLE001
                    job.fut.set_exception(e)
                dur_ms = (time.monotonic() - t0) * 1000
                if dur_ms > self._slow_ms:
                    log.warning("slow writer job %s: %.0fms (queued %.0fms)",
                                job.label, dur_ms, (t0 - job.enqueued_at) * 1000)
        finally:
            try:
                if self._on_close:
                    self._on_close(ctx)
            except Exception:  # noqa: BLE001
                log.exception("writer close failed")


class ReaderPool:
    """Read-only connection pool (B §7.3, v1.1 D13).

    Thread-local RO sqlite connection; j1_engine.run() verified on an RO
    connection with sqlite-vec loaded. Embedding model is process-global
    (loaded once at core start), shared across reader threads.
    """

    def __init__(self, reader_factory: Callable[[], Any], workers: int = 2):
        self._factory = reader_factory
        self._local = threading.local()
        self._ex = ThreadPoolExecutor(max_workers=workers,
                                      thread_name_prefix="db-reader",
                                      initializer=self._init_thread)

    def _init_thread(self) -> None:
        self._local.beam = self._factory()

    async def run(self, fn: Callable[[Any], Any]) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._ex, lambda: fn(self._local.beam))

    def close(self) -> None:
        try:
            self._ex.shutdown(wait=True)
        except Exception:
            pass