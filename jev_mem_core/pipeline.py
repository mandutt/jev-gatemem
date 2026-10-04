"""Turn & prefetch pipelines (B §7.4/§7.5, v1.1).

- process_turn: ledger receive (durable) -> gate (JEV via to_thread, outside
  writer) -> store (writer thread, 4-way) -> ledger finish.
- process_prefetch: stage1 lanes+RRF via ReaderPool; stage2 JEV rerank within
  the remaining budget. Any failure -> degraded RRF-only (never an error).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("jev_mem.pipeline")


def _redaction():
    from .redact import active
    return active()


def _redact_payload(payload: Dict) -> Dict:
    from .redact import redact_payload
    return redact_payload(payload)


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

        # B §5.3 (승인 2): ledger payload에만 redaction (스풀은 client가 수행)
        # mnemosyne DB 저장분은 치환 안 함.
        if _redaction():
            req_for_ledger = _redact_payload(req)
        else:
            req_for_ledger = req

        # 1) durable receive (writer queue)
        try:
            rec = await self.ctx.writer.submit(
                lambda w: ledger.ledger_receive(w.state, idem_key=idem_key,
                                                payload=req_for_ledger,
                                                payload_hash_=ph),
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
            fo = any((decisions.get(r) or {}).get("fail_open") for r in ("user", "assistant"))
            status = "fail_open_quarantine" if fo else ("stored" if mem_ids else "skipped")
            if not fo:
                # P3 (D7): 실사용 호출 성공 → open incident recovery streak.
                # 턴 단위 1회 — 같은 턴의 user/assistant 2회 호출이 streak을
                # 부풀리지 않는다 (b-ai "3회 ≈ 1.5턴" 지적 해소: 서로 다른 턴 기준).
                # to_thread: 내부 submit_sync().result()가 루프 스레드에서
                # 실행되면 루프가 짧게 블록되므로 워커 스레드로 분리한다.
                await asyncio.to_thread(self._note_recovery)
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
        # P2a (v2 검토): allowlist 폐기 → 불변식 반전.
        #   정상 판정 = JEV 200 응답을 받고 규칙에 따라 KEEP/SKIP 결정 (reason이
        #   store/type-rescue/low-conf/skip ... 등 규칙 기반).
        #   그 외 (http-*, no-key, kill, parse, no-wg, empty) = fail-open.
        #   reason이 transient(http-5xx, error)면 JevUnavailable(pending_gate)로.
        #   C-AI invariant: availability==UNAVAILABLE && decision==KEEP → QUARANTINE
        NORMAL_REASONS = ("store", "type-rescue", "low-conf", "skip", "context",
                          "no-store", "commitment-fp-v4", "parse-fail")

        def _infer_failure_class(reason: str) -> str:
            """reason 문자열만 있을 때 failure_class 폴백 추론 (P2a).

            - http-402 -> billing, http-401/403 -> auth, http-429/5xx -> transient
            - no-key/kill -> config, 그 외 -> unknown
            """
            if reason.startswith("http-402"):
                return "billing"
            if reason.startswith("http-401") or reason.startswith("http-403"):
                return "auth"
            if reason.startswith("http-429") or reason.startswith("http-5"):
                return "transient"
            if reason in ("no-key", "kill", "killswitch-off"):
                return "config"
            return "unknown"

        if (user or "").strip() and len(user) > 5:
            r = wg.evaluate(user) if wg else {"keep": True, "reason": "no-wg"}
            reason = str(r.get("reason") or "")
            if reason.startswith(transient) or reason in ("error",):
                raise JevUnavailable(f"gate user failed: {reason}")
            # F11 (P2a 강화): 정상 판정이 아닌 모든 KEEP → fail_open 마커.
            #   reason이 규칙 기반 정상 목록이 아니면 fail-open (allowlist 반전)
            is_normal = reason in NORMAL_REASONS
            if r.get("keep") and not is_normal:
                r["fail_open"] = reason
                r["availability"] = "unavailable"
                r["preservation"] = "quarantine"
                # P2b: 장애 구간 기록 + incident_id 부여 (재판정 batch 단위)
                fcls = r.get("failure_class") or _infer_failure_class(reason)
                r["incident_id"] = self._incident_id(fcls, reason)
                self.ctx.stats["gate_fail_open_total"] = (
                    self.ctx.stats.get("gate_fail_open_total", 0) + 1)
                # P2a: failure_class 별 집계 (경보용) — billing/auth는 사람 개입 필요
                fc = r.get("failure_class") or _infer_failure_class(reason)
                key = f"gate_fail_{fc}"
                self.ctx.stats[key] = self.ctx.stats.get(key, 0) + 1
                self.ctx.fail_open_streak += 1
            else:
                self.ctx.fail_open_streak = 0
            decisions["user"] = r
            user_skip = not r.get("keep")
        else:
            decisions["user"] = {"keep": True, "reason": "empty"}
        if (asst or "").strip() and len(asst) > 10:
            r = wg.evaluate_assistant(asst) if wg else {"keep": True, "reason": "no-wg"}
            reason = str(r.get("reason") or "")
            if reason.startswith(transient) or reason in ("error",):
                raise JevUnavailable(f"gate assistant failed: {reason}")
            if r.get("keep") and reason not in NORMAL_REASONS:
                r["fail_open"] = reason
                r["availability"] = "unavailable"
                r["preservation"] = "quarantine"
                fcls = r.get("failure_class") or _infer_failure_class(reason)
                r["incident_id"] = self._incident_id(fcls, reason)
                self.ctx.stats["gate_fail_open_total"] = (
                    self.ctx.stats.get("gate_fail_open_total", 0) + 1)
                fc = r.get("failure_class") or _infer_failure_class(reason)
                key = f"gate_fail_{fc}"
                self.ctx.stats[key] = self.ctx.stats.get(key, 0) + 1
                self.ctx.fail_open_streak += 1
            else:
                self.ctx.fail_open_streak = 0
            decisions["assistant"] = r
            asst_skip = not r.get("keep")
        else:
            decisions["assistant"] = {"keep": True, "reason": "empty"}
        return decisions

    def _incident_id(self, failure_class: str, reason: str) -> str:
        """Get-or-create incident_id for the current outage (P2b, D7).

        Writer thread가 아니므로 atomic하게 ledger에 기록할 수 없다.
        ctx 레벨 캐시로 같은 class+reason 구간을 재사용하고, writer에서
        ledger.outage_open으로 확정한다 (process_turn의 _finish 직전).
        """
        cache = getattr(self.ctx, "_incident_cache", None)
        if cache is None:
            cache = self.ctx._incident_cache = {}
        key = f"{failure_class}|{reason}"
        if key not in cache:
            import uuid as _uuid
            cache[key] = f"inc-{_uuid.uuid4().hex[:12]}"
        return cache[key]

    def _store(self, w, req, decisions, session_key, idem_key, turn_id):
        from . import store
        return store.store_kept(w, req=req, decisions=decisions,
                                session_key=session_key, idem_key=idem_key, turn_id=turn_id)

    def _finish(self, w, idem_key, decisions, mem_ids):
        from . import ledger
        fo = None
        fcls = None
        incident_id = None
        for role in ("user", "assistant"):
            d = (decisions.get(role) or {})
            if d.get("fail_open"):
                fo = d["fail_open"]
                fcls = d.get("failure_class")
                incident_id = d.get("incident_id")
                break
        if fo:
            # P2b (v2 D1): fail-open KEEP -> quarantine 상태 기록 (재판정 대상)
            status = "fail_open_quarantine"
            # P2b (D7): gate_outage 테이블에 장애 구간 확정 기록
            try:
                if incident_id:
                    ledger.outage_open(w.state, reason=fo,
                                       failure_class=fcls or "unknown",
                                       incident_id=incident_id)
                    self.ctx.stats["outages_open"] = \
                        len(ledger.outage_open_incidents(w.state))
                    self.ctx.stats["outage_incidents"] = [
                        i["incident_id"] for i in
                        ledger.outage_open_incidents(w.state)]
            except Exception:
                pass  # ledger 기록 실패는 저장과 무관
        else:
            status = "stored" if mem_ids else "skipped"
            # 4차: SKIP 발화 shadow archive (audit-only, recall 무영향).
            # fail_open_quarantine은 KEEP(재판정 대상)이라 여기서 제외.
            self._shadow_skips(w, idem_key, decisions, status)
        ledger.ledger_mark(w.state, idem_key, status, decisions=decisions,
                           memory_ids=mem_ids, clear_payload=True)

    def _ledger(self, w, idem_key, status, *, last_error=None):
        from . import ledger
        ledger.ledger_mark(w.state, idem_key, status, last_error=last_error)


    def _shadow_skips(self, w, idem_key: str, decisions: Dict, status: str) -> None:
        """4차: SKIP 발화를 skip_shadow 테이블에 기록 (audit-only).

        - redaction (redact_text_high_precision) 후 1,500자 cap — B 4차 지적 반영
          (1KB 바이트 cap은 한글 3바이트로 ~340자 — 감사 원문 왜곡).
        - failure/quarantine KEEP은 여기 안 옴 (위 호출부에서 분기).
        - 실패 시에도 절대 예외 전파하지 않음 (본 파이프라인 무영향).
        """
        if os.environ.get("JEV_MEM_SHADOW") == "0":
            return
        try:
            from . import ledger
            from .redact import redact_text_high_precision
            row = w.state.conn.execute(
                "SELECT agent, session_key, payload_json, received_at, turn_id"
                " FROM ingest_ledger WHERE idem_key=?", (idem_key,)
            ).fetchone()
            if not row:
                return
            agent, session_key, payload_json, received_at, turn_id = row
            payload = {}
            if payload_json:
                try:
                    payload = json.loads(payload_json)
                except Exception:
                    payload = {}
            user = payload.get("user_content") or ""
            asst = payload.get("assistant_content") or ""
            for spk, text in (("user", user), ("assistant", asst)):
                d = decisions.get(spk) or {}
                if d.get("keep") is False and (text or "").strip():
                    safe = redact_text_high_precision(text)[:1500]
                    ledger.shadow_add(
                        w.state.conn, idem_key=idem_key, turn_id=turn_id or "",
                        agent=agent or "", session_key=session_key or "",
                        speaker=spk, content=safe,
                        reason=str(d.get("reason") or "skip"),
                        store_conf=d.get("store_conf"),
                        type_conf=d.get("type_conf"),
                        type_label=d.get("type"),
                        received_at=received_at or "",
                    )
        except Exception:
            log.exception("skip_shadow capture failed (non-fatal)")

    def _note_recovery(self) -> None:
        """P3 (D7): 실사용 호출 성공 1회 → open incident recovery streak 기록.

        같은 턴 안의 2회 게이트 호출이 streak을 부풀리지 않도록 턴당 1회만.
        open incident가 없으면 no-op. 회복 판정은 DB 영속 (재시작 안전).
        """
        try:
            from .recover import RejudgeEngine
            from . import ledger
            if not getattr(self.ctx, "writer", None):
                return
            opens = self.ctx.writer.submit_sync(
                lambda w: ledger.outage_open_incidents(w.state),
                "outage_peek").result()
            if not opens:
                return
            engine = RejudgeEngine(self.ctx, cfg=self.ctx.cfg)
            for inc in opens:
                try:
                    engine.record_recovery_success(inc["incident_id"])
                except Exception:
                    log.exception("recovery streak failed for %s",
                                  inc["incident_id"])
        except Exception:
            log.exception("_note_recovery failed")

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
        include_pool_ids = bool(options.get("pool_ids", False))
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
        final_rows = stage1_rows
        if rerank and remaining > 0.3 and self.ctx.breaker.allow():
            try:
                async with self.ctx.jev_sem:
                    ranked = await asyncio.wait_for(
                        asyncio.to_thread(self._rerank, query, stage1_rows),
                        timeout=remaining)
                self.ctx.breaker.on_success()
                final_rows = ranked
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
        meta = {"degraded": degraded, "degraded_reason": reason,
                "rerank": rerank_used, "lanes": lanes,
                "latency_ms": round((time.perf_counter() - t0) * 1000)}
        # 4차: 쿼리 영속 로깅 (감사용, recall 무영향, writer 경유)
        _abstained = bool(stage1_rows) and not final_rows and rerank_used == "jev"
        try:
            await self.ctx.writer.submit(
                lambda w: _log_query(
                    w, query=query, agent=req.get("agent") or "",
                    session_id=req.get("session_id") or "",
                    pool_n=len(stage1_rows) if stage1_rows else 0,
                    abstained=_abstained,
                    latency_ms=round((time.perf_counter() - t0) * 1000)),
                "query_log",
            )
        except Exception:
            log.exception("query_log capture failed (non-fatal)")
        if include_pool_ids:
            # Measurement aid: stage1 pool ids (RRF order) + post-rerank ids
            # (JEV lift observation). Opt-in via options.pool_ids.
            meta["pool_ids"] = [str(r.get("id") or "") for r in stage1_rows]
            meta["final_ids"] = [str(r.get("id") or "") for r in final_rows[:40]]
        return {"context": ctx, "meta": meta}

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
        ranked, abstained = j1p.jev_rerank(query=query, pool=rows,
                                            client=_jev_client(), call_jev=True,
                                            timeout=5.0)
        if abstained:
            # Run O: Jev says no candidate is usable evidence. Return empty
            # so the prefetch renders an empty context block ("no memory").
            return []
        return ranked

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


def _log_query(w, *, query: str, agent: str, session_id: str,
               pool_n=None, abstained=None, latency_ms=None) -> None:
    """4차: prefetch 쿼리를 query_log에 기록 (writer 스레드 안에서 호출).

    recall 경로와 분리된 audit-only 로깅 — 실패해도 파이프라인 무영향.
    """
    try:
        from . import ledger
        from .redact import redact_text_high_precision
        safe = redact_text_high_precision(query)[:1500]
        ledger.query_log_add(
            w.state, query=safe, agent=agent, session_id=session_id,
            pool_n=pool_n, abstained=abstained, latency_ms=latency_ms)
    except Exception:
        log.exception("query_log capture failed (non-fatal)")


def _jev_client():
    """Lazy shared httpx client for JEV calls.

    - 실측 테스트/개발 시 EXPLABS_API_KEY 우선 (experientiallabs 게이트웨이),
      없으면 기존 TYPESAFE_API_KEY 폴백 (운영 데몬 호환 유지).
    - JEV_API_URL도 동일 우선순위로 해석: EXPLABS_API_KEY 존재 시
      https://api.experientiallabs.ai/v1/systemone 기본값 사용.
    - 키 스위칭 (2026-10-04): SmartRotator 기반 — EXPLABS_API_KEY /
      EXPLABS_API_KEY2 (별개 계정) 순환. 429 발생 시 다음 키로 전환,
      무료 소진(cost>0) 시 해당 키 제외. TYPESAFE는 최후 폴백.
    """
    global _jev_client_cache
    if _jev_client_cache is None:
        import httpx
        try:
            from .keyring import SmartRotator
        except Exception:
            SmartRotator = None
        if SmartRotator is not None:
            rot = SmartRotator()
            keys = rot.keys
        else:
            explabs_key = os.environ.get("EXPLABS_API_KEY") or ""
            typesafe_key = os.environ.get("TYPESAFE_API_KEY") or ""
            keys = [k for k in (explabs_key, typesafe_key) if k]
        if not keys:
            return None
        explabs_key = os.environ.get("EXPLABS_API_KEY") or ""
        typesafe_key = os.environ.get("TYPESAFE_API_KEY") or ""
        if explabs_key:
            api = os.environ.get("JEV_API_URL") or \
                "https://api.experientiallabs.ai/v1/systemone"
        else:
            api = os.environ.get("JEV_API_URL") or \
                "https://api.typesafe.ai/v1/systemone"
        try:
            _jev_client_cache = httpx.Client(
                timeout=httpx.Timeout(5.0, connect=5.0),
                headers={
                    "Authorization": f"Bearer {keys[0]}",
                    "Content-Type": "application/json",
                },
            )
            _jev_client_cache._jev_api = api  # j1_pipeline이 env에 의존하므로 실제 URL은 env 기준
            _jev_client_cache._jev_rotator = rot if SmartRotator is not None else None
            _jev_client_cache._jev_keys = keys
        except Exception:
            return None
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