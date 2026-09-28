"""v3 프롬프트 spot check — commitment/context 정의 강조가 정확도를 올리는지."""
import json
import os
import time

import httpx

TYPES = ['fact', 'preference', 'decision', 'commitment', 'goal', 'event',
         'instruction', 'relationship', 'context', 'learning', 'observation',
         'error', 'artifact', 'NO_STORE']

V3 = (
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
    "- preference: durable like/dislike.\n"
    "- observation: recurring pattern ('keeps happening').\n"
    "- learning: lesson learned.\n"
    "\n"
    "If conversation context is provided, use it to judge one-off vs lasting. "
    "Pick exactly one."
)


def classify(utt: str, ctx: str = ""):
    state = {"utterance": utt}
    if ctx:
        state["context"] = ctx
    q = {"classify": {
        "type": "choice", "instructions": V3,
        "criteria": {f"c{i}": t for i, t in enumerate(TYPES)}}}
    r = httpx.post(
        "https://api.typesafe.ai/v1/systemone",
        headers={"Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}",
                 "Content-Type": "application/json"},
        json={"state": state, "questions": q, "model": "jev-latest"},
        timeout=30)
    a = (r.json().get("answers") or {}).get("classify") or {}
    c = str(a.get("choice", "")).lstrip("c")
    pred = TYPES[int(c)] if c.isdigit() and int(c) < len(TYPES) else a.get("choice")
    probs = a.get("probabilities") or {}
    conf = probs.get(a.get("choice"), 0)
    return pred, conf


if __name__ == "__main__":
    tests = [
        ("내일까지 보고서 제출해야 해", "commitment", ""),
        ("다음 목요일로 예약해 주세요", "commitment", ""),
        ("3시에 전화할게", "commitment", ""),
        ("지금 작업 중이야", "context", ""),
        ("피곤하고 스트레스가 많아요", "context", ""),
        ("여행 가는데 호텔 방 하나 필요해", "context", ""),
        ("이번 주말에 이사해야 해", "commitment", ""),
        ("좋아 진행해줘", "NO_STORE", ""),
        ("앞으로 답변은 항상 표로 정리해줘", "instruction", ""),
        ("오류가 발생했어, 빌드가 실패했어", "error", ""),
    ]
    ok = 0
    for utt, gold, ctx in tests:
        pred, conf = classify(utt, ctx)
        mark = "✓" if pred == gold else "✗"
        if pred == gold:
            ok += 1
        print(f"{mark} gold={gold:12s} v3={pred:12s} conf={conf:.2f}  {utt[:35]!r}")
    print(f"\n{ok}/{len(tests)} 맞음")