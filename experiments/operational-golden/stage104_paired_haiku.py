# -*- coding: utf-8 -*-
"""stage104_paired_haiku.py — k=2 framing 페어드 실험 (haiku 통일판, 2026-10-10)

배경: stage103은 deepcombo 생성(ERR 70건 포함 판정 오염) + haiku 판정 — 방법론 오류.
사용자 결정: **생성도 haiku로 통일** (tokenharbor/claude-haiku-5.5:free).

- 60개 질문 전체 × fF/fT × 3샘플 = 360건 생성 (haiku)
- JEV 캐시(stage103_jev.json) 재사용 — pool/pick 동일
- 판정도 haiku (배치 5, 2워커)
- ERR 응답은 판정에서 제외
"""
import os, sys, json, time, argparse, urllib.request, urllib.error

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)

from stage101_consumer_rerun import build_prompt

URL = "http://localhost:20128/v1/chat/completions"
MODEL = "tokenharbor/claude-haiku-5.5:free"

def chat(prompt, temperature=0.2, max_tokens=400, retries=2):
    body = {"model": MODEL,
            "messages": [
                {"role": "system", "content": "당신은 Hermes 어시스턴스입니다. 한국어로 답변합니다."},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature}
    if max_tokens:
        body["max_tokens"] = max_tokens
    for attempt in range(retries):
        req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            # 2026-10-10: 120s 타임아웃이 hang 유발 → 40s로 단축 (hang 시 빠른 재시도)
            with urllib.request.urlopen(req, timeout=40) as r:
                raw = r.read().decode()
            d = json.loads(raw if raw.rstrip().endswith('}') else raw[:raw.rfind('}')+1])
            c = d["choices"][0]["message"].get("content") or ""
            if c.strip():
                return c
            return f"[ERR 빈응답]"
        except urllib.error.HTTPError as ex:
            if ex.code == 429:
                time.sleep(20 * (attempt + 1))
                continue
            return f"[ERR HTTP {ex.code}]"
        except Exception as e:
            time.sleep(2)
    return "[ERR 타임아웃]"

def judge_batch(items, retries=2):
    lines = []
    for idx, x in enumerate(items):
        lines.append(f"[{idx}] 질문: {x['query']}\n    AI 응답: {str(x['response'])[:600]}\n    이 질문은 정답이 있는 질문입니다.")
    prompt = ("다음 각 항목의 AI 응답을 평가하세요.\n\n" + "\n\n".join(lines) +
              "\n\n판정 기준: 응답이 **사용자 고유의 특정 정보**(파일 경로, 설정 값, 실험 수치, 과거 사건/결론, 사용자 고유 규칙)를 구체적으로 인용했는가? 일반 지식/추론으로도 답할 수 있는 내용만 있으면 no.\n"
              '각 항목에 대해 JSON 배열로만 답하세요: [{"i": 0, "verdict": "yes/no", "reason": "한 줄"}, ...] (verdict는 "yes" 또는 "no"만, reason은 한 줄, 다른 텍스트 금지)')
    for attempt in range(retries):
        body = {"model": MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2}
        req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                raw = r.read().decode()
            d = json.loads(raw if raw.rstrip().endswith('}') else raw[:raw.rfind('}')+1])
            c = d["choices"][0]["message"].get("content") or ""
            if not c.strip():
                return {}
            s, e = c.find("["), c.rfind("]")
            arr = json.loads(c[s:e+1])
            return {int(it["i"]): (str(it.get("verdict","")).lower(), it.get("reason",""))
                    for it in arr if isinstance(it, dict) and "i" in it
                    and str(it.get("verdict","")).lower() in ("yes","no")}
        except urllib.error.HTTPError as ex:
            if ex.code == 429:
                time.sleep(20); continue
            return {}
        except Exception:
            time.sleep(3)
    return {}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--gen-only", action="store_true", help="생성만 (판정 생략)")
    args = ap.parse_args()

    out_dir = os.path.join("experiments", "operational-golden", "data")
    QA_OUT = os.path.join(out_dir, "stage104_paired_haiku.json")
    JUDGE_OUT = os.path.join(out_dir, "stage104_paired_haiku_judge.json")

    # 1) 질문 + JEV 캐시 로드
    s101 = json.load(open(os.path.join(out_dir, "stage101_consumer.json"), encoding="utf-8"))
    uniq = {}
    for x in s101:
        uniq.setdefault(x["query"], x["cls"])
    queries = list(uniq.keys())[:args.limit]

    jev_cache = json.load(open(os.path.join(out_dir, "stage103_jev.json"), encoding="utf-8"))
    jev_map = {r["q"]: r for r in jev_cache}
    print(f"질문 {len(queries)}개, JEV 캐시 {len(jev_map)}개", flush=True)

    # 2) haiku 응답 생성 (체크포인트)
    results = []
    if os.path.exists(QA_OUT):
        try:
            results = json.load(open(QA_OUT, encoding="utf-8"))
        except Exception:
            pass
    done = {(x["query"], x["framing"], x.get("sample")) for x in results
            if not str(x.get("response","")).startswith("[ERR")}
    temps = [0.2, 0.5, 0.8]
    targets = []
    for qi, q in enumerate(queries):
        jr = jev_map.get(q)
        if not jr:
            continue
        ordered = jr.get("ordered") or []
        rows_k = ordered[:2]
        for framing in (False, True):
            for ti, temp in enumerate(temps):
                if (q, framing, ti) in done:
                    continue
                targets.append((q, framing, ti, temp, rows_k))
    print(f"생성 대상: {len(targets)}건 (완료 {len(done)}건)", flush=True)

    from concurrent.futures import ThreadPoolExecutor, as_completed
    t0 = time.time()
    WORKERS_GEN = 1  # 2026-10-10: 2워커에서 9router hang → 1워커 안정화
    with ThreadPoolExecutor(max_workers=WORKERS_GEN) as ex:
        futs = {}
        for (q, framing, ti, temp, rows_k) in targets:
            prompt = build_prompt(q, rows_k, framing)
            futs[ex.submit(chat, prompt, temp)] = (q, framing, ti, temp)
        done_n = 0
        for fut in as_completed(futs):
            q, framing, ti, temp = futs[fut]
            ans = fut.result()
            results.append({"query": q, "cls": uniq.get(q), "k": 2,
                            "framing": framing, "sample": ti, "temp": temp,
                            "pick_id": (jev_map.get(q) or {}).get("pick_id"),
                            "abstain_p": (jev_map.get(q) or {}).get("abstain_p"),
                            "response": ans, "model": MODEL})
            done_n += 1
            if done_n % 25 == 0:
                # 중간 체크포인트 저장
                json.dump(results, open(QA_OUT, "w", encoding="utf-8"), ensure_ascii=False)
                errs = sum(1 for x in results if str(x.get("response","")).startswith("[ERR"))
                print(f"  생성 {done_n}/{len(targets)} ({time.time()-t0:.0f}초, ERR {errs})", flush=True)
    json.dump(results, open(QA_OUT, "w", encoding="utf-8"), ensure_ascii=False)
    errs = sum(1 for x in results if str(x.get("response","")).startswith("[ERR"))
    print(f"생성 완료: {len(results)}건, ERR {errs}건 ({time.time()-t0:.0f}초)", flush=True)

    if args.gen_only:
        return

    # 3) haiku 판정 (ERR 제외)
    judged = []
    if os.path.exists(JUDGE_OUT):
        try:
            judged = json.load(open(JUDGE_OUT, encoding="utf-8"))
        except Exception:
            pass
    done_j = {(x["query"], x["framing"], x["sample"]) for x in judged if x.get("verdict") in ("yes","no")}
    targets_j = [x for x in results
                 if not str(x.get("response","")).startswith("[ERR")
                 and (x["query"], x["framing"], x.get("sample")) not in done_j]
    print(f"판정 대상: {len(targets_j)}건", flush=True)
    pending = targets_j
    t1 = time.time()
    while pending:
        next_p = []
        batches = [pending[i:i+5] for i in range(0, len(pending), 5)]
        with ThreadPoolExecutor(max_workers=2) as ex:
            futs = {ex.submit(judge_batch, b): b for b in batches}
            for fut in as_completed(futs):
                b = futs[fut]
                parsed = fut.result()
                for idx, x in enumerate(b):
                    if idx in parsed:
                        v, reason = parsed[idx]
                        judged.append({"query": x["query"], "framing": x["framing"], "sample": x["sample"],
                                       "verdict": v, "reason": reason})
                    else:
                        next_p.append(x)
        pending = next_p
        if pending:
            print(f"  🔄 판정 재시도: {len(pending)}건", flush=True)
    json.dump(judged, open(JUDGE_OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"판정 완료: {len(judged)}건 ({time.time()-t1:.0f}초)", flush=True)

if __name__ == "__main__":
    main()