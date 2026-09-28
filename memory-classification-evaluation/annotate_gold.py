"""Gold annotation via LLM (trusted labeling procedure).

Two-stage reasoning is forced in the prompt:
  Stage 1: conversational function / dialog act
  Stage 2: long-term memory value -> MemoryType (or NO_STORE)

The prompt explicitly forbids grammar-based judgments ("ends with ~줘 so ...").
Output is JSONL with fields: utterance, context, dialog_act, should_store,
gold_type, secondary_type, confidence, reason, ambiguity.

Usage:
  python annotate_gold.py <input.jsonl> <output.jsonl> <model> [--limit N]
"""
import json
import sys
import io
import time
import urllib.request
import urllib.error
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:20128/v1"
# Use the local router; no auth header needed for localhost (matches Hermes config)

SYSTEM_PROMPT = """당신은 한국어 발화 메모리 분류 Gold Annotation 레이블러입니다.

## 판단 원칙 (절대 규칙)
1. "무슨 문법으로 끝났는가"가 아니라 "화자가 이 발화를 통해 장기적으로 어떤 정보를 전달하는가"로 판단한다.
2. 종결어미(~줘, ~자, ~세요, ~했어 등)는 판단 근거가 될 수 없다. 같은 어미라도 문맥에 따라 다른 유형이 될 수 있다.
3. 일회성 대화 조각(수긍, 진행 지시, 안부, 잡담)은 저장 가치가 없다 → NO_STORE.
4. 반복 적용할 규칙, 지속 선호, 확정된 결정, 과거 교훈은 저장 가치가 있다.
5. 원본 데이터셋의 라벨을 복사하지 않는다. 오직 발화 내용의 의미와 장기 기억 가치만으로 판단한다.

## 두 단계 사고 (출력에 반드시 포함)
- Stage 1 (conversational function): 이 발화의 대화 기능이 무엇인가? (예: ACKNOWLEDGEMENT, REQUEST, PREFERENCE_STATEMENT, FAILURE_REPORT, FACT_STATEMENT, DECISION_STATEMENT, QUESTION, CONSTRAINT, ...)
- Stage 2 (memory value): 장기 메모리로 저장할 가치가 있는가? 있다면 어떤 유형인가?

## MemoryType 정의 (13개)
- fact: 객관적·검증 가능한 사실 (안정적)
- preference: 지속적인 선호/기호 (항상/주로 ~을 좋아함)
- decision: 확정된 선택 (이걸로 정했다)
- commitment: 약속/기한/의무
- goal: 목표/지표
- event: 과거에 발생한 특정 사건 (회의, 배포, 장애)
- instruction: 반복 적용할 행동 규칙/지침 (앞으로 ~해라)
- relationship: 사람/조직 관계
- context: 현재 진행 상황 (일시적)
- learning: 교훈/방법 습득 (이렇게 하면 안 되더라)
- observation: 반복되는 현상/패턴 (자꾸 ~가 반복돼)
- error: 오류/실패 보고
- artifact: 파일/문서/코드 위치 참조
- NO_STORE: (평가 전용) 장기 메모리로 저장할 의미가 없는 발화

## 경계 판단 지침
- 일회성 명령("좋아 진행해줘", "이것도 확인해줘") = NO_STORE (요청 기능이지만 저장 가치 없음)
- 장기 규칙("앞으로 항상 표로 정리해줘") = instruction
- 선호("표로 보는 게 편해", "나는 간결한 설명을 좋아해") = preference
- 확정("Rust로 가기로 했어", "그 방법으로 확정하자") = decision
- 오류 보고("오류가 발생했어") = error / 단순 반복 현상("자꾸 느려지는 것 같아") = observation / "이렇게 하면 안 된다는 걸 알았어" = learning
- "지금 작업 중이야" = context (일시적) 또는 NO_STORE
- 질문 = 문맥상 저장 가치 판단 (보통 NO_STORE)

## 출력 형식
반드시 아래 JSON 스키마로만 답하라 (마크다운 코드블록 금지, 순수 JSON만):
{
  "dialog_act": "...",
  "should_store": true/false,
  "gold_type": "preference | decision | ... | NO_STORE",
  "secondary_type": null 또는 "유형명",
  "confidence": 0.0~1.0,
  "reason": "한국어로 1~2문장 판단 근거 (Stage1→Stage2 흐름 포함)",
  "ambiguity": true/false
}"""

# This router path (tokenharbor/qwen3.8-flash:free) IGNORES system prompts and
# emits its own NLU schema; instructions must live in the USER message instead.
USER_TEMPLATE = """너는 한국어 발화 메모리 분류 gold 레이블러다.

규칙 (반드시 준수):
- 문법/종결어미가 아니라 의미와 장기 기억 가치로 판단한다.
- 일회성 수긍/진행 지시/잡담/질문은 NO_STORE (저장 가치 없음).
- 반복 적용 규칙(앞으로 ~해라)은 instruction, 지속 선호(~이 편해/~좋아해)는 preference,
  확정(~하기로 했어/~로 가자)은 decision, 오류 보고(오류 발생/실패)는 error,
  교훈(~라는 걸 알았어)은 learning, 반복 현상(~자꾸~)은 observation,
  객관적 사실은 fact, 과거 사건은 event, 일시적 상황(지금 ~ 중)은 context,
  약속/기한은 commitment, 목표는 goal, 관계는 relationship, 파일/자료 위치는 artifact.

아래 JSON 스키마로만 답하라 (설명 없이 순수 JSON만):
{{"dialog_act": "대화 기능 (ACKNOWLEDGEMENT/REQUEST/PREFERENCE_STATEMENT/FAILURE_REPORT/... 등)",
  "should_store": true 또는 false,
  "gold_type": "NO_STORE 또는 fact|preference|decision|commitment|goal|event|instruction|relationship|context|learning|observation|error|artifact",
  "secondary_type": null 또는 위 유형 중 하나,
  "confidence": 0.0~1.0,
  "reason": "한국어로 1~2문장 판단 근거",
  "ambiguity": true 또는 false}}

발화: {utterance}"""


def call_llm(model: str, utterance: str) -> dict:
    body = {
        "model": model,
        "messages": [
            # NOTE: this router path ignores system prompts (emits own NLU
            # schema); all instructions must be in the user message.
            {"role": "user", "content": USER_TEMPLATE.format(utterance=utterance)},
        ],
        "temperature": 0.0,
        "max_tokens": 700,
        # suppress hidden reasoning where the router honors it (speeds up batch)
        "reasoning_effort": "none",
    }
    req = urllib.request.Request(
        f"{BASE}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        raw = resp.read().decode()
    # Router paths append an SSE trailer ("data: [DONE]") after the JSON body.
    # Parse the leading JSON object and ignore everything after it.
    dec = json.JSONDecoder()
    try:
        data, _ = dec.raw_decode(raw)
    except json.JSONDecodeError:
        # fallback: strip known trailer then retry
        raw = raw.split("data: [DONE]")[0].strip()
        data, _ = dec.raw_decode(raw)
    text = data["choices"][0]["message"]["content"]
    # extract first {...} block (skip thinking if present)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON in response: {text[:200]}")
    parsed = json.loads(text[start : end + 1])
    # tolerate extra keys; keep only the ones we care about
    wanted = ["dialog_act", "should_store", "gold_type", "secondary_type",
              "confidence", "reason", "ambiguity"]
    return {k: parsed.get(k) for k in wanted}


def main():
    inp = Path(sys.argv[1])
    outp = Path(sys.argv[2])
    model = sys.argv[3] if len(sys.argv) > 3 else "gc/gemini-3.5-flash-lite"
    limit = int(sys.argv[4]) if len(sys.argv) > 4 else None
    workers = int(sys.argv[5]) if len(sys.argv) > 5 else 4

    rows = [json.loads(l) for l in open(inp, encoding="utf-8")]
    if limit:
        rows = rows[:limit]

    # resume support
    done_ids = set()
    if outp.exists():
        for l in open(outp, encoding="utf-8"):
            try:
                done_ids.add(json.loads(l)["id"])
            except Exception:
                pass

    todo = [r for r in rows if r["id"] not in done_ids]
    print(f"resume: {len(done_ids)} done, {len(todo)} todo, workers={workers}")

    import concurrent.futures

    def process(row):
        for attempt in range(3):
            try:
                ann = call_llm(model, row["utterance"])
                return {
                    "id": row["id"],
                    "dataset": row.get("dataset"),
                    "utterance": row["utterance"],
                    "context": row.get("context", ""),
                    "ending_class": row.get("ending_class"),
                    **ann,
                }
            except Exception as e:
                if attempt == 2:
                    return {"id": row["id"], "error": str(e)}
                time.sleep(2)

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(process, r): r for r in todo}
        done = 0
        with open(outp, "a", encoding="utf-8") as f:
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
        print("sample errors:")
        for r in [x for x in results if "error" in x][:5]:
            print(" ", r["id"][:50], "->", r["error"][:80])


if __name__ == "__main__":
    main()