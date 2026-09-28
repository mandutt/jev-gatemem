"""JEV write gate — G-qual 규칙 (P8+G-qual, 2026-09-28 실측 채택).

- SKIP = store==NO_STORE && type==NO_STORE && store_confidence>=0.6
- KEEP = 그 외 (store==STORE | type 저장타입 | 저신뢰 NO_STORE)
- JEV 호출 실패/타임아웃/비활성/키 없음 → KEEP (기존 저장, 누락 방지)
- 킬스위치: JEV_WRITE_GATE=0 → KEEP (게이트 비활성)

실측 근거 (memory-classification-evaluation/JEV_INGESTION_REPORT.md):
- store recall 0.951 (+45% vs G0.6 0.656)
- live 142건: 누락 0, 과다 5
- store 오분류 근본 원인 = store 지시문 편향 → type 이중확인으로 해결 (P11 실험)
"""
from __future__ import annotations

import logging
import os
import time
from typing import Dict, Optional

log = logging.getLogger(__name__)

JEV_WRITE_GATE_ENV = "JEV_WRITE_GATE"
JEV_WRITE_GATE_TIMEOUT_S = 5.0  # rerank와 동일한 하드 캡

API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"

TYPES = [
    "fact", "preference", "decision", "commitment", "goal", "event",
    "instruction", "relationship", "context", "learning", "observation",
    "error", "artifact", "NO_STORE",
]

STORE_INSTRUCTIONS = (
    "Does this utterance have long-term memory value worth storing? "
    "Pick exactly one.\n"
    "NO_STORE examples: '좋아 진행해줘' / '알겠습니다' / '그걸로 가자' / "
    "'감사합니다' / '네 그럼요' / '안녕하세요' / '서커스야' / '좋아, 스테이지 도어 좋네'\n"
    "STORE examples: '앞으로 답변은 항상 표로 정리해줘' / '내일까지 보고서 제출해야 해' / "
    "'나는 간결한 답변을 좋아해' / '오류가 발생했어, 빌드가 실패했어'\n"
    "NO_STORE for one-off conversational remarks, acknowledgments, trivial "
    "requests, small talk, or anything without lasting value. STORE only if "
    "it is a durable fact, preference, rule, decision, commitment, goal, "
    "event, relationship, learning, observation, error report, or artifact "
    "reference. Pick exactly one."
)

CLASSIFY_INSTRUCTIONS = (
    "Classify the speaker's utterance into exactly one memory type from the "
    "criteria, based on meaning and intent, NOT grammar or sentence ending.\n"
    "\n"
    "Key distinctions:\n"
    "- commitment: a promise, deadline, or obligation (e.g. 'I need to submit "
    "the report by tomorrow', 'I'll call you at 3pm'). Time-bound duties.\n"
    "- decision: a settled choice ('let's go with X').\n"
    "- context: a TEMPORARY state or ongoing situation ('I'm currently working "
    "on X', 'it's raining now'). If the utterance describes a transient "
    "situation rather than a lasting fact, it is context.\n"
    "- instruction: a RULE to apply REPEATEDLY from now on (e.g. 'from now on "
    "always format answers as a table'). A one-off request or acknowledgment "
    "(e.g. 'ok go ahead') is NOT instruction — it is NO_STORE.\n"
    "- NO_STORE: one-off filler, acknowledgment, small request, small talk, "
    "question without lasting value.\n"
    "- fact: a VERIFIABLE, settled statement ('the report is 40 pages'). Do NOT "
    "use for likes, events, or relationships.\n"
    "- event: something that HAPPENED at a specific time, an occurrence "
    "('the server crashed yesterday', 'we met at the cafe').\n"
    "- relationship: a connection between people ('my brother is a doctor', "
    "'we are coworkers').\n"
    "- artifact: a file, document, repo, or resource and where it lives "
    "('config.yaml is here', 'the repo is on GitHub').\n"
    "- preference: durable like/dislike.\n"
    "- observation: recurring pattern ('keeps happening').\n"
    "- learning: lesson learned.\n"
    "\n"
    "If conversation context is provided, use it to judge one-off vs lasting. "
    "Pick exactly one."
)


def _jtrace(event: str, fields: dict) -> None:
    """trace() lazy resolver — gateway shadowing-safe (j1_pipeline._jtrace와 동일 패턴)."""
    try:
        import importlib.util
        import sys as _sys
        from pathlib import Path as _Path

        mod = None
        alias = _sys.modules.get("__j1mw_gateway")
        if alias is not None:
            t = getattr(alias, "trace", None)
            if t is not None:
                mod = getattr(t, "trace", None) or t
        if mod is None:
            try:
                from gateway.trace import trace as _t
                mod = _t
            except Exception:
                mod = None
        if mod is None:
            _repo = _Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware")
            spec = importlib.util.spec_from_file_location(
                "jev_trace_direct_wg", _repo / "gateway" / "trace.py"
            )
            if spec and spec.loader:
                m = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(m)
                mod = m.trace
        if mod is None:
            return
        mod(event, fields)
    except Exception:
        pass  # tracing must never raise


def _collect(answers: Dict, key: str):
    a = answers.get(key) or {}
    choice = a.get("choice")
    probs = a.get("probabilities") or {}
    if choice is None:
        return None, None
    c = str(choice).lstrip("c")
    try:
        return int(c), probs.get(choice, probs.get(f"c{int(c)}"))
    except ValueError:
        return None, None


def evaluate(utterance: str, *, client=None, timeout: float = JEV_WRITE_GATE_TIMEOUT_S) -> Dict:
    """G-qual 게이트 평가. 반환: {keep, store, store_conf, type, type_conf, reason, latency_ms}.

    절대 raise하지 않음 — 실패 시 keep=True (KEEP, 누락 방지).
    """
    if not (utterance or "").strip():
        return {"keep": True, "reason": "empty"}
    if not gate_enabled():
        return {"keep": True, "reason": "killswitch-off"}

    key = os.environ.get("TYPESAFE_API_KEY") or ""
    if not key:
        log.debug("write-gate: no TYPESAFE_API_KEY -> KEEP")
        return {"keep": True, "reason": "no-key"}

    try:
        import httpx

        own_client = client is None
        c = client or httpx.Client(
            timeout=httpx.Timeout(timeout, connect=timeout),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
        )
        state = {
            "utterance": utterance,
            "candidates": [{"id": f"t{i}", "label": t} for i, t in enumerate(TYPES)],
        }
        questions = {
            "store": {
                "type": "choice",
                "instructions": STORE_INSTRUCTIONS,
                "criteria": {"c0": "STORE", "c1": "NO_STORE"},
            },
            "classify": {
                "type": "choice",
                "instructions": CLASSIFY_INSTRUCTIONS,
                "criteria": {f"c{i}": t for i, t in enumerate(TYPES)},
            },
        }
        t0 = time.perf_counter()
        try:
            resp = c.post(
                API_URL,
                json={"state": state, "questions": questions, "model": MODEL},
                timeout=timeout,
            )
        finally:
            if own_client:
                c.close()
        lat_ms = (time.perf_counter() - t0) * 1000
        if resp.status_code != 200:
            log.info("write-gate HTTP %s -> KEEP", resp.status_code)
            return {"keep": True, "reason": f"http-{resp.status_code}"}

        answers = resp.json().get("answers") or {}
        store_idx, store_conf = _collect(answers, "store")
        type_idx, type_conf = _collect(answers, "classify")
        store = "STORE" if store_idx == 0 else ("NO_STORE" if store_idx == 1 else None)
        mtype = TYPES[type_idx] if type_idx is not None and 0 <= type_idx < len(TYPES) else None
        store_conf = store_conf if store_conf is not None else 0.0
        type_conf = type_conf if type_conf is not None else 0.0

        # G-qual 규칙
        if store == "STORE":
            keep = True
            reason = "store"
        elif mtype not in (None, "NO_STORE"):
            keep = True
            reason = "type-rescue"
        elif store_conf >= 0.6:
            keep = False
            reason = "skip"
        else:
            keep = True
            reason = "low-conf"

        if not keep:
            _jtrace("write-gate", {
                "keep": "skip",
                "store": store,
                "store_conf": f"{store_conf:.2f}",
                "type": mtype,
                "type_conf": f"{type_conf:.2f}",
                "reason": reason,
                "lat_ms": f"{lat_ms:.0f}",
                "utterance": (utterance or "")[:100],
            })
        return {
            "keep": keep,
            "store": store,
            "store_conf": store_conf,
            "type": mtype,
            "type_conf": type_conf,
            "reason": reason,
            "latency_ms": round(lat_ms, 1),
        }
    except Exception as exc:
        log.info("write-gate failed (%s) -> KEEP", type(exc).__name__)
        return {"keep": True, "reason": "error", "error": str(exc)[:120]}


def gate_enabled() -> bool:
    """JEV_WRITE_GATE: '0'/'false'/'off' -> 비활성 (KEEP). 기본 활성."""
    raw = (os.environ.get(JEV_WRITE_GATE_ENV) or "").strip().lower()
    if raw in ("0", "false", "off", "no", "disabled"):
        return False
    return True


__all__ = ["evaluate", "gate_enabled", "STORE_INSTRUCTIONS", "CLASSIFY_INSTRUCTIONS", "TYPES"]