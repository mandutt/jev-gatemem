"""P11 실험 — store 질문에 type 분류 결과 주입 (store 오분류 302건 개선 여부).

가설: 302건 오분류 중 266건(88%)이 type은 저장타입인데 store만 NO_STORE.
store 결정 전에 type을 알고 있으면 store가 더 정확해질 것.

- P11-a: type을 먼저 분류 → store 질문 criteria에 '[type=X]' 주입 (1호출로 하되
         System One 멀티질문 순서가 유지되는지 불확실하므로 상태 기반 재질의)
- P11-b: type 단독 호출 → store 단독 호출 (2회, 가장 명확)

입력: 오분류 302건 jsonl (id/utterance/gold_type)
출력: P11_A.jsonl / P11_B.jsonl
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

STORE_INSTRUCTIONS_W_TYPE = (
    "Does this utterance have long-term memory value worth storing? "
    "Pick exactly one.\n"
    "NO_STORE examples: '좋아 진행해줘' / '알겠습니다' / '그걸로 가자' / "
    "'감사합니다' / '네 그럼요' / '안녕하세요' / '서커스야' / '좋아, 스테이지 도어 좋네'\n"
    "STORE examples: '앞으로 답변은 항상 표로 정리해줘' / '내일까지 보고서 제출해야 해' / "
    "'나는 간결한 답변을 좋아해' / '오류가 발생했어, 빌드가 실패했어'\n"
    "The utterance has ALREADY been classified as TYPE: {type}. "
    "If TYPE is a real memory type (fact, preference, decision, commitment, "
    "goal, event, instruction, relationship, context, learning, observation, "
    "error, artifact), it has lasting memory value by definition — STORE. "
    "Only if TYPE is NO_STORE should you consider NO_STORE: one-off remarks, "
    "acknowledgments, trivial requests, small talk. Pick exactly one."
)


def _post(state, questions, timeout=60.0):
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
    lat = (time.perf_counter() - t0) * 1000
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json(), lat


def _pick(answers, key):
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


def classify_type(utterance, context=""):
    state = {
        "utterance": utterance,
        "candidates": [{"id": f"t{i}", "label": t} for i, t in enumerate(TYPES)],
    }
    if context:
        state["context"] = context
    data, lat = _post(state, {
        "classify": {
            "type": "choice",
            "instructions": CLASSIFY_INSTRUCTIONS,
            "criteria": {f"c{i}": t for i, t in enumerate(TYPES)},
        },
    })
    idx, prob = _pick(data.get("answers") or {}, "classify")
    return TYPES[idx] if idx is not None and 0 <= idx < len(TYPES) else None, prob, lat


def store_with_type(utterance, mtype, context=""):
    """store 질문에 미리 분류한 type 주입."""
    state = {
        "utterance": utterance,
        "candidates": [],
    }
    if context:
        state["context"] = context
    data, lat = _post(state, {
        "store": {
            "type": "choice",
            "instructions": STORE_INSTRUCTIONS_W_TYPE.format(type=mtype or "unknown"),
            "criteria": {"c0": "STORE", "c1": "NO_STORE"},
        },
    })
    idx, prob = _pick(data.get("answers") or {}, "store")
    return ("STORE" if idx == 0 else ("NO_STORE" if idx == 1 else None)), prob, lat


def store_alone(utterance, context=""):
    """P11-b 대조: store 단독 (type 정보 없음) — 원래 1호출에서 store가 얼마나 틀리는지."""
    state = {"utterance": utterance}
    if context:
        state["context"] = context
    data, lat = _post(state, {
        "store": {
            "type": "choice",
            "instructions": STORE_INSTRUCTIONS,
            "criteria": {"c0": "STORE", "c1": "NO_STORE"},
        },
    })
    idx, prob = _pick(data.get("answers") or {}, "store")
    return ("STORE" if idx == 0 else ("NO_STORE" if idx == 1 else None)), prob, lat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output_a")   # P11-a: type 주입
    ap.add_argument("output_b")   # P11-b: store 단독
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    if not os.environ.get("TYPESAFE_API_KEY"):
        print("!! TYPESAFE_API_KEY 미설정")
        sys.exit(2)

    rows = [json.loads(l) for l in open(args.input, encoding="utf-8")]
    if args.limit:
        rows = rows[: args.limit]

    done_a = set()
    done_b = set()
    if Path(args.output_a).exists():
        for l in open(args.output_a, encoding="utf-8"):
            try:
                done_a.add(json.loads(l)["id"])
            except Exception:
                pass
    if Path(args.output_b).exists():
        for l in open(args.output_b, encoding="utf-8"):
            try:
                done_b.add(json.loads(l)["id"])
            except Exception:
                pass
    todo = [r for r in rows if r["id"] not in done_a or r["id"] not in done_b]
    print(f"resume: A {len(done_a)} B {len(done_b)} done, todo {len(todo)}")

    def process(row):
        out = {"id": row["id"], "utterance": row["utterance"],
               "gold_type": row.get("gold_type"), "gold_should_store": row.get("gold_should_store")}
        errors = []
        # 1) type 분류
        for attempt in range(3):
            try:
                mtype, tprob, tlat = classify_type(row["utterance"], row.get("context", ""))
                out["type"] = mtype
                out["type_confidence"] = tprob
                out["type_latency_ms"] = round(tlat, 1)
                break
            except Exception as e:
                if attempt == 2:
                    errors.append(f"type: {e}")
                time.sleep(2 * (attempt + 1))
        else:
            out["type"] = None

        # 2) store with type (P11-a)
        if out.get("type") is not None:
            for attempt in range(3):
                try:
                    s, sp, slat = store_with_type(row["utterance"], out["type"], row.get("context", ""))
                    out["store_a"] = s
                    out["store_a_confidence"] = sp
                    out["store_a_latency_ms"] = round(slat, 1)
                    break
                except Exception as e:
                    if attempt == 2:
                        errors.append(f"store_a: {e}")
                    time.sleep(2 * (attempt + 1))
        # 3) store alone (P11-b)
        for attempt in range(3):
            try:
                s, sp, slat = store_alone(row["utterance"], row.get("context", ""))
                out["store_b"] = s
                out["store_b_confidence"] = sp
                out["store_b_latency_ms"] = round(slat, 1)
                break
            except Exception as e:
                if attempt == 2:
                    errors.append(f"store_b: {e}")
                time.sleep(2 * (attempt + 1))
        if errors:
            out["error"] = "; ".join(errors)[:200]
        return out

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(process, r): r for r in todo}
        done = 0
        with open(args.output_a, "a", encoding="utf-8") as fa, open(args.output_b, "a", encoding="utf-8") as fb:
            for fut in concurrent.futures.as_completed(futures):
                r = fut.result()
                results.append(r)
                if "error" not in r:
                    fa.write(json.dumps({k: v for k, v in r.items() if k in (
                        "id", "utterance", "gold_type", "gold_should_store", "type",
                        "type_confidence", "type_latency_ms", "store_a", "store_a_confidence")},
                        ensure_ascii=False) + "\n")
                    fb.write(json.dumps({k: v for k, v in r.items() if k in (
                        "id", "utterance", "gold_type", "gold_should_store", "type",
                        "store_b", "store_b_confidence")}, ensure_ascii=False) + "\n")
                    fa.flush()
                    fb.flush()
                done += 1
                if done % 30 == 0:
                    print(f"  {done}/{len(todo)} done", flush=True)
    n_ok = len([r for r in results if "error" not in r])
    n_err = len([r for r in results if "error" in r])
    print(f"done: {n_ok} ok, {n_err} errors")
    if n_err:
        for r in [x for x in results if "error" in x][:5]:
            print(" ", r["id"][:50], "->", r["error"][:100])


if __name__ == "__main__":
    main()