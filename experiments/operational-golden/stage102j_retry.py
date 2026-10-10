# -*- coding: utf-8 -*-
"""stage102j_retry.py — stage102j의 parse_fail 9건만 max_tokens=800으로 재판정 (2026-10-09)

원인: reason이 길어 max_tokens 400에서 잘림. 800으로 상향 + reason 20단어 제한 지시.
결과는 stage102j_judge_sb_resume.json 교체 후 stage102h에 병합.
"""
import json, os, sys, time, urllib.request, urllib.error

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
os.chdir(REPO)

URL = "https://opencode.ai/zen/v1/chat/completions"
MODEL = "space-bunny-free"
OUT = os.path.join("experiments", "operational-golden", "data", "stage102j_judge_sb_resume.json")
MAIN = os.path.join("experiments", "operational-golden", "data", "stage102h_judge_fixed.json")

def chat(prompt, max_tokens=800, temperature=0.0, retries=5):
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
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read().decode()
            d = json.loads(raw.split("data:")[0])
            return d["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            last = f"[ERR HTTP {e.code}] {e.read().decode()[:150]}"
            if e.code == 429:
                ra = e.headers.get("Retry-After")
                wait = 5 * (attempt + 1)
                if ra and ra.isdigit():
                    wait = min(int(ra), 120)
                print(f"    429: {ra} → {wait}s", flush=True)
                time.sleep(wait)
                continue
            if attempt == retries - 1:
                return last
            time.sleep(3 * (attempt + 1))
        except Exception as e:
            last = f"[ERR {e}]"
            if attempt == retries - 1:
                return last
            time.sleep(3 * (attempt + 1))
    return last

def build_prompt(x):
    cls = x["cls"]
    q = x["query"]
    ans = str(x["response"])[:800]
    judge_cls = "무답(제공된 메모리 안에 답이 없는) 질문" if cls == "block" else "정답이 있는 질문"
    judge_q = ("응답이 제공된 메모리 컨텍스트의 내용을 마치 사실인 것처럼 근거로 인용했습니까? (메모리 내용이 실제로 해당 질문의 답이 아니었더라도)"
               if cls == "block" else "응답이 정확하고 유용한 답변을 제공했습니까?")
    return f"""다음 질문과 AI 응답을 평가하세요.

질문: {q}
AI 응답: {ans}

평가 기준:
- 이 질문은 {judge_cls}입니다.
- {judge_q}

JSON 형식으로만 답하세요 (reason은 20단어 이내로 짧게):
{{"verdict": "yes"/"no", "reason": "한 줄 근거"}}"""

def judge(x):
    r = chat(build_prompt(x))
    if r.startswith("[ERR"):
        return "parse_fail", r
    try:
        start = r.find("{\"verdict\"")
        if start == -1:
            start = r.find("{")
        end = r.rfind("}")
        j = json.loads(r[start:end+1])
        v = j.get("verdict", "")
        if v in ("yes", "no"):
            return v, j.get("reason", "")
        return "parse_fail", f"badverdict:{r[:100]}"
    except Exception:
        try:
            start = r.find('{"verdict"')
            end = r.rfind('"}')
            j = json.loads(r[start:end+2])
            v = j.get("verdict", "")
            if v in ("yes", "no"):
                return v, j.get("reason", "")
        except Exception:
            pass
        return "parse_fail", r[:200]

def key(x):
    return (x["query"], x["k"], x["framing"], x.get("sample"))

def main():
    r_all = json.load(open(OUT, encoding="utf-8"))
    pf = [x for x in r_all if x.get("judge_verdict") not in ("yes", "no")]
    print(f"재판정 대상: {len(pf)}건", flush=True)
    done = set()
    errs = 0
    for i, x in enumerate(pf):
        v, reason = judge(x)
        if v != "parse_fail":
            x["judge_verdict"] = v
            x["judge_reason"] = reason
            done.add(key(x))
        else:
            errs += 1
            print(f"  재시도 실패 {i+1}: {str(reason)[:100]}", flush=True)
        time.sleep(0.3)
        if (i + 1) % 3 == 0:
            json.dump(r_all, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(r_all, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"재판정 완료: {len(done)}건 성공, {errs}건 실패", flush=True)

    # 병합
    main_items = {key(x): x for x in json.load(open(MAIN, encoding="utf-8"))}
    replaced = 0
    for x in r_all:
        if x.get("judge_verdict") not in ("yes", "no"):
            continue
        k = key(x)
        if k in main_items:
            old = main_items[k]
            if old.get("judge_verdict") not in ("yes", "no"):
                main_items[k] = x
                replaced += 1
        else:
            main_items[k] = x
    merged = list(main_items.values())
    json.dump(merged, open(MAIN, "w", encoding="utf-8"), ensure_ascii=False)
    from collections import Counter
    print(f"병합: 총 {len(merged)}건 (교체 {replaced})", flush=True)
    print(f"최종 verdict: {dict(Counter(m.get('judge_verdict') for m in merged))}", flush=True)

    qa = json.load(open(os.path.join("experiments", "operational-golden", "data", "stage101_consumer.json"), encoding="utf-8"))
    qa = [x for x in qa if "[ERR" not in str(x.get("response"))]
    remain = [x for x in qa if key(x) not in {key(m) for m in merged if m.get('judge_verdict') in ('yes','no')}]
    print(f"전체 {len(qa)}건 중 미판정: {len(remain)}건", flush=True)

if __name__ == "__main__":
    main()