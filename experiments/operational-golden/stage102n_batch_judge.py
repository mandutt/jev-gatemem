# -*- coding: utf-8 -*-
"""stage102n_batch_judge.py — 배치 판정 러너 (콜 수 90% 절감, 2026-10-10)

기존: 건당 1콜 (1,074콜) → 배치: 5건/콜 (~215콜)

핵심:
- 프롬프트 1개에 N건의 (질문, 응답)을 넣고 JSON 배열로 판정 요청
- 각 건: {"i": 인덱스, "verdict": "yes"/"no", "reason": "..."}
- temperature: 모델 기본값 유지 (0.2 — 노이즈 인위 제거 금지, 2026-10-10 결정)
- space-bunny 직접 HTTP (429 시 지수 백오프)
"""
import json, os, sys, time, urllib.request, urllib.error, random

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
QA = os.path.join(DATA, "stage101_consumer.json")
OUT = os.path.join(DATA, "stage102n_batch_judge.json")

URL = "https://opencode.ai/zen/v1/chat/completions"
MODEL = "space-bunny-free"
BATCH = 5   # 1콜당 판정 건수
TEMPERATURE = 0.2  # 모델 기본값 — 노이즈 보존

JSON_FORMAT = '[{"i": 0, "verdict": "yes/no", "reason": "..."}, ...]'

def build_batch_prompt(items):
    """N건을 하나의 프롬프트로 — 각 건에 질문+응답+예상 답변 유무"""
    lines = []
    for idx, x in enumerate(items):
        cls = x["cls"]
        judge_cls = "무답(제공된 메모리 안에 답이 없는) 질문" if cls == "block" else "정답이 있는 질문"
        judge_q = ("응답이 제공된 메모리 컨텍스트의 내용을 마치 사실인 것처럼 근거로 인용했습니까?"
                   if cls == "block" else "응답이 정확하고 유용한 답변을 제공했습니까?")
        lines.append(
            f"[{idx}] 질문: {x['query']}\n"
            f"    AI 응답: {str(x['response'])[:600]}\n"
            f"    기준: 이 질문은 {judge_cls}입니다. {judge_q}"
        )
    prompt = (
        "다음 각 항목의 AI 응답을 평가하세요.\n\n"
        + "\n\n".join(lines) +
        f"\n\n각 항목에 대해 JSON 배열로만 답하세요:\n{JSON_FORMAT}\n"
        "(verdict는 \"yes\" 또는 \"no\"만, reason은 한 줄)"
    )
    return prompt

def parse_batch(resp_text, n):
    """배치 응답에서 [i, verdict, reason] 추출"""
    s = resp_text.find("[")
    e = resp_text.rfind("]")
    if s < 0 or e < 0:
        return {}
    try:
        arr = json.loads(resp_text[s:e+1])
        result = {}
        for item in arr:
            if isinstance(item, dict) and "i" in item:
                v = str(item.get("verdict", "")).lower()
                if v in ("yes", "no"):
                    result[int(item["i"])] = (v, item.get("reason", ""))
        return result
    except Exception:
        return {}

def call_batch(prompt, retries=5):
    body = {"model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1500, "temperature": TEMPERATURE}
    for attempt in range(retries):
        req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "opencode/2.0.19"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read().decode()
            c = json.loads(raw.split("data:")[0])["choices"][0]["message"]["content"]
            return c
        except urllib.error.HTTPError as ex:
            if ex.code == 429:
                wait = min(60 * (attempt + 1), 300)
                print(f"  429 — {wait}s 대기", flush=True)
                time.sleep(wait)
                continue
            return None
        except Exception:
            time.sleep(5)
            continue
    return None

def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    d = json.load(open(QA, encoding="utf-8"))
    d = [x for x in d if "[ERR" not in str(x.get("response"))]
    if limit:
        d = d[:limit]
    print(f"전체: {len(d)}건, 배치 {BATCH}건/콜 → 약 {len(d)//BATCH + 1}콜 예상", flush=True)

    # 체크포인트
    done_keys = set()
    results = []
    if os.path.exists(OUT):
        try:
            results = json.load(open(OUT, encoding="utf-8"))
            done_keys = {(x["query"], x["k"], x["framing"], x.get("sample")) for x in results if x.get("judge_verdict") in ("yes", "no")}
            print(f"체크포인트: {len(results)}건", flush=True)
        except Exception:
            pass

    targets = [x for x in d if (x["query"], x["k"], x["framing"], x.get("sample")) not in done_keys]
    print(f"판정 대상: {len(targets)}건", flush=True)

    t0 = time.time()
    ok = 0
    for start in range(0, len(targets), BATCH):
        batch = targets[start:start+BATCH]
        prompt = build_batch_prompt(batch)
        resp = call_batch(prompt)
        if resp is None:
            print(f"  배치 {start//BATCH} 실패 (retries 소진) — 이 배치는 건너뜀", flush=True)
            continue
        parsed = parse_batch(resp, len(batch))
        for idx, x in enumerate(batch):
            if idx in parsed:
                v, reason = parsed[idx]
                x["judge_verdict"] = v
                x["judge_reason"] = reason
                x["judge_model"] = MODEL
                x["judge_batch"] = True
                results.append(x)
                ok += 1
            else:
                # 개별 재시도 1회
                single = call_batch(build_batch_prompt([x]))
                if single:
                    sp = parse_batch(single, 1)
                    if 0 in sp:
                        v, reason = sp[0]
                        x["judge_verdict"] = v
                        x["judge_reason"] = reason
                        x["judge_model"] = MODEL
                        x["judge_batch"] = False
                        results.append(x)
                        ok += 1
        if (start // BATCH + 1) % 10 == 0:
            el = time.time() - t0
            print(f"  배치 {start//BATCH + 1}/{(len(targets)-1)//BATCH + 1} — {ok}건 판정 ({el/60:.1f}분)", flush=True)
            json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
        time.sleep(1)

    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    el = time.time() - t0
    print(f"\n완료: {ok}/{len(targets)}건 판정 ({el/60:.1f}분, 약 {len(targets)//BATCH + 1}콜)", flush=True)
    print(f"→ {OUT}")

if __name__ == "__main__":
    main()