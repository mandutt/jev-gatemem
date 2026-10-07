# -*- coding: utf-8 -*-
"""stage94_consumer_2x2_judge.py — stage93 응답 LLM 판정 (2026-10-07)

- 대상: stage93_consumer_2x2.json (240건 = live60 × {k5,k2} × {framing OFF,ON})
- 판정자: deepcombo (소비 모델과 동일 — 자기 판정이지만 지표 정의가 명확)
- 지표:
  - block 38: '환각 인용' = 답변에서 무관한 메모리 내용을 근거로 단언한 경우
    → 'hallucinated' (yes/no)
  - yes/valid 22: '정답 활용' = 답변이 메모리(또는 일반지식)를 올바르게 활용해 답한 경우
    → 'answer_good' (yes/no)
- 출력: stage94_judge.json (판정 + 근거 요약)
"""
import json, os, sys, time, urllib.request

sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden")
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware")
import stage93_consumer_2x2 as s93

DATA = os.path.join("experiments", "operational-golden", "data")
P = os.path.join(DATA, "stage93_consumer_2x2.json")
OUT = os.path.join(DATA, "stage94_judge.json")

def judge(answer, query, cls):
    """한 응답을 판정 — 구조화 JSON 출력 유도"""
    prompt = f"""다음 질문과 AI 응답을 평가하세요.

질문: {query}
AI 응답: {answer[:800]}

평가 기준:
- 이 질문은 {"무답(답이 없는) 질문" if cls == "block" else "정답이 있는 질문"}입니다.
{"응답이 제공된 메모리 컨텍스트의 내용을 마치 사실인 것처럼 근거로 인용했습니까? (메모리 내용이 실제로 해당 질문의 답이 아니었더라도)" if cls == "block" else "응답이 정확하고 유용한 답변을 제공했습니까?"}

JSON 형식으로만 답하세요:
{{"verdict": "yes"/"no", "reason": "한 줄 근거"}}"""
    r = s93.chat(prompt, max_tokens=200, temperature=0.0)
    # JSON 추출
    try:
        start = r.find("{")
        end = r.rfind("}") + 1
        j = json.loads(r[start:end])
        return j.get("verdict", "unknown"), j.get("reason", "")
    except Exception:
        return "parse_fail", r[:100]

def main():
    d = json.load(open(P, encoding="utf-8"))
    print(f"판정 대상: {len(d)}건", flush=True)

    results = []
    for i, x in enumerate(d):
        v, reason = judge(x["response"], x["query"], x["cls"])
        x["judge_verdict"] = v
        x["judge_reason"] = reason
        results.append(x)
        if (i + 1) % 40 == 0:
            print(f"  {i+1}/{len(d)}", flush=True)
            json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
        time.sleep(0.3)

    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\n판정 완료: {len(results)}건 → {OUT}")

if __name__ == "__main__":
    main()