"""Probe 1: JEV System One을 메모리 분류기로 쓸 수 있는지 확인.

14개 라벨(13 MemoryType + NO_STORE) choice 분류에 JEV가 응답하는지,
라벨 노출 방식(숫자형 인덱스 vs 문자열)과 레이턴시/성공률을 측정한다.
read-only probe — production 코드 수정 없음.
"""
import json
import os
import sys
import time
from pathlib import Path

import httpx

KEY = os.environ.get("TYPESAFE_API_KEY", "")
API = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"

# Mnemosyne 13 MemoryType + 평가용 NO_STORE (지시문 §2)
TYPES = [
    "fact", "preference", "decision", "commitment", "goal", "event",
    "instruction", "relationship", "context", "learning", "observation",
    "error", "artifact", "NO_STORE",
]

PROBES = [
    {"id": "p1", "utterance": "좋아 진행해줘.", "gold": "NO_STORE"},
    {"id": "p2", "utterance": "앞으로 답변은 항상 표로 정리해줘.", "gold": "preference"},
    {"id": "p3", "utterance": "오류가 발생했어. 빌드가 실패했어.", "gold": "error"},
    {"id": "p4", "utterance": "저는 필라델피아에서 워싱턴으로 가려고 해요.", "gold": "goal"},
    {"id": "p5", "utterance": "다음 목요일로 예약해 주세요.", "gold": "commitment"},
    {"id": "p6", "utterance": "I prefer concise answers with bullet points.", "gold": "preference"},
    {"id": "p7", "utterance": "그걸로 가자.", "gold": "NO_STORE"},
]


def jev_choice(utterance: str, labels: list[str], instructions: str,
               timeout: float = 30.0) -> tuple:
    """TypeSafe System One choice 질문 1회 호출.

    returns (choice_raw, latency_ms, status, response_text)
    """
    state = {
        "utterance": utterance,
        "candidates": [
            {"id": f"t{i}", "label": lab} for i, lab in enumerate(labels)
        ],
    }
    questions = {
        "classify": {
            "type": "choice",
            "instructions": instructions,
            "criteria": {f"c{i}": lab for i, lab in enumerate(labels)},
        }
    }
    t0 = time.perf_counter()
    try:
        resp = httpx.post(
            API,
            headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
            json={"state": state, "questions": questions, "model": MODEL},
            timeout=timeout,
        )
    except Exception as e:
        return None, (time.perf_counter() - t0) * 1000, -1, f"EXC: {e}"
    lat = (time.perf_counter() - t0) * 1000
    if resp.status_code != 200:
        return None, lat, resp.status_code, resp.text[:300]
    data = resp.json()
    ans = (data.get("answers") or {}).get("classify") or {}
    return ans.get("choice"), lat, resp.status_code, json.dumps(data, ensure_ascii=False)[:500]


if __name__ == "__main__":
    if not KEY:
        print("!! TYPESAFE_API_KEY 미설정 — .env에서 로드 필요")
        sys.exit(2)

    # 지시문 §2/§5 기반: 발화의 "장기 메모리 가치" 판단 지시
    instructions = (
        "Classify the speaker's utterance into exactly one memory type "
        "from the given criteria. Consider: (1) whether this utterance has "
        "long-term memory value worth storing (NO_STORE if it is a one-off "
        "conversational remark, acknowledgment, or trivial request without "
        "lasting value); (2) if it is worth storing, pick the most accurate "
        "semantic memory type describing the utterance's content and intent. "
        "Pick exactly one."
    )

    lats = []
    for p in PROBES:
        choice, lat, status, body = jev_choice(p["utterance"], TYPES, instructions)
        lats.append(lat if status == 200 else None)
        print(f"[{p['id']}] gold={p['gold']!r} JEV_choice={choice!r} "
              f"status={status} lat={lat:.0f}ms")
        if status != 200:
            print(f"    body: {body[:200]}")
        elif choice is not None:
            # c0~c13 -> 인덱스 -> 라벨 매핑 시도 (문자열 직접 반환일 수도)
            c = str(choice).lstrip("c")
            try:
                idx = int(c)
                label = TYPES[idx] if 0 <= idx < len(TYPES) else f"IDX_OUT_OF_RANGE({choice})"
            except ValueError:
                label = choice  # 문자열 라벨 직접 반환
            print(f"    -> label={label!r} match={label == p['gold']}")

    ok = [x for x in lats if x is not None]
    print(f"\n=== PROBE SUMMARY ===")
    print(f"success: {len(ok)}/{len(PROBES)} | "
          f"latency: avg={sum(ok)/len(ok):.0f}ms p95={sorted(ok)[int(len(ok)*0.95)-1]:.0f}ms"
          if ok else "all failed")