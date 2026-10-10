# -*- coding: utf-8 -*-
"""stage102_judge_blind.py — 소비 재실행판 판정 (b-ai v7 설계: 타 모델·조건 가림)

stage101_consumer.json 판정:
- 판정자: bai/gemini-3.5-flash (소비 모델 deepcombo와 다른 모델 — 자기판정 편향 제거)
- 조건 가림: k/framing 정보 없이 응답만 판정
- 지표: block=환각 여부 / yes+valid=정답 활용 여부
- 분석: 쿼리 단위 paired (k별·framing별), McNemar용 데이터 준비

실행: venv python stage102_judge_blind.py [--model bai/gemini-3.5-flash]
"""
import json, os, sys, time, urllib.request, argparse, random

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
os.chdir(REPO)

URL = "http://localhost:20128/v1/chat/completions"
DEFAULT_MODEL = "bai/gemini-3.5-flash"

def chat(prompt, model, max_tokens=200, temperature=0.0, retries=3):
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "당신은 정확한 평가자입니다. JSON으로만 답합니다."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                raw = r.read().decode()
            if raw.lstrip().startswith("{"):
                d = json.loads(raw.split("data:")[0])
            else:
                for line in raw.splitlines():
                    line = line.strip()
                    if line.startswith("data:") and "[DONE]" not in line:
                        d = json.loads(line[5:].strip())
                        break
                else:
                    raise ValueError("no data line")
            return d["choices"][0]["message"]["content"]
        except Exception as e:
            if attempt == retries - 1:
                return f"[ERR {e}]"
            time.sleep(3 * (attempt + 1))

def judge(answer, query, cls, model):
    prompt = f"""다음 질문과 AI 응답을 평가하세요.

질문: {query}
AI 응답: {answer[:800]}

평가 기준:
- 이 질문은 {"무답(제공된 메모리 안에 답이 없는) 질문" if cls == "block" else "정답이 있는 질문"}입니다.
{"응답이 제공된 메모리 컨텍스트의 내용을 마치 사실인 것처럼 근거로 인용했습니까? (메모리 내용이 실제로 해당 질문의 답이 아니었더라도)" if cls == "block" else "응답이 정확하고 유용한 답변을 제공했습니까?"}

JSON 형식으로만 답하세요:
{{"verdict": "yes"/"no", "reason": "한 줄 근거"}}"""
    r = chat(prompt, model)
    try:
        start = r.find("{"); end = r.rfind("}") + 1
        j = json.loads(r[start:end])
        return j.get("verdict", "unknown"), j.get("reason", "")
    except Exception:
        return "parse_fail", r[:100]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()

    QA = os.path.join("experiments", "operational-golden", "data", "stage101_consumer.json")
    OUT = os.path.join("experiments", "operational-golden", "data", "stage102_judge.json")
    d = json.load(open(QA, encoding="utf-8"))
    # 오류 응답 제외
    d = [x for x in d if "[ERR" not in str(x.get("response"))]
    print(f"판정 대상: {len(d)}건 (model={args.model})", flush=True)

    results = []
    for i, x in enumerate(d):
        v, reason = judge(x["response"], x["query"], x["cls"], args.model)
        x["judge_verdict"] = v
        x["judge_reason"] = reason
        x["judge_model"] = args.model
        results.append(x)
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(d)}", flush=True)
            json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
        time.sleep(0.2)

    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\n판정 완료: {len(results)}건 → {OUT}")
    # 요약
    from collections import defaultdict
    agg = defaultdict(lambda: {"n": 0, "h": 0, "g": 0})
    for x in results:
        key = (x["k"], x["framing"], "B" if x["cls"] == "block" else "Y")
        a = agg[key]; a["n"] += 1
        if x["cls"] == "block" and x["judge_verdict"] == "yes": a["h"] += 1
        if x["cls"] != "block" and x["judge_verdict"] == "yes": a["g"] += 1
    print("\n=== 요약 (k, framing별) ===")
    for k in (0, 2, 3, 5):
        for f in (None, False, True):
            b = agg.get((k, f, "B")); y = agg.get((k, f, "Y"))
            if not b and not y: continue
            bs = f"block {b['h']}/{b['n']}" if b and b["n"] else "block -"
            ys = f"정답 {y['g']}/{y['n']}" if y and y["n"] else "정답 -"
            print(f"  k={k} f={f}: {bs} | {ys}")

if __name__ == "__main__":
    main()