"""P3 자동 재판정 worker — fail-open quarantine → rejudge (D1-D8).

설계: docs/review/2026-10-03_failopen_P3_설계안.md (3 AI 검토 종합)
- 실행 주체: core 내부 worker (프로세스 분리 없음) — D1
- SQLite ledger/incident = 유일한 source of truth (restart-safe) — D3
- 회복 판정(recovery state)과 재판정 실행(worker) 분리 — D4
- 하이브리드 트리거: 내부 루프 / CLI / admin 엔드포인트 — 같은 엔진 함수 — D5
- 동시성 예산: foreground HIGH / rejudge LOW — D6
- 회복 상태 DB 영속 (recovery_success_count 등) — D7
- 재장애 시 즉시 중단 (billing/auth 1회, transient N회) — D8

엔진 함수는 순수 (ctx 주입) — CLI(tools/)와 core 루프가 같은 코드 경로를 공유.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# quarantine 대상 predicate — canonical(rejudged 필드) + 레거시(태그형 gate) 동시 인식.
# NOT LIKE '%rejudged%'는 canonical·레거시 모두에 걸려 재처리 방지 필터로 유효.
FAILOPEN_PENDING_SQL = (
    "metadata_json LIKE '%fail_open%'"
    " AND metadata_json NOT LIKE '%rejudged%'")

log = logging.getLogger("jev_mem.recover")

# pipeline._evaluate_turn과 동일한 정상 판정 reason 목록 (allowlist 반전 기준)
NORMAL_REASONS = ("store", "type-rescue", "low-conf", "skip", "context",
                  "no-store", "commitment-fp-v4", "parse-fail")


# ----------------------------------------------------------------------
# quarantine 행 조회 (mnemosyne.db read-only)
# ----------------------------------------------------------------------
def quarantine_rows(mconn, incident_id: Optional[str] = None, limit: int = 100
                    ) -> List[Dict]:
    """fail_open 마커 + 재판정 전(pending) 행 (P2b 태깅 기준, incident 필터).

    이미 rejudged 마커가 있는 행은 제외 — apply 완료 행의 재처리 방지
    (_incident_quarantine_left와 동일 필터).
    """
    q = ("SELECT id, content, metadata_json, timestamp FROM working_memory"
         f" WHERE {FAILOPEN_PENDING_SQL}")
    args: list = []
    if incident_id:
        q += " AND metadata_json LIKE ?"
        args.append(f"%{incident_id}%")
    q += " ORDER BY timestamp LIMIT ?"
    args.append(limit)
    rows = mconn.execute(q, args).fetchall()
    out = []
    for r in rows:
        meta = {}
        try:
            meta = json.loads(r["metadata_json"] or "{}")
        except Exception:
            pass
        out.append({
            "id": r["id"], "content": r["content"], "metadata": meta,
            "ts": r["timestamp"],
            "incident_id": meta.get("incident_id"),
            "fail_open": str(meta.get("gate", "")).replace("fail_open:", ""),
        })
    return out


def _role_of(content: str) -> str:
    return "assistant" if content.strip().startswith("[ASSISTANT]") else "user"


def _strip_prefix(content: str) -> str:
    for p in ("[USER] ", "[ASSISTANT] "):
        if content.startswith(p):
            return content[len(p):]
    return content


# ----------------------------------------------------------------------
# 단건 재판정 (strict) — JEV 실패 시 예외 (행 불변)
# ----------------------------------------------------------------------
def rejudge_one(content: str, *, role: str) -> Dict:
    """JEV gate 단건 호출 (strict). 실패 시 raise — 행 불변 (D3 strict).

    Returns: verdict dict {keep, reason, conf, ...}
    """
    from gateway.write_gate import evaluate, evaluate_assistant
    # gateway.write_gate는 HTTP 실패 시 keep=True + reason='http-NNN'을
    # 반환한다 (P2a _failure_result — fail-open 불변식). 재판정(strict)에서는
    # 이 응답이 '비정상 KEEP'으로 skip 오분류되므로, HTTP 실패를 예외로
    # 승격해 run_batch의 재장애(halt) 경로로 보낸다 (D8/D3).
    utterance = _strip_prefix(content)
    if role == "assistant":
        verdict = evaluate_assistant(utterance)
    else:
        verdict = evaluate(utterance)
    reason = str(verdict.get("reason") or "")
    if reason.startswith("http-"):
        code = reason.split("-")[-1]
        exc = RuntimeError(f"JEV gate HTTP {code} during rejudge")
        exc.reason = reason  # type: ignore[attr-defined]
        exc.status_code = int(code) if code.isdigit() else 0  # type: ignore[attr-defined]
        raise exc
    return verdict


def _classify_verdict(verdict: Dict) -> str:
    """verdict -> keep | skip (tools/jed_failopen_rejudge_v2와 동일 규칙)."""
    keep = bool(verdict.get("keep"))
    reason = str(verdict.get("reason") or "")
    # 정상 판정 KEEP만 keep; 그 외(비정상 reason KEEP 포함)는 skip
    if keep and reason in NORMAL_REASONS:
        return "keep"
    return "skip"


# ----------------------------------------------------------------------
# 배치 실행 엔진 (core worker + CLI 공용)
# ----------------------------------------------------------------------
class RejudgeEngine:
    """재판정 배치 실행 — status/lease/verdict 기록 포함.

    ctx: CoreContext (writer submit 경유 접근) 또는 CLI용 경량 어댑터.
    """

    def __init__(self, ctx: Any, *, cfg: Any = None):
        self.ctx = ctx
        self.cfg = cfg if cfg is not None else getattr(ctx, "cfg", None)

    # -- 상태 전이 (writer 스레드 경유) ---------------------------------
    def _mark_status(self, w, idem_key: str, status: str) -> None:
        from . import ledger
        ledger.ledger_mark(w.state, idem_key, status)

    # -- 회복 감지 (D4/D7): 실사용 호출 성공 시 incident streak ----------
    def record_recovery_success(self, incident_id: str) -> bool:
        """실제 호출 성공 1회 -> incident recovery streak 기록.

        Returns True if incident became rejudge_ready.
        """
        from . import ledger
        try:
            return self.ctx.writer.submit_sync(
                lambda w: ledger.recovery_record_success(
                    w.state, incident_id,
                    streak=self.cfg.rejudge_streak,
                    cooldown_min=self.cfg.rejudge_cooldown_min),
                "recovery_streak").result()
        except Exception:
            log.exception("recovery_record_success failed")
            return False

    def reset_recovery(self, incident_id: str) -> None:
        from . import ledger
        try:
            # .result(): halt 경로에서 재장애 반영을 결정적으로 커밋 (run_batch는
            # 워커 스레드에서 실행되므로 루프 블록 없음).
            self.ctx.writer.submit_sync(
                lambda w: ledger.recovery_reset(w.state, incident_id),
                "recovery_reset").result()
        except Exception:
            log.exception("recovery_reset failed")

    def ready_incidents(self) -> List[Dict]:
        from . import ledger
        try:
            return self.ctx.writer.submit_sync(
                lambda w: ledger.recovery_ready_incidents(w.state),
                "recovery_ready").result()
        except Exception:
            log.exception("recovery_ready_incidents failed")
            return []

    def open_incidents(self) -> List[Dict]:
        from . import ledger
        try:
            return self.ctx.writer.submit_sync(
                lambda w: ledger.outage_open_incidents(w.state),
                "outage_open_peek").result()
        except Exception:
            log.exception("outage_open_incidents failed")
            return []

    # -- 재판정 배치 ----------------------------------------------------
    def run_batch(self, *, incident_id: Optional[str] = None,
                  limit: Optional[int] = None) -> Dict:
        """재판정 배치 1회 실행 (bounded concurrency, strict, lease).

        Returns: {rejudged, kept, skipped, failed, halted, left}
        """
        cfg = self.cfg
        limit = limit or cfg.rejudge_batch
        from . import ledger

        # 1) quarantine 대상 (mnemosyne DB read-only)
        mconn = None
        try:
            mconn = self.ctx.reader_conn() if hasattr(self.ctx, "reader_conn") \
                else self._open_mem_ro()
            rows = quarantine_rows(mconn, incident_id=incident_id, limit=limit * 3)
        finally:
            if mconn is not None and not hasattr(self.ctx, "reader_conn"):
                try:
                    mconn.close()
                except Exception:
                    pass

        # 2) lease claim (writer 스레드 경유로 상태 DB에)
        claimed = []
        for r in rows:
            ok = self.ctx.writer.submit_sync(
                lambda w, rid=r["id"], iid=r.get("incident_id") or incident_id or "":
                ledger.rejudge_claim(w.state, rid, iid, cfg.rejudge_lease_s),
                "rejudge_claim").result()
            if ok:
                claimed.append(r)
            if len(claimed) >= limit:
                break

        # 3) 각 행 재판정 (strict — 실패 시 중단/리셋)
        kept = skipped = failed = 0
        halted = False
        transient_streak = 0
        log.info("rejudge batch: claimed=%d (incident=%s)", len(claimed), incident_id)
        for r in claimed:
            if self.ctx.breaker.is_open:
                halted = True
                log.warning("rejudge halted: circuit open")
                break
            try:
                verdict = rejudge_one(r["content"], role=_role_of(r["content"]))
                self.ctx.breaker.on_success()
                transient_streak = 0
            except Exception as e:
                failed += 1
                self.ctx.breaker.on_failure(e)
                # D8: 재장애 중단 기준 — billing/auth는 1회, transient는 N회
                reason = str(getattr(e, "reason", "") or e)
                code = str(getattr(e, "status_code", "") or "")
                is_halt = bool(code) and cfg.rejudge_billing_halt and (
                    code in ("402", "403", "401"))
                is_halt = is_halt or (cfg.rejudge_billing_halt and (
                    "402" in reason or "403" in reason or "401" in reason))
                transient_streak += 1
                is_halt = is_halt or transient_streak >= cfg.rejudge_transient_halt
                log.warning("rejudge row failed (%s): %s — halt=%s",
                            r["id"][:16], reason, is_halt)
                self._record_verdict(r["id"], "failed", str(reason)[:200],
                                     r.get("incident_id"), apply_status="none")
                if is_halt:
                    halted = True
                    self.reset_recovery(r["incident_id"] or incident_id or "")
                    break
                continue

            v = _classify_verdict(verdict)
            if v == "keep":
                kept += 1
            else:
                skipped += 1
            self._record_verdict(r["id"], v,
                                 str(verdict.get("reason") or ""),
                                 r.get("incident_id"), apply_status="applied")
            # apply: 메모리 행 metadata 반영 (P1 규칙 — recall beam 제외)
            self._apply_verdict(r["id"], v, r.get("incident_id") or "")
            # lease 해제
            self.ctx.writer.submit_sync(
                lambda w, rid=r["id"]: ledger.rejudge_release(w.state, rid),
                "rejudge_release")

        # 4) incident 완료 판정 (이 incident의 quarantine 소진 시)
        if incident_id and not halted:
            remaining = self._incident_quarantine_left(incident_id)
            if remaining == 0:
                self.ctx.writer.submit_sync(
                    lambda w: ledger.outage_mark_rejudge_done(w.state, incident_id),
                    "rejudge_done")
                log.info("incident %s rejudge done", incident_id)
        # left: incident 지정 시 그 incident의 잔여, 미지정(remnant) 시 전체 잔여
        left = self._incident_quarantine_left(incident_id or "")
        return {"rejudged": kept + skipped + failed, "kept": kept,
                "skipped": skipped, "failed": failed, "halted": halted,
                "left": left}

    def _apply_verdict(self, memory_id: str, verdict: str,
                       incident_id: str) -> None:
        """verdict를 메모리 행 metadata에 반영 (mnemosyne.db 직접 UPDATE).

        keep : metadata.rejudged='keep' — 행 유지, quarantine에서 제외
        skip : metadata.rejudged='skip' + archived=true + valid_until=now
               — P1 archiving 규칙과 동일하게 live recall에서 제외
        실패해도 rejudge_verdicts 기록은 유지 (재시도는 다음 배치에서).

        canonical 포맷 (rejudge_markers): gate 불변, mutation 후 직렬화,
        metadata_json만 UPDATE — valid_until 컬럼은 skip일 때만 별도 UPDATE.
        """
        import sqlite3
        from datetime import datetime
        db = Path(self.cfg.mnemosyne_db)
        try:
            conn = sqlite3.connect(f"file:{db.as_posix()}?mode=rw", uri=True,
                                   timeout=15)
            try:
                from .rejudge_markers import apply_rejudge_patch, now_iso
                ok = apply_rejudge_patch(
                    conn, memory_id, verdict,
                    model=getattr(self.cfg, "jev_model", "jev-latest"))
                if not ok:
                    log.warning("apply: row %s missing — skipped", memory_id)
                    return
                if verdict == "skip":
                    # ★컬럼 write 필수 — recall 필터는 metadata가 아니라 컬럼을 본다
                    # (beam.py: `valid_until IS NULL OR valid_until > now`).
                    # metadata만 쓰면 archived 행이 live recall에서 안 걸러짐
                    # (2026-10-03 실측 회귀: P3 경로 7건 노출).
                    conn.execute(
                        "UPDATE working_memory SET valid_until=? WHERE id=?",
                        (now_iso(), memory_id))
                conn.commit()
                log.info("apply %s -> %s (%s)", memory_id[:16], verdict,
                         incident_id)
            finally:
                conn.close()
        except Exception:
            log.exception("apply verdict failed for %s", memory_id)

    def _open_mem_ro(self):
        import sqlite3
        from pathlib import Path
        db = Path(self.cfg.mnemosyne_db)
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _incident_quarantine_left(self, incident_id: str) -> int:
        mconn = None
        try:
            mconn = self._open_mem_ro()
            if incident_id:
                row = mconn.execute(
                    "SELECT COUNT(*) AS n FROM working_memory"
                    f" WHERE {FAILOPEN_PENDING_SQL}"
                    " AND metadata_json LIKE ?",
                    (f"%{incident_id}%",)).fetchone()
            else:
                # remnant (incident 미지정): 전체 pending quarantine 수
                row = mconn.execute(
                    "SELECT COUNT(*) AS n FROM working_memory"
                    f" WHERE {FAILOPEN_PENDING_SQL}").fetchone()
            return int(row["n"]) if row else 0
        except Exception:
            return -1
        finally:
            if mconn is not None:
                try:
                    mconn.close()
                except Exception:
                    pass

    def _record_verdict(self, memory_id: str, verdict: str, reason: str,
                        incident_id: Optional[str], apply_status: str) -> None:
        """rejudge_verdicts 테이블 기록 (core_state.db, writer 경유)."""
        from datetime import datetime
        try:
            self.ctx.writer.submit_sync(
                lambda w: w.state.execute(
                    "INSERT OR REPLACE INTO rejudge_verdicts"
                    " (memory_id, verdict, model, reason, conf, lat_ms, rejudged_at,"
                    "  incident_id, apply_status) VALUES (?,?,?,?,?,?,?,?,?)",
                    (memory_id, verdict,
                     getattr(self.cfg, "jev_model", "jev-latest"),
                     reason, None, 0,
                     datetime.now().isoformat(timespec="seconds"),
                     incident_id or "", apply_status)),
                "rejudge_verdict").result()
            w = None
        except Exception:
            log.exception("verdict record failed for %s", memory_id)