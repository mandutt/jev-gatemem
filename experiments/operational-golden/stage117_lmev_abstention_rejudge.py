# -*- coding: utf-8 -*-
"""stage117_lmev_abstention_rejudge.py — abstention 30건 규칙 보정 재판정 (2026-10-10)

stage116에서 haiku 프롬프트에 abstention 규칙이 없어 29/30을 no로 판정한 것 보정.
- abstention 문항: "정직하게 거부하면 정답" — hypothesis가 '모른다/없다'고 답해도
  정답(answer)과 의미적으로 일치하면 yes (거부 = 정답)
- 대상: stage112에서 jev_abstain=True인 30건 (hypothesis 이미 존재, JEV 0콜)
- 판정: claude-haiku (6콜)
"""
import os, sys, json, time, urllib.request, urllib.error

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
RES = os.path.join(DATA, "stage112_lmev_results.jsonl")
JUDGED = os.path.join(DATA, "stage113_lmev_judged.jsonl")
OUT = os.path.join(DATA, "stage117_lmev_abstention_haiku.jsonl")

JUDGE_URL = "http://localhost:20128/v1/chat/completions"
JUDGE_MODEL = "tokenharbor/claude-haiku-5.5:free"

def judge_batch(items, retries=2):
    """abstention 문항 판정 — 정직 거부=정답 규칙 포함"""
    lines = []
    for idx, x in enumerate(items):
        lines.append(
            f"[{idx}]\n"
            f"  질문: {x['question'][:300]}\n"
            f"  정답(answer): {str(x['answer'])[:300]}\n"
            f"  에이전트 응답(hypothesis): {str(x['hypothesis'])[:600]}"
        )
    prompt = ("다음 각 항목은 **abstention(거부) 문항**입니다. 이 문항의 채점 규칙은:\n"
              "**에이전트가 \"메모리에 없음/모름/확실치 않음\"이라고 정직하게 거부하면 정답 처리**됩니다.\n"
              "판정 기준:\n"
              "- 응답이 '모른다/없다/정보 없음'을 정직하게 말했다면 → **yes** (거부 = 정답)\n"
              "- 응답이 정답을 실제로 말했어도 → **yes**\n"
              "- 응답이 거부도 아니고 정답도 아니면 (엉뚱한 사실) → **no**\n\n"
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
    # abstention 30건 추출 (stage113의 abstention=True 기준)
    abst_ids = set()
    with open(JUDGED, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                j = json.loads(line)
                if j.get("abstention") is True:
                    abst_ids.add(j["question_id"])
    print(f"abstention 문항: {len(abst_ids)}건")

    rows = []
    with open(RES, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                if r["question_id"] in abst_ids:
                    rows.append(r)
    print(f"hypothesis 로드: {len(rows)}건")

    # 체크포인트
    results = []
    done_ids = set()
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    j = json.loads(line)
                    if j.get("verdict") in ("yes", "no"):
                        done_ids.add(j["question_id"])
                        results.append(j)
    targets = [r for r in rows if r["question_id"] not in done_ids]
    print(f"판정 대상: {len(targets)}건 (완료 {len(done_ids)})")

    # 5건 소량 검증 → 전체
    from concurrent.futures import ThreadPoolExecutor, as_completed
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
    with open(OUT, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    yes = sum(1 for r in results if r.get("verdict") == "yes")
    print(f"\nabstention 보정 재판정: {len(results)}건 — yes {yes}/{len(results)} ({yes/len(results)*100:.1f}%)")

if __name__ == "__main__":
    main()