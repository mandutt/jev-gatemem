"""JEV(System One)를 메모리 분류기로 사용하는 분류 실행기.

- 입력 JSONL (GOLD_*_ANN1.jsonl 형식): id, utterance, gold_type
- JEV System One choice에 store(STORE/NO_STORE) + classify(14종)를
  **한 호출**로 질의, probabilities/confidence 보존
- resume 지원: output에 이미 있는 id는 건너뜀
- 503/5xx 재시도 (3회), workers 스레드풀

Usage:
  python jev_classify.py <input.jsonl> <output.jsonl> [--limit N] [--workers W]
"""
import argparse
import concurrent.futures
import io
import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

API = "https://api.typesafe.ai/v1/systemone"
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
    "given criteria, based on meaning and intent, NOT grammar or sentence "
    "ending. NO_STORE means no long-term memory value. Pick exactly one."
)


def jev_classify(utterance: str, timeout: float = 60.0) -> dict:
    """One JEV call: returns {store, store_prob, type, type_prob, probs, latency_ms, usage}."""
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
                res = jev_classify(row["utterance"])
                return {
                    "id": row["id"],
                    "dataset": row.get("dataset"),
                    "utterance": row["utterance"],
                    "ending_class": row.get("ending_class"),
                    "gold_type": row.get("gold_type"),
                    "gold_should_store": row.get("should_store"),
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