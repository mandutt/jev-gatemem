"""Turn & prefetch pipelines (B §7.4/§7.5, v1.1).

- process_turn: ledger receive (durable) -> gate (JEV via to_thread, outside
  writer) -> store (writer thread, 4-way) -> ledger finish.
- process_prefetch: stage1 lanes+RRF via ReaderPool; stage2 JEV rerank within
  the remaining budget. Any failure -> degraded RRF-only (never an error).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("jev_mem.pipeline")


class JevUnavailable(Exception):
    pass


class JevTimeout(JevUnavailable):
    pass


class JevError(JevUnavailable):
    pass


class CircuitBreaker:
    """Closed -> open after N consecutive failures; half-open probe (B §8.1)."""

    def __init__(self, failures: int = 5, open_s: float = 30.0):
        self.failures = failures
        self.open_s = open_s
        self.state = "closed"  # closed | open | half-open
        self.consecutive = 0
        self.last_failure_at = 0.0
        self.last_ok_at = 0.0

    def allow(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            if time.monotonic() - self.last_failure_at >= self.open_s:
                self.state = "half-open"
                return True  # single probe
            return False
        return False  # half-open already probing — wait for verdict

    def on_success(self) -> None:
        self.state = "closed"
        self.consecutive = 0
        self.last_ok_at = time.monotonic()

    def on_failure(self, exc: Optional[BaseException] = None) -> None:
        self.consecutive += 1
        self.last_failure_at = time.monotonic()
        if self.state == "half-open" or self.consecutive >= self.failures:
            self.state = "open"

    @property
    def is_open(self) -> bool:
        return self.state != "closed"


class Pipeline:
    def __init__(self, ctx: Any):
        self.ctx = ctx

    # ------------------------------------------------------------------
    async def process_turn(self, req: Dict, *, recovery: bool = False) -> Dict:
        """Full turn pipeline. Returns result dict for /v1/turns."""
        from . import ledger

        agent = req.get("agent", "")
        session_id = req.get("session_id", "")
        session_key = f"{agent}_{session_id}" if not session_id.startswith(f"{agent}_") else session_id
        idem_key = req.get("idempotency_key")
        user = req.get("user_content") or ""
        asst = req.get("assistant_content") or ""
        if not idem_key:
            if req.get("turn_seq") is not None:
                idem_key = f"{agent}:{session_id}:{req['turn_seq']}"
            else:
                idem_key = f"{agent}:{session_id}:{__import__('uuid').uuid4().hex[:12]}"
        ph = ledger.payload_hash(agent, session_id, req.get("turn_seq"), user, asst)

        # 1) durable receive (writer queue)
        try:
            rec = await self.ctx.writer.submit(
                lambda w: ledger.ledger_receive(w.state, idem_key=idem_key, payload=req, payload_hash_=ph),
                "ledger_receive",
            )
        except Exception as e:
            return {"ok": False, "error": {"code": "LEDGER_FAIL", "message": str(e), "retryable": True}}

        if rec["status"] == "conflict":
            return {"ok": False, "error": {"code": "IDEMPOTENCY_CONFLICT",
                                           "message": "same key, different payload", "retryable": False}}
        if rec["status"] == "duplicate":
            # completed already?
            row = rec.get("row") or {}
            status = row.get("status")
            self.ctx.stats["dedup_count"] += 1
            return {"ok": True, "status": "stored" if status == "stored" else status,
                    "turn_id": rec["turn_id"], "deduplicated": True}

        turn_id = rec["turn_id"]

        # 2) gate (async, outside writer)
        # session lock: same session serialized, others parallel
        async with self.ctx.session_lock(session_key):
            try:
                async with self.ctx.jev_sem:
                    if not self.ctx.breaker.allow():
                        raise JevUnavailable("circuit open")
                    decisions = await asyncio.to_thread(
                        self._evaluate_turn, user, asst)
                    self.ctx.breaker.on_success()
                    self.ctx.stats["jev_calls"] += 1
            except (JevUnavailable, JevTimeout, JevError) as e:
                self.ctx.breaker.on_failure(e)
                self.ctx.stats["jev_failures"] += 1
                return await self._gate_failure(req, rec, session_key, idem_key, turn_id, e)
            except Exception as e:
                # unexpected — treat as gate failure -> pending_gate (data preserved)
                log.exception("gate unexpected failure")
                self.ctx.breaker.on_failure(e)
                self.ctx.stats["jev_failures"] += 1
                return await self._gate_failure(req, rec, session_key, idem_key, turn_id, e)

            # 3) store (writer thread)
            try:
                mem_ids = await self.ctx.writer.submit(
                    lambda w: self._store(w, req, decisions, session_key, idem_key, turn_id),
                    "store_turn",
                )
            except Exception as e:
                # writer failure — keep row pending, data still in ledger
                await self.ctx.writer.submit(
                    lambda w: self._ledger(w, idem_key, "pending_gate",
                                           last_error=f"store_fail:{type(e).__name__}"),
                    "ledger_store_fail",
                )
                return {"ok": False, "error": {"code": "STORE_FAIL", "message": str(e), "retryable": True}}

            # 4) finish
            await self.ctx.writer.submit(
                lambda w: self._finish(w, idem_key, decisions, mem_ids), "ledger_finish")
            status = "stored" if mem_ids else "skipped"
            self.ctx.stats["turns"][status] = self.ctx.stats["turns"].get(status, 0) + 1
            return {"ok": True, "status": status, "turn_id": turn_id,
                    "decisions": decisions, "memory_ids": mem_ids}

    # -- internals ------------------------------------------------------
    def _evaluate_turn(self, user: str, asst: str) -> Dict[str, Dict]:
        """Runs BOTH gates synchronously (JEV calls). to_thread-wrapped.

        JEV network/5xx failures are ALSO surfaced as JevUnavailable so the
        pipeline can move the turn to pending_gate (B §8.2 'spool' default).
        Fail-open KEEP verdicts with a non-transient cause (401/empty/kill
        switch/parse) are returned as-is.
        """
        wg = _load_write_gate()
        decisions: Dict[str, Dict] = {}
        user_skip = False
        asst_skip = False
        transient = ("http-5", "error")
        if (user or "").strip() and len(user) > 5:
            r = wg.evaluate(user) if wg else {"keep": True, "reason": "no-wg"}
            reason = str(r.get("reason") or "")
            if reason.startswith(transient) or reason in ("error",):
                raise JevUnavailable(f"gate user failed: {reason}")
            decisions["user"] = r
            user_skip = not r.get("keep")
        else:
            decisions["user"] = {"keep": True, "reason": "empty"}
        if (asst or "").strip() and len(asst) > 10:
            r = wg.evaluate_assistant(asst) if wg else {"keep": True, "reason": "no-wg"}
            reason = str(r.get("reason") or "")
            if reason.startswith(transient) or reason in ("error",):
                raise JevUnavailable(f"gate assistant failed: {reason}")
            decisions["assistant"] = r
            asst_skip = not r.get("keep")
        else:
            decisions["assistant"] = {"keep": True, "reason": "empty"}
        return decisions

    def _store(self, w, req, decisions, session_key, idem_key, turn_id):
        from . import store
        return store.store_kept(w, req=req, decisions=decisions,
                                session_key=session_key, idem_key=idem_key, turn_id=turn_id)

    def _finish(self, w, idem_key, decisions, mem_ids):
        from . import ledger
        status = "stored" if mem_ids else "skipped"
        ledger.ledger_mark(w.state, idem_key, status, decisions=decisions,
                           memory_ids=mem_ids, clear_payload=True)

    def _ledger(self, w, idem_key, status, *, last_error=None):
        from . import ledger
        ledger.ledger_mark(w.state, idem_key, status, last_error=last_error)

    async def _gate_failure(self, req, rec, session_key, idem_key, turn_id, exc):
        """JEV unavailable -> pending_gate (B §8.2 default 'spool')."""
        # mark pending_gate, keep payload for later re-judgement
        try:
            await self.ctx.writer.submit(
                lambda w: self._ledger(w, idem_key, "pending_gate",
                                       last_error=f"gate:{type(exc).__name__}"),
                "ledger_pending_gate",
            )
            self.ctx.stats["turns"]["pending_gate"] = \
                self.ctx.stats["turns"].get("pending_gate", 0) + 1
        except Exception:
            pass
        return {"ok": True, "status": "pending_gate", "turn_id": turn_id,
                "decisions": {}, "error": str(exc)[:120]}

    # ------------------------------------------------------------------
    async def requeue_pending_gate(self, max_age_h: float = 24.0,
                                   batch: int = 20) -> Dict:
        """Re-judge pending_gate rows (B §8.2): oldest first, max N.

        Called every `pending_gate_retry_interval_s` while the circuit is
        closed. Rows older than `max_age_h` -> failed(reason=expired) and
        their payload is dropped.
        """
        from . import ledger

        def _peek(w):
            return ledger.pending_gate_rows(w.state, limit=batch)

        rows = await self.ctx.writer.submit(_peek, "pending_peek")
        if not rows:
            return {"rejudged": 0, "expired": 0, "left": 0}
        rejudged = 0
        expired = 0
        now = time.time()
        for r in rows:
            created = r.get("created_at") or 0
            age_h = (now - created) / 3600 if created else 0
            if age_h >= max_age_h:
                try:
                    await self.ctx.writer.submit(
                        lambda w, k=r["idem_key"]: ledger.ledger_mark(
                            w.state, k, "failed", last_error="expired",
                            clear_payload=True),
                        "pending_expire")
                    expired += 1
                except Exception:
                    pass
                continue
            payload = r.get("payload")
            if not payload:
                # payload lost — nothing to re-judge; mark failed
                try:
                    await self.ctx.writer.submit(
                        lambda w, k=r["idem_key"]: ledger.ledger_mark(
                            w.state, k, "failed", last_error="payload_lost",
                            clear_payload=True),
                        "pending_fail")
                    expired += 1
                except Exception:
                    pass
                continue
            # re-judge: run the gate+store part only (ledger row already exists)
            try:
                res = await self._rejudge_one(payload, r["idem_key"])
                if res:
                    rejudged += 1
            except Exception:
                log.exception("rejudge failed for %s", r["idem_key"])
        return {"rejudged": rejudged, "expired": expired,
                "left": await self._pending_count()}

    async def _pending_count(self) -> int:
        from . import ledger
        try:
            return await self.ctx.writer.submit(
                lambda w: ledger.pending_gate_count(w.state), "pending_count")
        except Exception:
            return -1

    async def _rejudge_one(self, payload: Dict, idem_key: str) -> bool:
        """Gate + store for an already-received row. Returns True on success."""
        user = payload.get("user_content") or ""
        asst = payload.get("assistant_content") or ""
        agent = payload.get("agent") or ""
        session_id = payload.get("session_id") or ""
        session_key = payload.get("session_key") or \
            f"{agent}_{session_id}" if session_id else ""
        try:
            async with self.ctx.jev_sem:
                if not self.ctx.breaker.allow():
                    return False  # circuit open again — leave for next round
                decisions = await asyncio.to_thread(self._evaluate_turn, user, asst)
                self.ctx.breaker.on_success()
        except (JevUnavailable, JevTimeout, JevError) as e:
            self.ctx.breaker.on_failure(e)
            return False
        except Exception as e:
            self.ctx.breaker.on_failure(e)
            return False
        try:
            mem_ids = await self.ctx.writer.submit(
                lambda w: self._store(w, payload, decisions, session_key,
                                      idem_key, ""),
                "store_rejudged")
            await self.ctx.writer.submit(
                lambda w, k=idem_key: self._finish(w, k, decisions, mem_ids),
                "ledger_finish_rejudged")
            return True
        except Exception as e:
            log.warning("rejudge store failed: %s", e)
            return False

    # ------------------------------------------------------------------
    async def process_prefetch(self, req: Dict) -> Dict:
        """Two-stage prefetch with budget (B §7.5). Returns dict for response."""
        options = req.get("options") or {}
        max_chars = int(options.get("max_chars", 6000))
        timeout_ms = int(options.get("timeout_ms") or self.ctx.cfg.prefetch_default_timeout_ms)
        timeout_ms = max(200, min(timeout_ms, self.ctx.cfg.prefetch_max_timeout_ms))  # D7a clamp
        rerank = bool(options.get("rerank", True))
        query = (req.get("query") or "").strip()
        if not query:
            return {"context": "", "meta": {"degraded": True, "degraded_reason": "empty_query",
                                            "rerank": "skipped", "latency_ms": 0}}

        deadline = time.monotonic() + timeout_ms / 1000
        t0 = time.perf_counter()
        lanes = {}
        stage1_rows = []

        # stage 1: lanes -> RRF -> filter (ReaderPool, no JEV)
        try:
            result = await self.ctx.readers.run(
                lambda beam: self._retrieve(beam, query))
            stage1_rows = result or []
            lanes = getattr(self.ctx, "_last_lanes", {})
        except Exception as e:
            log.warning("prefetch stage1 failed: %s", e)
            return {"context": "", "meta": {"degraded": True, "degraded_reason": "stage1_failed",
                                            "rerank": "skipped",
                                            "latency_ms": round((time.perf_counter() - t0) * 1000)}}

        if not stage1_rows:
            return {"context": "", "meta": {"degraded": False, "degraded_reason": None,
                                            "rerank": "skipped", "lanes": lanes,
                                            "latency_ms": round((time.perf_counter() - t0) * 1000)}}

        # stage 2: JEV rerank if budget allows
        remaining = deadline - time.monotonic()
        ctx = ""
        degraded = False
        reason = None
        rerank_used = "skipped"
        if rerank and remaining > 0.3 and self.ctx.breaker.allow():
            try:
                async with self.ctx.jev_sem:
                    ranked = await asyncio.wait_for(
                        asyncio.to_thread(self._rerank, query, stage1_rows),
                        timeout=remaining)
                self.ctx.breaker.on_success()
                ctx = self._render(ranked, query, max_chars)
                rerank_used = "jev"
            except (asyncio.TimeoutError, JevUnavailable, JevError) as e:
                self.ctx.breaker.on_failure(e)
                self.ctx.stats["jev_failures"] += 1
                ctx = self._render(stage1_rows, query, max_chars)
                degraded = True
                reason = "jev_timeout" if isinstance(e, asyncio.TimeoutError) else "jev_unavailable"
                rerank_used = "failed"
        else:
            ctx = self._render(stage1_rows, query, max_chars)
            degraded = remaining <= 0.3
            reason = "budget_exceeded" if degraded else None
            rerank_used = "skipped" if (not rerank) else ("budget_exceeded" if degraded else "skip")

        self.ctx.stats["prefetch_total"] += 1
        if degraded:
            self.ctx.stats["prefetch_degraded"] += 1
        return {"context": ctx,
                "meta": {"degraded": degraded, "degraded_reason": reason,
                         "rerank": rerank_used, "lanes": lanes,
                         "latency_ms": round((time.perf_counter() - t0) * 1000)}}

    def _retrieve(self, beam, query: str) -> List[Dict]:
        """Stage 1: lanes -> RRF -> conservative filter (no JEV)."""
        from gateway import j1_pipeline as j1p
        from core import j1_engine
        import mnemosyne.core.beam as beam_mod

        def recall_raw(kind: str, arg, k: int):
            if kind == "fts":
                return beam_mod._fts_search_working(beam.conn, arg, k=k)
            if kind == "vec":
                emb = beam_mod._embeddings.embed([arg])
                if emb is None or not len(emb):
                    return []
                return beam_mod._wm_vec_search(beam.conn, emb[0], k=k)
            if kind == "imp":
                return j1p._imp_search(beam.conn, k=k)
            if kind == "graph":
                return j1p._graph_lane_search(beam.conn, arg, k=k)
            if kind == "get":
                row = j1_engine.hydration_get(beam, arg)
                return row if isinstance(row, dict) else None
            return []

        pool = j1p.build_lane_pool(recall_raw, query)
        return j1p._filter_and_rank(pool, query) if pool else []

    def _rerank(self, query: str, rows: List[Dict]) -> List[Dict]:
        from gateway import j1_pipeline as j1p
        return j1p.jev_rerank(query=query, pool=rows,
                              client=_jev_client(), call_jev=True,
                              timeout=5.0)

    def _render(self, rows: List[Dict], query: str, max_chars: int) -> str:
        from core import j1_engine
        # B §5.3: top-k 유지 (embedded j1_engine.run과 동일 — JEV 없으면
        # jev_rerank가 pool 전체를 반환하므로 top_k=5로 잘라야 golden 일치)
        rows = rows[:5] if rows else rows
        block = j1_engine.format_block(rows, query)
        if max_chars > 0 and len(block) > max_chars:
            block = block[:max_chars]
        return block


_jev_client_cache = None


def _jev_client():
    """Lazy shared httpx client for JEV calls (write_gate compatible)."""
    global _jev_client_cache
    if _jev_client_cache is None:
        from core import j1_engine
        _jev_client_cache = j1_engine.typesafe_client()
    return _jev_client_cache


def _load_write_gate():
    """Shadowing-safe write_gate load (j1_access pattern)."""
    try:
        from harnesses import wg_access
        return wg_access.write_gate()
    except Exception:
        try:
            from gateway import write_gate
            return write_gate
        except Exception:
            return None