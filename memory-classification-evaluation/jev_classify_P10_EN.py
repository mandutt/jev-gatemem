"""P10-EN — P10 프롬프트의 지시문만 영어로 번역한 A/B 분류기.

가설: JEV가 영어 지시문에 더 잘 따르는지 검증 (실측 결과: 차이 없음 — 400건 68.5% vs KO 67.2%, 미채택).
- STORE_INSTRUCTIONS: 영어 지시 + 한국어 예시 유지
- CLASSIFY_INSTRUCTIONS: 영어 지시 + 한국어 예시 (별도 없음 — P10과 동일 구조)
"""
import argparse
import concurrent.futures
import json
import os
import sys
import time
from pathlib import Path

import httpx

API = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
TYPES = ["fact", "preference", "decision", "commitment", "goal", "event",
         "instruction", "relationship", "context", "learning", "observation",
         "error", "artifact", "NO_STORE"]

STORE_INSTRUCTIONS_EN = (
    "STORE if the utterance has lasting value for future conversations, "
    "NO_STORE otherwise.\n"
    "NO_STORE examples: '좋아 진행해줘' / '알겠습니다' / '그걸로 가자' / "
    "'감사합니다' / '네 그럼요' / '안녕하세요' / '서커스야' / '좋아, 스테이지 도어 좋네'\n"
    "STORE examples: '앞으로 답변은 항상 표로 정리해줘' / '내일까지 보고서 제출해야 해' / "
    "'나는 간결한 답변을 좋아해' / '오류가 발생했어, 빌드가 실패했어'\n"
    "IMPORTANT: in a software/coding work context, questions about design, "
    "architecture, implementation, debugging, or project state ('how does X "
    "work?', 'which approach is better?', 'why is the build failing?') ARE "
    "valuable context — STORE them. GO-AHEAD commands that only approve or "
    "continue already-started work ('좋아 진행해줘', '다음 단계 진행하자', "
    "'좋아 별도 설계해서 실험해봐', '네가 테스트를 진행해줘', '그걸로 가자') "
    "carry no new information — NO_STORE. NO_STORE is only for casual small "
    "talk, one-off acknowledgments, thanks, and go-ahead commands.\n"
    "Pick exactly one."
)

CLASSIFY_INSTRUCTIONS_EN = (
    "Classify the speaker's utterance into exactly one memory type from the "
    "criteria, based on meaning and intent, NOT grammar or sentence ending.\n"
    "\n"
    "Key distinctions:\n"
    "- commitment: a promise, deadline, or obligation with a TIME or PLACE — "
    "including reservations, schedules, and travel plans ('I'll call you at "
    "3pm', 'book a table for 4 on March 10', 'I'm leaving on the 4th', 'pick "
    "me up at 6:30'). A one-off service notice to the other party ('I'll send "
    "you a confirmation email') or a general statement of need ('I have to "
    "pay', 'I need to take classes') is NOT commitment — it is NO_STORE or "
    "context.\n"
    "- decision: a settled choice about HOW to do something ('let's go with "
    "X', 'I'll take the second one', 'let's use this structure from now on', "
    "'let's write tests with pytest'). A preference or wish ('I should look "
    "for a job') is NOT a decision — it is a goal or preference.\n"
    "- goal: a desired outcome or intention the speaker wants to achieve, "
    "without a firm time/place commitment ('I want to find a job', 'I need a "
    "hotel room for the trip').\n"
    "- context: only when the speaker describes what they are CURRENTLY doing "
    "or their current temporary state ('I'm working on X right now', 'we're "
    "waiting for the bus', 'I just finished rehearsal', 'the reservation is "
    "confirmed'). Do NOT use for opinions, small talk, general statements, "
    "or one-off remarks — those are NO_STORE or preference.\n"
    "- instruction: a RULE to apply REPEATEDLY from now on, or an explicit "
    "task directive ('from now on always format answers as a table', 'add two "
    "sentences to this text', 'analyze this financial report'). Do NOT use for "
    "one-off advice, ATM/guide notices, or casual commands — even in "
    "imperative form ('insert your card', 'look at your heels', 'calm down') — "
    "those are NO_STORE.\n"
    "- NO_STORE: one-off filler, acknowledgment, small request, small talk, "
    "question without lasting value.\n"
    "- fact: a VERIFIABLE, settled statement ('the report is 40 pages'). Do NOT "
    "use for likes, events, or relationships.\n"
    "- event: something that HAPPENED at a specific time, an occurrence "
    "('the server crashed yesterday', 'we met at the cafe').\n"
    "- relationship: a STATIC connection or role of the speaker or people "
    "('my brother is a doctor', 'we are coworkers', 'I work at a store as its "
    "manager', 'I am a CS student'). Do NOT use for feelings about people, "
    "compliments, or affection ('I love kids', 'you are the only one for me') "
    "— those are preference or NO_STORE.\n"
    "- artifact: a file, document, repo, or resource and where it lives "
    "('config.yaml is here', 'the repo is on GitHub').\n"
    "- preference: durable like/dislike, opinion, or belief.\n"
    "- observation: ONLY a repeated pattern affecting the speaker that KEEPS "
    "happening ('it keeps crashing', 'she always forgets'). Do NOT use for "
    "one-time events, general statements about society, or everyday filler — "
    "even if it contains 'always' or 'often' as a figure of speech.\n"
    "- learning: a realization, discovery, lesson, or changed approach — even "
    "stated as a past event ('I realized my daughter sings beautifully', "
    "'that method caused problems so I switched', 'I learned that ...').\n"
    "\n"
    "WORK CONTEXT RULE: in software/coding sessions, questions about design, "
    "architecture, implementation details, debugging, or project state are "
    "VALUABLE — classify them as context, decision, learning, or fact as "
    "appropriate, never NO_STORE. Reserve NO_STORE for casual small talk, "
    "thanks, acknowledgments, and go-ahead commands.\n"
    "\n"
    "If conversation context is provided, use it to judge one-off vs lasting. "
    "Pick exactly one."
)


def jev_classify_en(utterance: str, context: str = "", timeout: float = 60.0) -> dict:
    """One JEV call (EN instructions): returns {store, store_prob, type, type_prob, probs, latency_ms, usage}."""
    state = {
        "utterance": utterance,
        "candidates": [{"id": f"t{i}", "label": t} for i, t in enumerate(TYPES)],
    }
    if context:
        state["context"] = context
    questions = {
        "store": {
            "type": "choice",
            "instructions": STORE_INSTRUCTIONS_EN,
            "criteria": {"c0": "STORE", "c1": "NO_STORE"},
        },
        "classify": {
            "type": "choice",
            "instructions": CLASSIFY_INSTRUCTIONS_EN,
            "criteria": {f"c{i}": t for i, t in enumerate(TYPES)},
        },
    }
    t0 = time.perf_counter()
    resp = httpx.post(
        API,
        headers={
            "Authorization": f"Bearer {os.environ.get('TYPESAFE_API_KEY', '')}",
            "Content-Type": "application/json",
        },
        json={"state": state, "questions": questions, "model": MODEL},
        timeout=timeout,
    )
    lat_ms = (time.perf_counter() - t0) * 1000
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    answers = data.get("answers") or {}

    def _pick(key: str):
        a = answers.get(key) or {}
        choice = a.get("choice")
        probs = a.get("probabilities") or {}
        if choice is None:
            return None, None, probs
        c = str(choice).lstrip("c")
        try:
            return int(c), probs.get(choice, probs.get(f"c{int(c)}")), probs
        except ValueError:
            return None, None, probs

    store_idx, store_prob, store_probs = _pick("store")
    type_idx, type_prob, type_probs = _pick("classify")

    return {
        "store": "STORE" if store_idx == 0 else ("NO_STORE" if store_idx == 1 else None),
        "store_confidence": store_prob,
        "store_probs": store_probs,
        "type": TYPES[type_idx] if type_idx is not None and 0 <= type_idx < len(TYPES) else None,
        "type_confidence": type_prob,
        "type_probs": type_probs,
        "latency_ms": round(lat_ms, 1),
        "usage": data.get("usage") or {},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()

    if not os.environ.get("TYPESAFE_API_KEY"):
        print("!! TYPESAFE_API_KEY 미설정")
        sys.exit(2)

    rows = [json.loads(l) for l in open(args.input, encoding="utf-8")]
    if args.limit:
        rows = rows[: args.limit]

    done_ids = set()
    if Path(args.output).exists():
        for l in open(args.output, encoding="utf-8"):
            try:
                done_ids.add(json.loads(l)["id"])
            except Exception:
                pass
    todo = [r for r in rows if r["id"] not in done_ids]
    print(f"resume: {len(done_ids)} done, {len(todo)} todo, workers={args.workers}")

    def process(row):
        for attempt in range(3):
            try:
                res = jev_classify_en(row["utterance"], row.get("context", ""))
                return {
                    "id": row["id"],
                    "dataset": row.get("dataset"),
                    "utterance": row["utterance"],
                    "gold_type": row.get("gold_type"),
                    "gold_should_store": row.get("gold_should_store"),
                    **res,
                }
            except Exception as e:
                if attempt == 2:
                    return {"id": row["id"], "error": str(e)[:200]}
                time.sleep(2 * (attempt + 1))

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(process, r): r for r in todo}
        done = 0
        with open(args.output, "a", encoding="utf-8") as f:
            for fut in concurrent.futures.as_completed(futures):
                r = fut.result()
                results.append(r)
                if "error" not in r:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                    f.flush()
                done += 1
                if done % 20 == 0:
                    print(f"  {done}/{len(todo)} done", flush=True)
    results.sort(key=lambda r: r["id"])
    n_ok = len([r for r in results if "error" not in r])
    n_err = len([r for r in results if "error" in r])
    print(f"done: {n_ok} ok, {n_err} errors")
    if n_err:
        for r in [x for x in results if "error" in x][:5]:
            print(" ", r["id"][:50], "->", r["error"][:80])


if __name__ == "__main__":
    main()