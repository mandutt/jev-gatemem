# -*- coding: utf-8 -*-
"""stage102k_judge_sb_all.py — space-bunny 단일 판정자 전체 재판정 (2026-10-09)

배경: stage102h의 1,074건 판정이 nemotron/space-bunny/fledge 혼합으로 진행됨.
판정자별 block yes율 22~86% — 모델 간 기준 해석 차이가 심해 혼합판정으로는
2×2 소비 QA 결론 불가 (스킬 consumer-qa-holdout §6: 판정자 변경 시 교차 검증 후
그대로 쓰지 말 것 — 10-08 deepcombo vs space-bunny 합의율 46%).
→ space-bunny 단일 판정자로 전량 재판정 (직접 HTTP, 200 확인, 무료 할당량 리셋 확인).

- 단일 스레드 (병렬 금지)
- max_tokens=800 + reason 20단어 제한 (10-09 parse_fail 9건 = 400자 잘림 경험)
- 체크포인트: stage102k_judge_sb_all.json (10건마다)
- 완료 후 stage102h_judge_fixed.json을 space-bunny 판정으로 원자적 교체
- 429 시 Retry-After 대기 (최대 120초) × 5회, 끝나고도 남은 건 2회 재시도 루프
"""
import json, os, sys, time, urllib.request, urllib.error

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
os.chdir(REPO)

URL = "https://opencode.ai/zen/v1/chat/completions"
MODEL = "space-bunny-free"
OUT = os.path.join("experiments", "operational-golden", "data", "stage102k_judge_sb_all.json")
MAIN = os.path.join("experiments", "operational-golden", "data", "stage102h_judge_fixed.json")
QA = os.path.join("experiments", "operational-golden", "data", "stage101_consumer.json")

SLEEP = 0.3
SAVE_EVERY = 10

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
                print(f"    429 (attempt {attempt+1}): {ra} → {wait}s 대기", flush=True)
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
    qa = json.load(open(QA, encoding="utf-8"))
    qa = [x for x in qa if "[ERR" not in str(x.get("response"))]
    print(f"전체: {len(qa)}건", flush=True)

    results = []
    done_keys = set()
    if os.path.exists(OUT):
        try:
            results = json.load(open(OUT, encoding="utf-8"))
            done_keys = {key(x) for x in results if x.get("judge_verdict") in ("yes", "no")}
            print(f"체크포인트: {len(results)}건 (유효 {len(done_keys)})", flush=True)
        except Exception:
            results = []

    targets = [x for x in qa if key(x) not in done_keys]
    print(f"판정 대상: {len(targets)}건 (model={MODEL}, 단일 판정자)", flush=True)

    t0 = time.time()
    round_no = 1
    while targets and round_no <= 3:
        print(f"--- 라운드 {round_no}: {len(targets)}건 ---", flush=True)
        still = []
        errs = 0
        for i, x in enumerate(targets):
            v, reason = judge(x)
            if v == "parse_fail":
                errs += 1
                still.append(x)
            x["judge_verdict"] = v
            x["judge_reason"] = reason
            x["judge_model"] = MODEL
            results.append(x)
            if (len(results)) % SAVE_EVERY == 0:
                el = time.time() - t0
                rate = len(results) / el * 60
                json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"  {len(results)}건 누적 (err {errs}) {rate:.1f}건/분", flush=True)
            time.sleep(SLEEP)
        json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
        targets = [x for x in still if key(x) not in done_keys]
        # 성공한 건 체크포인트 반영
        done_keys = {key(x) for x in results if x.get("judge_verdict") in ("yes", "no")}
        targets = [x for x in targets if key(x) not in done_keys]
        round_no += 1
        if targets:
            print(f"  라운드 {round_no-1} 종료: {len(targets)}건 실패 → 재시도", flush=True)

    el = time.time() - t0
    ok = sum(1 for x in results if x.get("judge_verdict") in ("yes", "no"))
    print(f"\n재판정 완료: {len(results)}건 처리 / 유효 {ok}건 / parse_fail {len(results)-ok}건 ({el/60:.1f}분)", flush=True)

    # stage102h 원자적 교체 — 유효 판정 건만
    merged = [x for x in results if x.get("judge_verdict") in ("yes", "no")]
    missing = [x for x in qa if key(x) not in {key(m) for m in merged}]
    if len(merged) == len(qa):
        json.dump(merged, open(MAIN, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"stage102h 교체 완료: {len(merged)}건 (전량 space-bunny 단일 판정자)", flush=True)
    else:
        print(f"⚠️ 유효 {len(merged)}/{len(qa)} — stage102h 교체 보류, 남은 {len(missing)}건", flush=True)
        json.dump(merged, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)

if __name__ == "__main__":
    main()