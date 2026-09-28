"""v7 프롬프트 검증 — relationship/instruction 오분류 케이스 재분류.

대상: (1) gold=relationship/instruction인데 틀린 것 (2) pred=relationship/instruction인데 gold가 다른 것
실행: python jev_v7_probe.py  (workers=3)
출력: JEV_V7_PROBE.jsonl
"""
import json
import os
import time
from pathlib import Path

import httpx

HERE = Path(__file__).parent
API = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
TYPES = ["fact", "preference", "commitment", "goal", "event", "observation",
         "learning", "relationship", "context", "instruction", "decision",
         "error", "artifact", "NO_STORE"]

CLASSIFY_INSTRUCTIONS = (
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
    "- decision: a settled choice ('let's go with X', 'I'll take the second "
    "one').\n"
    "- context: only when the speaker describes what they are CURRENTLY doing "
    "or their current temporary state ('I'm working on X right now', 'we're "
    "waiting for the bus'). Do NOT use for opinions, small talk, general "
    "statements, or one-off remarks — those are NO_STORE or preference.\n"
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
    "If conversation context is provided, use it to judge one-off vs lasting. "
    "Pick exactly one."
)


def jev_classify(utterance: str, context: str = "") -> dict:
    state = {"utterance": utterance, "candidates": [{"id": f"t{i}", "label": t} for i, t in enumerate(TYPES)]}
    if context:
        state["context"] = context
    questions = {
        "store": {"type": "choice", "instructions": "STORE if worth remembering later, NO_STORE otherwise.",
                  "criteria": {"c0": "STORE", "c1": "NO_STORE"}},
        "classify": {"type": "choice", "instructions": CLASSIFY_INSTRUCTIONS,
                     "criteria": {f"c{i}": t for i, t in enumerate(TYPES)}},
    }
    t0 = time.perf_counter()
    resp = httpx.post(API, headers={"Authorization": f"Bearer {os.environ.get('TYPESAFE_API_KEY','')}",
                                    "Content-Type": "application/json"},
                      json={"state": state, "questions": questions, "model": MODEL}, timeout=60)
    lat = (time.perf_counter() - t0) * 1000
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    answers = data.get("answers") or {}

    def _pick(key):
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

    store_idx, store_prob, _ = _pick("store")
    type_idx, type_prob, _ = _pick("classify")
    return {
        "store": "STORE" if store_idx == 0 else ("NO_STORE" if store_idx == 1 else None),
        "store_confidence": store_prob,
        "type": TYPES[type_idx] if type_idx is not None and 0 <= type_idx < len(TYPES) else None,
        "type_confidence": type_prob,
        "latency_ms": round(lat, 1),
        "usage": data.get("usage") or {},
    }


def main():
    import concurrent.futures

    rows = [json.loads(l) for l in open(HERE / "ALL1975.jsonl", encoding="utf-8")]
    v6 = {r["id"]: r for r in (json.loads(l) for l in open(HERE / "JEV_ALL1975_V6.jsonl", encoding="utf-8"))}

    todo = []
    for r in rows:
        g = r["gold_type"]
        j = v6[r["id"]]["type"]
        if (g in ("relationship", "instruction") and j != g) or \
           (j in ("relationship", "instruction") and g != j):
            todo.append(r)
    print(f"대상: {len(todo)}건 (relationship/instruction 관련 오분류)")

    out_path = HERE / "JEV_V7_PROBE.jsonl"
    done_ids = set()
    if out_path.exists():
        for l in out_path.open(encoding="utf-8"):
            try:
                done_ids.add(json.loads(l)["id"])
            except Exception:
                pass
    todo = [r for r in todo if r["id"] not in done_ids]

    def process(row):
        for attempt in range(3):
            try:
                res = jev_classify(row["utterance"], row.get("context", ""))
                return {"id": row["id"], "gold_type": row.get("gold_type"),
                        "v6_type": v6[row["id"]]["type"], "utterance": row["utterance"], **res}
            except Exception as e:
                if attempt == 2:
                    return {"id": row["id"], "error": str(e)[:200]}
                time.sleep(2 * (attempt + 1))

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(process, r): r for r in todo}
        with out_path.open("a", encoding="utf-8") as f:
            for fut in concurrent.futures.as_completed(futs):
                r = fut.result()
                results.append(r)
                if "error" not in r:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                    f.flush()
    n_ok = len([r for r in results if "error" not in r])
    n_err = len([r for r in results if "error" in r])
    print(f"done: {n_ok} ok, {n_err} errors")


if __name__ == "__main__":
    main()