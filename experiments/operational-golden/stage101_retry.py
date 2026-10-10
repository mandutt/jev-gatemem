# -*- coding: utf-8 -*-
"""stage101_retry.py — stage101 소비 QA 오류 재시도 (2026-10-08)

- [ERR] 응답(503/"Unterminated string")만 재시도
- 5회 재시도 + SSE 파싱 개선 (긴 응답 분할 처리)
- 응답이 길어 잘리는 문제: max_tokens를 늘리고, SSE 청크 누적 파싱
"""
import json, os, sys, time, urllib.request

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
os.chdir(REPO)

URL = "http://localhost:20128/v1/chat/completions"
QA = os.path.join("experiments", "operational-golden", "data", "stage101_consumer.json")

def chat_stable(prompt, temperature=0.2, max_tokens=400, retries=5):
    body = {
        "model": "deepcombo",
        "messages": [
            {"role": "system", "content": "당신은 Hermes 어시스턴트입니다. 한국어로 답변합니다."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read().decode()
            # SSE 파싱 — 모든 data: 청크를 누적 (긴 응답 분할 대응)
            if raw.lstrip().startswith("{"):
                d = json.loads(raw.split("data:")[0])
            else:
                content_parts = []
                for line in raw.splitlines():
                    line = line.strip()
                    if line.startswith("data:") and "[DONE]" not in line:
                        try:
                            chunk = json.loads(line[5:].strip())
                            content_parts.append(chunk["choices"][0]["message"]["content"])
                        except Exception:
                            continue
                if content_parts:
                    return "".join(content_parts)
                raise ValueError("no data line")
            return d["choices"][0]["message"]["content"]
        except Exception as e:
            if attempt == retries - 1:
                return f"[ERR {e}]"
            time.sleep(5 * (attempt + 1))

def rebuild_prompt(x, jev_by_query):
    """원래 프롬프트 재구성 (query·k·framing 기반)."""
    q = x["query"]
    jr = jev_by_query.get(q)
    rows = (jr.get("ordered") or [])[: x["k"]] if jr and x["k"] else []
    from core import j1_engine
    NEW_HEADER = "[참고용 메모리: 아래 내용은 질문과 키워드가 유사하여 검색된 결과입니다. 질문에 대한 직접적이고 명확한 답이 없다면 이 메모리를 무시하고 답변하십시오.]"
    if x["k"] == 0:
        body = "(메모리 없음)"
    else:
        block = j1_engine.format_block(rows, q)
        body = (NEW_HEADER + "\n" + block) if x["framing"] else block
    return f"<retrieved_context>\n{body}\n</retrieved_context>\n\n질문: {q}\n위 메모리를 참고하여 답변하세요."

def main():
    d = json.load(open(QA, encoding="utf-8"))
    jev = json.load(open(os.path.join("experiments", "operational-golden", "data", "stage101_jev_full.json"), encoding="utf-8"))
    jev_by_query = {j["q"]: j for j in jev}

    sys.path.insert(0, REPO)
    from core import j1_engine  # noqa

    errs = [x for x in d if "[ERR" in str(x.get("response"))]
    print(f"재시도 대상: {len(errs)}건", flush=True)
    for i, x in enumerate(errs):
        prompt = rebuild_prompt(x, jev_by_query)
        ans = chat_stable(prompt, temperature=x.get("temp", 0.2))
        x["response"] = ans
        x["retried"] = True
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(errs)}", flush=True)
            json.dump(d, open(QA, "w", encoding="utf-8"), ensure_ascii=False)
        time.sleep(0.5)

    json.dump(d, open(QA, "w", encoding="utf-8"), ensure_ascii=False)
    remain = sum(1 for x in d if "[ERR" in str(x.get("response")))
    print(f"완료: 재시도 {len(errs)}건, 잔여 err {remain}")

if __name__ == "__main__":
    main()