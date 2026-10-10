# -*- coding: utf-8 -*-
"""stage102p_batch_judge_deepseek.py — deepseek-v4.1-flash:free 배치 판정 (2026-10-10)

9router(localhost:20128) 모델 tkh/deepseek-v4.1-flash:free 사용:
- qwen3.8(Experlabs) 503/429 반복 문제 → 로컬 9router로 전환 (11.8s/배치 실측)
- 배치: 5건/콜, 워커: 2 (사용자 지정)
- 판정 기준: 응답이 "사용자 특정 정보(경로/수치/과거 사건/고유 규칙)"를 인용했는가
"""
import json, os, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
QA = os.path.join(DATA, "stage101_consumer.json")
OUT = os.path.join(DATA, "stage102p_judge_claude.json")  # 모델별 분리 (deepseek 판정 135건은 미사용)

URL = "http://localhost:20128/v1/chat/completions"
MODEL = "tokenharbor/claude-haiku-5.5:free"  # 2026-10-10: 6.3s/배치 (deepseek 57s 대비 9배 빠름), 판정 더 정확
BATCH = 5
WORKERS = 2

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
    body = {"model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2}
    for attempt in range(retries):
        req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=240) as r:
                raw = r.read().decode()
            # 9router 응답: JSON + trailing "data: [DONE]"
            # content 필드만 정확히 추출 (reasoning_content 필드와 구분)
            d = json.loads(raw if raw.rstrip().endswith('}') else raw[:raw.rfind('}')+1])
            msg = d.get("choices", [{}])[0].get("message", {})
            c = msg.get("content") or ""
            if c.strip():
                return c
            return None
        except urllib.error.HTTPError as ex:
            if ex.code == 429:
                time.sleep(30)
                continue
            print(f"  HTTP {ex.code}: {ex.read().decode()[:120]}", flush=True)
            return None
        except json.JSONDecodeError as e:
            print(f"  JSON 파싱 실패: {e} (raw {len(raw)}자)", flush=True)
            return None
        except Exception as e:
            print(f"  ERR: {e}", flush=True)
            time.sleep(3)
    return None

def main():
    ap = sys.argv
    limit = int(ap[1]) if len(ap) > 1 else 0
    d = json.load(open(QA, encoding="utf-8"))
    d = [x for x in d if "[ERR" not in str(x.get("response"))]
    if limit:
        d = d[:limit]
    print(f"전체: {len(d)}건, 배치 {BATCH}건/콜, 워커 {WORKERS}", flush=True)

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
    pending = targets
    while pending:
        next_pending = []
        batches = [pending[i:i+BATCH] for i in range(0, len(pending), BATCH)]
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(call_batch, build_batch_prompt(b)): b for b in batches}
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
                        next_pending.append(x)
                if not batch_ok:
                    print(f"  ⚠️ 부분 실패 — 재시도 대기", flush=True)
                done += 1
                if done % 25 == 0:
                    el = time.time() - t0
                    print(f"  {done}배치 — {len(results)}건 ({el/60:.1f}분, {n_calls}콜)", flush=True)
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