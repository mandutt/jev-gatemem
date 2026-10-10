# -*- coding: utf-8 -*-
"""stage116_lmev_rejudge_haiku.py — LongMemEval 500건 claude-haiku 재판정 (2026-10-10)

목적: stage112/113의 저점수(24.1%)가 "read-path 성능"인지 "deepcombo judge 노이즈"인지 분리.
- 기존 judge: deepcombo (문제 발견: hypothesis가 정답인데 no 판정한 케이스 다수)
- 재판정: tokenharbor/claude-haiku-5.5:free (표준 판정 모델, stage104 이후 검증됨)
- 입력: stage112_lmev_results.jsonl (question + answer + hypothesis) — JEV 콜 없음
- 판정 기준: hypothesis가 answer와 의미적으로 일치하는가 (yes/no)
- 소량 검증(5건) 후 전체 500건 실행
"""
import os, sys, json, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
IN = os.path.join(DATA, "stage112_lmev_results.jsonl")
OUT = os.path.join(DATA, "stage116_lmev_haiku_judged.jsonl")

JUDGE_URL = "http://localhost:20128/v1/chat/completions"
JUDGE_MODEL = "tokenharbor/claude-haiku-5.5:free"

def judge_batch(items, retries=2):
    """hypothesis가 answer와 의미적으로 일치하는지 판정"""
    lines = []
    for idx, x in enumerate(items):
        lines.append(
            f"[{idx}]\n"
            f"  질문: {x['question'][:300]}\n"
            f"  정답(answer): {str(x['answer'])[:300]}\n"
            f"  에이전트 응답(hypothesis): {str(x['hypothesis'])[:600]}"
        )
    prompt = ("다음 각 항목에서, **에이전트 응답(hypothesis)이 정답(answer)과 의미적으로 일치하는가**를 판정하세요.\n"
              "기준: 응답이 정답과 같은 사실을 말했으면 yes (표현이 달라도 무방, 부분 일치 포함).\n"
              "응답이 정답을 모르거나, 다른 사실을 말하거나, 정답과 모순되면 no.\n"
              "응답이 '모른다/없다'고 하면 no.\n\n"
              + "\n\n".join(lines) +
              "\n\n마지막 줄에 JSON 배열로만 답하세요: [{\"i\": 0, \"verdict\": \"yes/no\", \"reason\": \"한 줄\"}, ...]")
    for attempt in range(retries):
        body = {"model": JUDGE_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2}
        req = urllib.request.Request(JUDGE_URL, data=json.dumps(body).encode(),
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
            return {int(it["i"]): (str(it.get("verdict", "")).lower(), it.get("reason", ""))
                    for it in arr if isinstance(it, dict) and "i" in it
                    and str(it.get("verdict", "")).lower() in ("yes", "no")}
        except urllib.error.HTTPError as ex:
            if ex.code == 429:
                time.sleep(20)
                continue
            return {}
        except Exception:
            time.sleep(3)
    return {}

def main():
    ap = argparse = None
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="소량 검증용 (0=전체 500)")
    args = ap.parse_args()

    rows = []
    with open(IN, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if args.limit:
        rows = rows[:args.limit]
    print(f"대상: {len(rows)}건", flush=True)

    # 체크포인트
    done_ids = set()
    results = []
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    j = json.loads(line)
                    if j.get("verdict") in ("yes", "no"):
                        done_ids.add(j["question_id"])
                        results.append(j)
    targets = [r for r in rows if r["question_id"] not in done_ids]
    print(f"판정 대상: {len(targets)}건 (완료 {len(done_ids)})", flush=True)

    t0 = time.time()
    pending = targets
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
                        results.append({"question_id": x["question_id"],
                                        "question_type": x.get("question_type"),
                                        "verdict": v, "reason": reason})
                    else:
                        next_p.append(x)
        pending = next_p
        if pending:
            print(f"  🔄 재시도: {len(pending)}건", flush=True)
        # 중간 저장
        with open(OUT, "w", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        if len(results) % 100 == 0 and len(results) > 0:
            print(f"  {len(results)}건 ({time.time()-t0:.0f}초)", flush=True)

    # 요약
    from collections import Counter
    yes = sum(1 for r in results if r.get("verdict") == "yes")
    no = sum(1 for r in results if r.get("verdict") == "no")
    print(f"\n재판정 완료: {len(results)}건 — yes {yes} ({yes/len(results)*100:.1f}%), no {no}", flush=True)

    # 유형별
    by_type = Counter()
    for r in results:
        by_type[(r.get("question_type"), r.get("verdict"))] += 1
    for (qt, v), c in sorted(by_type.items()):
        total = sum(c2 for (qt2, v2), c2 in by_type.items() if qt2 == qt)
        print(f"  {qt}: {v} {c}/{total} ({c/total*100:.0f}%)")

if __name__ == "__main__":
    main()