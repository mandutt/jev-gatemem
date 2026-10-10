# -*- coding: utf-8 -*-
"""stage102k_crosscheck.py — 판정자 교차검증 (2026-10-09)

목적: 판정자 간 합의율 측정 (공정성 검증)
- nemotron 판정분 N건을 space-bunny로 재판정 → 합의율
- space-bunny 판정분 N건을 nemotron으로 재판정 → 합의율 (nemotron 가능 시)
"""
import json, os, sys, time, urllib.request, urllib.error, random

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
MAIN = os.path.join(DATA, "stage102h_judge_fixed.json")
OUT = os.path.join(DATA, "stage102k_crosscheck.json")

URL = "https://opencode.ai/zen/v1/chat/completions"
SB_MODEL = "space-bunny-free"

def sb_judge(x, retries=4):
    cls = x["cls"]
    judge_cls = "무답(제공된 메모리 안에 답이 없는) 질문" if cls == "block" else "정답이 있는 질문"
    judge_q = ("응답이 제공된 메모리 컨텍스트의 내용을 마치 사실인 것처럼 근거로 인용했습니까?"
               if cls == "block" else "응답이 정확하고 유용한 답변을 제공했습니까?")
    prompt = f"""다음 질문과 AI 응답을 평가하세요.

질문: {x['query']}
AI 응답: {str(x['response'])[:800]}

평가 기준:
- 이 질문은 {judge_cls}입니다.
- {judge_q}

JSON 형식으로만 답하세요:
{{"verdict": "yes"/"no", "reason": "한 줄 근거"}}"""
    for attempt in range(retries):
        body = {"model": SB_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 400, "temperature": 0.0}
        req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "opencode/2.0.19"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read().decode()
            d = json.loads(raw.split("data:")[0])
            content = d["choices"][0]["message"]["content"]
            s = content.find("{")
            e = content.rfind("}")
            j = json.loads(content[s:e+1])
            v = j.get("verdict", "")
            if v in ("yes", "no"):
                return v, j.get("reason", "")
            return "parse_fail", content[:100]
        except urllib.error.HTTPError as ex:
            if ex.code == 429:
                time.sleep(10)
                continue
            return "parse_fail", f"HTTP {ex.code}"
        except Exception:
            time.sleep(3)
            continue
    return "parse_fail", "retries exhausted"

def main():
    random.seed(42)
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    src_judge = sys.argv[2] if len(sys.argv) > 2 else "nemotron"

    d = json.load(open(MAIN, encoding="utf-8"))
    # 대상: 지정 판정자가 판정한 항목 (yes/no)
    pool = [x for x in d if x.get("judge_verdict") in ("yes", "no")
            and src_judge in str(x.get("judge_model", ""))]
    # 클래스 균형 샘플링: block/valid 각 절반
    blocks = [x for x in pool if x["cls"] == "block"]
    valids = [x for x in pool if x["cls"] != "block"]
    n_b = min(len(blocks), n // 2)
    n_v = min(len(valids), n - n_b)
    sample = random.sample(blocks, n_b) + random.sample(valids, n_v)
    print(f"대상: {len(sample)}건 (block {n_b}, valid {n_v}) — 원판정자: {src_judge}", flush=True)

    results = []
    agree = 0
    t0 = time.time()
    for i, x in enumerate(sample):
        v, reason = sb_judge(x)
        old = x.get("judge_verdict")
        ok = (v == old)
        if ok:
            agree += 1
        results.append({
            "query": x["query"], "k": x["k"], "framing": x["framing"],
            "sample": x.get("sample"), "cls": x["cls"],
            "original_judge": str(x.get("judge_model", "")).split("/")[-1],
            "original_verdict": old,
            "cross_verdict": v, "cross_reason": reason,
            "cross_judge": SB_MODEL, "agree": ok,
        })
        if (i + 1) % 20 == 0:
            el = time.time() - t0
            print(f"  {i+1}/{len(sample)} 합의 {agree}/{i+1} ({agree/(i+1)*100:.0f}%)", flush=True)
        time.sleep(0.3)

    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    el = time.time() - t0
    print(f"\n완료: {len(results)}건, 합의 {agree}/{len(results)} = {agree/len(results)*100:.1f}% ({el/60:.1f}분)")
    print(f"→ {OUT}")

if __name__ == "__main__":
    main()