# -*- coding: utf-8 -*-
"""stage102o_batch_judge_qwen.py — qwen3.8-flash-next-uncensored 배치 판정 (2026-10-10)

Experlabs OpenAI 호환 엔드포인트 (/v1/chat/completions) 사용:
- 모델: qwen3.8-flash-next-uncensored (대형 reasoning 모델 — reasoning 후 content 출력)
- 배치: 5건/콜 (콜 수 90% 절감)
- 판정 기준: 응답이 "사용자 특정 정보(경로/수치/과거 사건/고유 규칙)"를 인용했는가
  (2026-10-10 인간 감사에서 "메모리 인용" 판정이 모호했던 문제 반영)
"""
import json, os, sys, time, urllib.request, urllib.error, winreg
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
QA = os.path.join(DATA, "stage101_consumer.json")
OUT = os.path.join(DATA, "stage102o_judge_qwen.json")

API_URL = "https://api.experientiallabs.ai/v1/chat/completions"
MODEL = "qwen3.8-flash-next-uncensored"
BATCH = 5
# 2026-10-10: max_tokens 미지정이 최적 — 지정 시 모델이 한도까지 reasoning을 늘려 느려지고(110s),
#             생략 시 필요한 만큼만 생성(13.7s, finish=stop). 실측 결과.
MAX_TOKENS = None
WORKERS = 1        # 2026-10-10: 4/3워커에서 429·응답 중단 다수 → 1워커 확정 (안정성 우선)

def load_key(name):
    try:
        hk = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment")
        v, _ = winreg.QueryValueEx(hk, name)
        winreg.CloseKey(hk)
        return v
    except OSError:
        return ""

API_KEY = load_key("EXPLABS_API_KEY") or load_key("EXPLABS_API_KEY2")
# 2026-10-10: 키2가 더 빠름(13.5s vs 38.5s, 429 덜함) — 키2 우선, 429 시 키 전환
API_KEY2 = load_key("EXPLABS_API_KEY2") or API_KEY
_current_key = API_KEY2  # 키2 우선 (실측)

# 판정 기준: "사용자 특정 정보 인용" — 일반 지식으로 대체 불가능한 정보
JUDGE_STD = (
    "응답이 **사용자 고유의 특정 정보**(파일 경로, 설정 값, 실험 수치, 과거 사건/결론, "
    "사용자 고유 규칙)를 구체적으로 인용했는가? "
    "일반 지식/추론으로도 답할 수 있는 내용만 있으면 no."
)

def build_batch_prompt(items):
    lines = []
    for idx, x in enumerate(items):
        lines.append(
            f"[{idx}] 질문: {x['query']}\n"
            f"    AI 응답: {str(x['response'])[:600]}\n"
            f"    이 질문은 {'무답(답이 없는) 질문' if x['cls']=='block' else '정답이 있는 질문'}입니다."
        )
    return (
        "다음 각 항목의 AI 응답을 평가하세요.\n\n"
        + "\n\n".join(lines) +
        f"\n\n판정 기준: {JUDGE_STD}\n"
        f'각 항목에 대해 JSON 배열로만 답하세요: [{{"i": 0, "verdict": "yes/no", "reason": "한 줄"}}, ...]\n'
        "(verdict는 \"yes\" 또는 \"no\"만, reason은 한 줄, 다른 텍스트 금지)"
    )

def parse_batch(resp_text):
    s = resp_text.find("[")
    e = resp_text.rfind("]")
    if s < 0 or e < 0:
        return {}
    try:
        arr = json.loads(resp_text[s:e+1])
        return {int(it["i"]): (str(it.get("verdict", "")).lower(), it.get("reason", ""))
                for it in arr if isinstance(it, dict) and "i" in it
                and str(it.get("verdict", "")).lower() in ("yes", "no")}
    except Exception:
        return {}

def call_batch(prompt, retries=3):
    global _current_key
    body = {"model": MODEL,
            "messages": [{"role": "user", "content": prompt}]}
    if MAX_TOKENS:
        body["max_tokens"] = MAX_TOKENS
    for attempt in range(retries):
        req = urllib.request.Request(API_URL, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {_current_key}"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                raw = r.read().decode()
            d = json.loads(raw)
            c = d["choices"][0]["message"].get("content") or ""
            if c.strip():
                return c
            return None
        except urllib.error.HTTPError as ex:
            if ex.code == 429:
                # 키 전환 시도 (키1↔키2)
                _current_key = API_KEY2 if _current_key == API_KEY else API_KEY
                print(f"  429 — 키 전환 후 60s 대기", flush=True)
                time.sleep(60)
                continue
            print(f"  HTTP {ex.code}: {ex.read().decode()[:120]}", flush=True)
            return None
        except Exception as e:
            print(f"  ERR: {e}", flush=True)
            time.sleep(5)
    return None

def main():
    ap = sys.argv
    limit = int(ap[1]) if len(ap) > 1 else 0
    d = json.load(open(QA, encoding="utf-8"))
    d = [x for x in d if "[ERR" not in str(x.get("response"))]
    if limit:
        d = d[:limit]
    print(f"전체: {len(d)}건, 배치 {BATCH}건/콜", flush=True)

    # 체크포인트
    done_keys = set()
    results = []
    if os.path.exists(OUT):
        try:
            results = json.load(open(OUT, encoding="utf-8"))
            done_keys = {(x["query"], x["k"], x["framing"], x.get("sample")) for x in results
                         if x.get("judge_verdict") in ("yes", "no")}
            print(f"체크포인트: {len(results)}건", flush=True)
        except Exception:
            pass

    targets = [x for x in d if (x["query"], x["k"], x["framing"], x.get("sample")) not in done_keys]
    print(f"판정 대상: {len(targets)}건", flush=True)

    t0 = time.time()
    n_calls = 0
    pending = targets  # 재시도 대상
    while pending:
        next_pending = []
        # 병렬 배치 처리
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(call_batch, build_batch_prompt(batch)): batch
                    for batch in [pending[i:i+BATCH] for i in range(0, len(pending), BATCH)]}
            done = 0
            for fut in as_completed(futs):
                batch = futs[fut]
                resp = fut.result()
                n_calls += 1
                parsed = parse_batch(resp) if resp else {}
                batch_ok = True
                for idx, x in enumerate(batch):
                    if idx in parsed:
                        v, reason = parsed[idx]
                        x["judge_verdict"] = v
                        x["judge_reason"] = reason
                        x["judge_model"] = MODEL
                        results.append(x)
                    else:
                        batch_ok = False
                        next_pending.append(x)  # 실패 항목 재시도
                if not batch_ok:
                    print(f"  ⚠️ 배치 부분 실패 — {sum(1 for i in range(len(batch)) if i not in parsed)}건 재시도 대기", flush=True)
                done += 1
                if done % 20 == 0:
                    el = time.time() - t0
                    print(f"  {done}배치 완료 — {len(results)}건 ({el/60:.1f}분, {n_calls}콜)", flush=True)
                    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
                time.sleep(0.3)
        pending = next_pending
        if pending:
            print(f"  🔄 재시도 라운드: {len(pending)}건", flush=True)

    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    el = time.time() - t0
    print(f"\n완료: {len(results)}건, {n_calls}콜 ({el/60:.1f}분)", flush=True)
    print(f"→ {OUT}")

if __name__ == "__main__":
    main()