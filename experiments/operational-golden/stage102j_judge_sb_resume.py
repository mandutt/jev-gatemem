# -*- coding: utf-8 -*-
"""stage102j_judge_sb_resume.py — space-bunny 직접 HTTP로 stage102h 잔여 판정 (2026-10-09)

리셋 확인: 10-09 09:3x space-bunny 직접 HTTP 200 (probe).
전략 (사용자 지시 10-09):
- opencode CLI 병렬 스폰 금지 → CLI 미사용, 직접 HTTP 단일 스레드
- 체크포인트 stage102h_judge_fixed.json 유지, 미판정 건만 이어서
- 대상: (a) judge_verdict가 yes/no가 아닌 건 (parse_fail) + (b) 아예 없는 건
- 완료 후 stage102h_judge_fixed.json에 병합 (기존 yes/no 항목은 절대 덮어쓰지 않음)

프롬프트는 stage102h_judge_fixed_workers.py build_prompt와 동일 (교차 모델 판정 일관성).
chat()은 stage102b_judge_opencode.py 패턴 (max_tokens=400, retries=5, UA opencode/2.0.19).
"""
import json, os, sys, time, urllib.request, urllib.error, argparse

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
os.chdir(REPO)

URL = "https://opencode.ai/zen/v1/chat/completions"
MODEL = "space-bunny-free"
OUT = os.path.join("experiments", "operational-golden", "data", "stage102j_judge_sb_resume.json")
MAIN = os.path.join("experiments", "operational-golden", "data", "stage102h_judge_fixed.json")
QA = os.path.join("experiments", "operational-golden", "data", "stage101_consumer.json")

SLEEP = 0.3

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
                # Retry-After 확인
                ra = e.headers.get("Retry-After")
                wait = 5 * (attempt + 1)
                if ra and ra.isdigit():
                    wait = min(int(ra), 120)
                print(f"    429: {ra} → {wait}s 대기", flush=True)
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

JSON 형식으로만 답하세요:
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
        # 중첩 JSON 대응 (stage102b)
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--save-every", type=int, default=10)
    args = ap.parse_args()

    d = json.load(open(QA, encoding="utf-8"))
    d = [x for x in d if "[ERR" not in str(x.get("response"))]
    if args.limit:
        d = d[:args.limit]
    print(f"전체 성공 응답: {len(d)}건", flush=True)

    # 기존 stage102h 체크포인트의 (key → item) 맵
    main_items = {}
    if os.path.exists(MAIN):
        ml = json.load(open(MAIN, encoding="utf-8"))
        main_items = {key(x): x for x in ml}
        print(f"체크포인트 stage102h: {len(ml)}건", flush=True)

    done_keys = {k for k, x in main_items.items() if x.get("judge_verdict") in ("yes", "no")}
    print(f"  유효 판정(yes/no): {len(done_keys)}건", flush=True)

    # 이어서 저장용 (stage102j 자체 체크포인트)
    results = []
    done_j = set()
    if os.path.exists(OUT):
        try:
            results = json.load(open(OUT, encoding="utf-8"))
            done_j = {key(x) for x in results if x.get("judge_verdict") in ("yes", "no")}
            print(f"stage102j 체크포인트: {len(results)}건 (유효 {len(done_j)})", flush=True)
        except Exception:
            results = []

    targets = [x for x in d if key(x) not in done_keys and key(x) not in done_j]
    print(f"판정 대상: {len(targets)}건 (model={MODEL})", flush=True)

    errs = 0
    t0 = time.time()
    for i, x in enumerate(targets):
        v, reason = judge(x)
        if v == "parse_fail":
            errs += 1
        x["judge_verdict"] = v
        x["judge_reason"] = reason
        x["judge_model"] = MODEL
        results.append(x)
        if (i + 1) % args.save_every == 0:
            el = time.time() - t0
            rate = (i + 1) / el * 60
            json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"  {i+1}/{len(targets)} (err {errs}) {rate:.1f}건/분", flush=True)
        time.sleep(SLEEP)

    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    el = time.time() - t0
    print(f"\nstage102j 완료: {len(results)}건 → {OUT} (err {errs}, {el/60:.1f}분)", flush=True)

    # ---- 병합: stage102h 체크포인트에 유효 판정만 반영 (기존 yes/no는 보존) ----
    merged = list(main_items.values())
    merged_map = {key(x): x for x in merged}
    replaced = added = 0
    for x in results:
        if x.get("judge_verdict") not in ("yes", "no"):
            continue
        k = key(x)
        if k in merged_map:
            old = merged_map[k]
            if old.get("judge_verdict") not in ("yes", "no"):
                # 기존 parse_fail → 교체
                idx = next(i for i, m in enumerate(merged) if key(m) == k)
                merged[idx] = x
                replaced += 1
        else:
            merged.append(x)
            merged_map[k] = x
            added += 1
    json.dump(merged, open(MAIN, "w", encoding="utf-8"), ensure_ascii=False)
    from collections import Counter
    print(f"병합 완료: → {MAIN} 총 {len(merged)}건 (교체 {replaced}, 추가 {added})", flush=True)
    print(f"최종 verdict: {dict(Counter(m.get('judge_verdict') for m in merged))}", flush=True)
    remain = [x for x in d if key(x) not in {key(m) for m in merged if m.get('judge_verdict') in ('yes','no')}]
    print(f"아직 미판정(유효 기준): {len(remain)}건", flush=True)

if __name__ == "__main__":
    main()