# -*- coding: utf-8 -*-
"""stage102b_judge_opencode.py — space-bunny-free 판정 (2026-10-08)

opencode zen 무료 모델로 판정:
- 엔드포인트: https://opencode.ai/zen/v1/chat/completions
- 모델: space-bunny-free (zero-retention, Hermes와 독립 — 동시 실행 가능)
- 인증: User-Agent: opencode/2.0.19 (키 불필요)
- tools 없는 단순 chat (9router PR#4165 403 대상 아님)

용도:
  --all     : 전체 1,074건 판정
  --cross N : 처음 N건을 deepcombo 기존 판정과 교차 검증 (판정자 합의율)
"""
import json, os, sys, time, urllib.request, argparse

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
os.chdir(REPO)

URL = "https://opencode.ai/zen/v1/chat/completions"
MODEL = "space-bunny-free"

def chat(prompt, max_tokens=400, temperature=0.0, retries=5):
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "당신은 정확한 평가자입니다. JSON으로만 답합니다."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "opencode/2.0.19"}, method="POST")
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                raw = r.read().decode()
            d = json.loads(raw.split("data:")[0])
            return d["choices"][0]["message"]["content"]
        except Exception as e:
            if attempt == retries - 1:
                return f"[ERR {e}]"
            time.sleep(3 * (attempt + 1))

def judge(answer, query, cls):
    prompt = f"""다음 질문과 AI 응답을 평가하세요.

질문: {query}
AI 응답: {answer[:800]}

평가 기준:
- 이 질문은 {"무답(제공된 메모리 안에 답이 없는) 질문" if cls == "block" else "정답이 있는 질문"}입니다.
{"응답이 제공된 메모리 컨텍스트의 내용을 마치 사실인 것처럼 근거로 인용했습니까? (메모리 내용이 실제로 해당 질문의 답이 아니었더라도)" if cls == "block" else "응답이 정확하고 유용한 답변을 제공했습니까?"}

JSON 형식으로만 답하세요:
{{"verdict": "yes"/"no", "reason": "한 줄 근거"}}"""
    r = chat(prompt)
    # 중첩 JSON 대응: 마지막 완전한 JSON 객체 추출
    try:
        start = r.find("{")
        end = r.rfind("}")
        j = json.loads(r[start:end+1])
        return j.get("verdict", "unknown"), j.get("reason", "")
    except Exception:
        # 중첩 구조: reason 값이 또 JSON이면
        try:
            start = r.find('{"verdict"')
            end = r.rfind('"}')
            j = json.loads(r[start:end+2])
            return j.get("verdict", "unknown"), j.get("reason", "")
        except Exception:
            return "parse_fail", r[:200]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--cross", type=int, default=0)
    args = ap.parse_args()

    QA = os.path.join("experiments", "operational-golden", "data", "stage101_consumer.json")
    JUDGE = os.path.join("experiments", "operational-golden", "data", "stage102_judge.json")
    OUT = os.path.join("experiments", "operational-golden", "data", "stage102b_judge_sb.json")

    d = json.load(open(QA, encoding="utf-8"))
    d = [x for x in d if "[ERR" not in str(x.get("response"))]
    print(f"전체 성공 응답: {len(d)}건")

    if args.cross:
        # 교차 검증: 기존 deepcombo 판정과 비교
        old = json.load(open(JUDGE, encoding="utf-8"))
        old_map = {(x["query"], x["k"], x["framing"], x.get("sample")): x.get("judge_verdict")
                   for x in old}
        targets = [x for x in d if (x["query"], x["k"], x["framing"], x.get("sample")) in old_map][:args.cross]
        print(f"교차 검증 대상: {len(targets)}건 (기존 deepcombo 판정과 비교)")
        results = []
        agree = 0
        for i, x in enumerate(targets):
            v, reason = judge(x["response"], x["query"], x["cls"])
            old_v = old_map[(x["query"], x["k"], x["framing"], x.get("sample"))]
            ok = (v == old_v)
            if ok: agree += 1
            results.append({**x, "judge_verdict": v, "judge_reason": reason,
                            "judge_model": MODEL, "old_verdict": old_v, "agree": ok})
            if (i + 1) % 20 == 0:
                print(f"  {i+1}/{len(targets)}", flush=True)
                json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
            time.sleep(0.2)
        json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"\n교차 합의율: {agree}/{len(targets)} = {agree/len(targets)*100:.1f}%")
        return

    if args.all:
        print(f"전체 판정 시작: {len(d)}건 (model={MODEL})", flush=True)
        results = []
        for i, x in enumerate(d):
            v, reason = judge(x["response"], x["query"], x["cls"])
            x["judge_verdict"] = v
            x["judge_reason"] = reason
            x["judge_model"] = MODEL
            results.append(x)
            if (i + 1) % 100 == 0:
                print(f"  {i+1}/{len(d)}", flush=True)
                json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
            time.sleep(0.2)
        json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"\n완료: {len(results)}건 → {OUT}")
        return

    print("--all 또는 --cross N 사용")

if __name__ == "__main__":
    main()