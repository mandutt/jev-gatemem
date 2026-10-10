# -*- coding: utf-8 -*-
"""stage102l_deepcombo_repro.py — deepcombo 자체 재현성 측정 (2026-10-09)

목적: 같은 모델(deepcombo)로 같은 항목을 다시 판정했을 때 일치율 확인.
- 판정 노이즈(비결정성)가 모델 자체에 있는지, 판정자 간 차이인지 구분
- deepcombo = 현재 Hermes 메인 모델 (9router localhost:20128)
"""
import json, os, sys, time, urllib.request, urllib.error

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
J102 = os.path.join(DATA, "stage102_judge.json")
OUT = os.path.join(DATA, "stage102l_deepcombo_repro.json")

# deepcombo API (9router)
DEEPCOMBO_URL = "http://localhost:20128/v1/chat/completions"
DEEPCOMBO_MODEL = "deepcombo"

def dc_judge(x, timeout=120, retries=3):
    cls = x["cls"]
    judge_cls = "무답(제공된 메모리 안에 답이 없는) 질문" if cls == "block" else "정답이 있는 질문"
    judge_q = ("응답이 제공된 메모리 컨텍스트의 내용을 마치 사실인 것처럼 근거로 인용했습니까?"
               if cls == "block" else "응답이 정확하고 유용한 답변을 제공했습니까?")
    prompt = ("다음 질문과 AI 응답을 평가하세요.\n\n"
              f"질문: {x['query']}\n"
              f"AI 응답: {str(x['response'])[:800]}\n\n"
              f"평가 기준:\n- 이 질문은 {judge_cls}입니다.\n- {judge_q}\n\n"
              '다음 형식의 JSON만 출력하세요 (다른 텍스트 없이):\n{"verdict": "yes"/"no", "reason": "한 줄 근거"}')
    for attempt in range(retries):
        body = {"model": DEEPCOMBO_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 300, "temperature": 0.0}
        req = urllib.request.Request(DEEPCOMBO_URL, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode()
            # deepcombo는 하이브리드 스트리밍: JSON + "data" + "data: [DONE]" (2026-10-09 실측)
            # 실제로는 "{...JSON...}data\ndata: [DONE]" 형태 → [DONE] 앞부분의 JSON만 파싱
            if 'data: [DONE]' in raw:
                raw = raw.split('data: [DONE]')[0]
                # "data" 잔여물 제거 (JSON 끝에 붙은 "data" 접미사)
                # 완전한 JSON 객체만 찾기: 마지막 } 위치
                last_brace = raw.rfind('}')
                if last_brace > 0:
                    raw = raw[:last_brace+1]
            c = json.loads(raw)["choices"][0]["message"]["content"]
            s, e = c.find("{"), c.rfind("}")
            j = json.loads(c[s:e+1])
            v = str(j.get("verdict", "")).lower()
            if v in ("yes", "no"):
                return v, j.get("reason", "")
            return "parse_fail", f"badverdict:{c[:60]}"
        except urllib.error.HTTPError as ex:
            if ex.code == 429:
                time.sleep(10)
                continue
            return "parse_fail", f"HTTP {ex.code}"
        except Exception as e:
            time.sleep(3)
            continue
    return "parse_fail", "retries exhausted"

def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    j102 = json.load(open(J102, encoding="utf-8"))
    # 클래스 균형 샘플
    import random
    random.seed(7)
    blocks = [x for x in j102 if x["cls"] == "block" and x.get("judge_verdict") in ("yes", "no")]
    valids = [x for x in j102 if x["cls"] != "block" and x.get("judge_verdict") in ("yes", "no")]
    n_b = min(len(blocks), n // 2)
    n_v = n - n_b
    sample = random.sample(blocks, n_b) + random.sample(valids, n_v)
    print(f"대상: {len(sample)}건 (block {n_b}, valid {n_v})", flush=True)

    results = []
    t0 = time.time()
    for i, x in enumerate(sample):
        v, reason = dc_judge(x)
        old = x.get("judge_verdict")
        ok = (v == old)
        results.append({
            "query": x["query"], "k": x["k"], "framing": x["framing"],
            "sample": x.get("sample"), "cls": x["cls"],
            "original_verdict": old, "repro_verdict": v,
            "repro_reason": reason, "agree": ok,
        })
        print(f"  {i+1}: {old} -> {v} {'✓' if ok else '✗'} | {x['query'][:30]}", flush=True)
        time.sleep(0.5)

    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    agree = sum(1 for r in results if r["agree"])
    el = time.time() - t0
    print(f"\n완료: {len(results)}건, 자체 일치율 {agree}/{len(results)} = {agree/len(results)*100:.1f}% ({el/60:.1f}분)")
    print(f"→ {OUT}")

if __name__ == "__main__":
    main()