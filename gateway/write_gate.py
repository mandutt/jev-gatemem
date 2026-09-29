"""JEV write gate — G-qual 규칙 (P8+G-qual, 2026-09-28 실측 채택).

- SKIP (user, G-qual) = store==NO_STORE && type==NO_STORE && store_confidence>=0.6
- SKIP (assistant, G-AS) = store==NO_STORE | (store==STORE && type==context)
- KEEP = 그 외 | 파싱 실패 | JEV 호출 실패/타임아웃/비활성/키 없음 (누락 방지)
- 킬스위치: JEV_WRITE_GATE=0 → KEEP (게이트 비활성)
- 타임아웃 15s + 1회 재시도 (5xx/시간초과) — 실측 latency 0.24~1.9s 꼬리 23s

실측 근거 (memory-classification-evaluation/):
- user: store recall 0.951 (+45% vs G0.6 0.656), live 142건 누락 0
- assistant: gold50 precision 0.744 / recall 0.935 / F1 0.829
- assistant context 필터: 17건 전수 gold → 오분류 0건 (결과물 손실 0)
"""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Dict, Optional

log = logging.getLogger(__name__)

JEV_WRITE_GATE_ENV = "JEV_WRITE_GATE"
# 실측 (2026-09-28): JEV API latency 0.24~1.9s (대부분 <0.5s), 서버 오류 503/520
# 간헐 + 상위 꼬리 23s. 5s 하드캡은 잦은 실패(→전부 KEEP)를 유발해 게이트 무력화.
# 15s + 1회 재시도로 상향: 대부분 즉시 통과, 서버 오류는 재시도로 흡수.
JEV_WRITE_GATE_TIMEOUT_S = 15.0
JEV_WRITE_GATE_RETRIES = 1

API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"

TYPES = [
    "fact", "preference", "decision", "commitment", "goal", "event",
    "instruction", "relationship", "context", "learning", "observation",
    "error", "artifact", "NO_STORE",
]

# G-AS commitment FP 필터 v4 (2026-09-28 실험 확정):
#   gold50: 회귀 0, FP 43% 감소 (precision 0.744→0.806, F1 0.829→0.866)
#   트레이드오프: 지식작업 보호(KNOWLEDGE) ↔ 실행작업 전환 포착(TRANSITION+OPERATION)
_AS_KNOWLEDGE = re.compile(
    r"(검증|확인|조사|분석|테스트|정밀|확정|검토|추정|판단|파악|실측|분해|라이브|확보)"
)
_AS_OPERATION = re.compile(
    r"(백업|설치|스왑|설정|복구|적용|구축|등록|이관|모니터링|cron)"
)
_AS_TRANSITION = re.compile(
    r"(정상|감지|동작|완료|완성|등록|파악).{0,40}(이제|다음|그럼)"
)
_AS_INTENT = re.compile(
    r"(진행하겠|만들겠|구축하|정리하|작성하겠|등록하겠|돌릴게|할게|해볼게|적용하겠|시작하겠|세겠습니다)"
)


def _as_commitment_fp_filter(utterance: str) -> bool:
    """G-AS commitment 추가 필터 v4 — True면 SKIP (저장 생략).

    KNOWLEDGE(지식작업) 있으면 KEEP (TP 보호),
    TRANSITION(결과→이제/다음) && OPERATION(실행작업) → SKIP,
    INTENT(순수 진행 의지) → SKIP.
    """
    if _AS_KNOWLEDGE.search(utterance[:200]):
        return False
    if _AS_TRANSITION.search(utterance) and _AS_OPERATION.search(utterance):
        return True
    if _AS_INTENT.search(utterance):
        return True
    return False

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


def _post_systemone(client, *, utterance: str, timeout: float) -> tuple:
    """POST /v1/systemone with retry on transient server errors.

    Returns (status_code, answers_dict). Retries up to JEV_WRITE_GATE_RETRIES
    on HTTP 5xx (503/520) — observed intermittently on the live API.
    Never raises for transient failures; network exceptions surface to the
    caller's try/except (-> KEEP).
    """
    import httpx

    utterance_cut = (utterance or "")[:1500]
    state = {
        "utterance": utterance_cut,
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
    body = {"state": state, "questions": questions, "model": MODEL}
    last_status = None
    last_answers = {}
    attempts = 1 + JEV_WRITE_GATE_RETRIES
    for attempt in range(attempts):
        try:
            resp = client.post(API_URL, json=body, timeout=timeout)
        except httpx.TimeoutException:
            if attempt < attempts - 1:
                continue  # transient timeout — retry
            raise
        last_status = resp.status_code
        if resp.status_code == 200:
            return 200, (resp.json().get("answers") or {})
        if resp.status_code >= 500 and attempt < attempts - 1:
            continue  # server error (503/520) — retry
        return resp.status_code, {}
    return last_status or 0, last_answers


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
        t0 = time.perf_counter()
        try:
            status_code, answers = _post_systemone(c, utterance=utterance, timeout=timeout)
        finally:
            if own_client:
                c.close()
        lat_ms = (time.perf_counter() - t0) * 1000
        if status_code != 200:
            log.info("write-gate HTTP %s -> KEEP", status_code)
            return {"keep": True, "reason": f"http-{status_code}"}
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
        else:
            # B: KEEP도 trace (2026-09-29 실측 채택) — 게이트 판정 근거를 항상 남김.
            # SKIP 전용 trace는 "KEEP vs 미평가"를 구분 못 해 사후 감사 불가였음.
            # unconditional (옵션 없음): 플러그인 자체 완결성 — 스킬/문서 부재에도 감사 가능.
            _jtrace("write-gate", {
                "keep": "keep",
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


def evaluate_assistant(utterance: str, *, client=None, timeout: float = JEV_WRITE_GATE_TIMEOUT_S) -> Dict:
    """G-AS 게이트 평가 (assistant 발화 전용, 2026-09-28 확정).

    규칙 (jev_classify_AS.gate_keep와 동일):
      - KEEP  = store==STORE && type != context  (저장 가치 있는 결과물)
      - SKIP  = store==NO_STORE | (store==STORE && type==context)
      - 파싱 실패(store=None)만 KEEP — 누락 방지
    입력은 1500자로 truncation (HTTP 400 회피 — 200건 분석에서 검증된 cut).

    절대 raise하지 않음 — 실패 시 keep=True (KEEP, 누락 방지).
    """
    if not (utterance or "").strip():
        return {"keep": True, "reason": "empty"}
    if not gate_enabled():
        return {"keep": True, "reason": "killswitch-off"}

    key = os.environ.get("TYPESAFE_API_KEY") or ""
    if not key:
        log.debug("write-gate-as: no TYPESAFE_API_KEY -> KEEP")
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
        t0 = time.perf_counter()
        try:
            status_code, answers = _post_systemone(c, utterance=utterance, timeout=timeout)
        finally:
            if own_client:
                c.close()
        lat_ms = (time.perf_counter() - t0) * 1000
        if status_code != 200:
            log.info("write-gate-as HTTP %s -> KEEP", status_code)
            return {"keep": True, "reason": f"http-{status_code}"}
        store_idx, store_conf = _collect(answers, "store")
        type_idx, type_conf = _collect(answers, "classify")
        store = "STORE" if store_idx == 0 else ("NO_STORE" if store_idx == 1 else None)
        mtype = TYPES[type_idx] if type_idx is not None and 0 <= type_idx < len(TYPES) else None
        store_conf = store_conf if store_conf is not None else 0.0
        type_conf = type_conf if type_conf is not None else 0.0

        # G-AS 규칙 (gold50 + ctx17 전수 검증으로 채택, jev_classify_AS.gate_keep와 동일)
        #   KEEP  = store==STORE && type!=context
        #   SKIP  = (store==STORE && type==context) | store==NO_STORE
        #   파싱 실패(store=None)만 KEEP — 누락 방지
        #   + commitment FP 필터 v4: KEEP 중 "진행 전환/순수 진행 의지" → SKIP
        if store == "STORE" and mtype != "context":
            if mtype == "commitment" and _as_commitment_fp_filter(utterance or ""):
                keep = False
                reason = "commitment-fp-v4"
            else:
                keep = True
                reason = "store"
        elif store in ("STORE", "NO_STORE"):
            keep = False
            reason = "context" if mtype == "context" else "no-store"
        else:
            keep = True
            reason = "parse-fail"

        if not keep:
            _jtrace("write-gate-as", {
                "keep": "skip",
                "store": store,
                "store_conf": f"{store_conf:.2f}",
                "type": mtype,
                "type_conf": f"{type_conf:.2f}",
                "reason": reason,
                "lat_ms": f"{lat_ms:.0f}",
                "utterance": (utterance or "")[:100],
            })
        else:
            # B: KEEP도 trace (2026-09-29 실측 채택) — assistant 게이트 판정 근거를 항상 남김.
            # unconditional: 플러그인 자체 완결성 (스킬/문서 부재에도 사후 감사 가능).
            _jtrace("write-gate-as", {
                "keep": "keep",
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
        log.info("write-gate-as failed (%s) -> KEEP", type(exc).__name__)
        return {"keep": True, "reason": "error", "error": str(exc)[:120]}


def gate_enabled() -> bool:
    """JEV_WRITE_GATE: '0'/'false'/'off' -> 비활성 (KEEP). 기본 활성."""
    raw = (os.environ.get(JEV_WRITE_GATE_ENV) or "").strip().lower()
    if raw in ("0", "false", "off", "no", "disabled"):
        return False
    return True


__all__ = ["evaluate", "evaluate_assistant", "gate_enabled", "STORE_INSTRUCTIONS", "CLASSIFY_INSTRUCTIONS", "TYPES"]