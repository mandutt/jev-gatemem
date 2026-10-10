# -*- coding: utf-8 -*-
"""stage107_k3_answer_util.py — k=3 정답 활용률 실측 (2026-10-10)

사안 A(k=2 보류)의 절충 후보 k=3을 소비 QA로 검증.
- stage93 구조 재사용: 기존 stage93_jev_rows.json (JEV choice 결과) 사용 — JEV 재호출 없음
- 대상: yes/valid 22건 (정답 활용률) + block 38건 (환각률 비교용)
- 조건: {k=3} × {framing OFF} + 비교 셀 {k=5, k=2}은 stage93 기존 결과 사용
- 소비 모델: deepcombo (Hermes 메인 모델)
- 판정: claude-haiku (tokenharbor/claude-haiku-5.5:free) — 정답 활용 여부

실행: python stage107_k3_answer_util.py
"""
import os, sys, json, time, argparse, urllib.request, urllib.error

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)

from stage101_consumer_rerun import chat  # deepcombo 채팅 재사용

DATA = os.path.join("experiments", "operational-golden", "data")
JEV_ROWS = os.path.join(DATA, "stage93_jev_rows.json")
OUT = os.path.join(DATA, "stage107_k3_answer_util.json")

JUDGE_URL = "http://localhost:20128/v1/chat/completions"
JUDGE_MODEL = "tokenharbor/claude-haiku-5.5:free"

def build_prompt(q, k, framing, rows):
    picked_rows = rows[:k] if rows else []
    body = "\n".join(f"- {r['content']}" for r in picked_rows) if picked_rows else "(메모리 없음)"
    if framing:
        body = ("[참고용 메모리: 아래 내용은 질문과 키워드가 유사하여 검색된 결과입니다. "
                "질문에 대한 직접적이고 명확한 답이 없다면 이 메모리를 무시하고 답변하십시오.]\n" + body)
    return (f"<retrieved_context>\n{body}\n</retrieved_context>\n\n"
            f"질문: {q}\n위 메모리를 참고하여 답변하세요.")

def judge_batch(items, retries=2):
    """정답 활용 판정: yes/valid 질문 — 응답이 메모리 속 정답을 정확히 활용했는가"""
    lines = []
    for idx, x in enumerate(items):
        lines.append(f"[{idx}] 질문: {x['query']}\n    AI 응답: {str(x['response'])[:600]}")
    prompt = ("다음 각 항목에서, AI 응답이 **제공된 메모리 컨텍스트 속 '정답'을 정확히 활용해 답변했는가**를 판정하세요.\n"
              "기준: 응답이 메모리에 있는 정보(경로, 수치, 규칙, 과거 결론 등)를 정확히 인용하거나 그에 기반해 답하면 yes.\n"
              "메모리를 무시하고 일반 지식/추론으로만 답했거나, 메모리 내용과 다른 답을 했으면 no.\n\n"
              + "\n\n".join(lines) +
              "\n마지막 줄에 JSON 배열로만 답하세요: [{\"i\": 0, \"verdict\": \"yes/no\", \"reason\": \"한 줄\"}, ...]")
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
    ap.add_argument("--subset", type=int, default=0)
    args = ap.parse_args()

    jev_rows = json.load(open(JEV_ROWS, encoding="utf-8"))
    if args.subset:
        jev_rows = jev_rows[:args.subset]
    print(f"JEV 결과: {len(jev_rows)}건", flush=True)

    # 1) k=3 소비 QA (framing OFF만 — k=2/k=5와 동일 조건 비교)
    results = []
    if os.path.exists(OUT):
        try:
            results = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            pass
    done = {(x["query"]) for x in results}
    t0 = time.time()
    for i, jr in enumerate(jev_rows):
        q = jr["q"]
        if q in done:
            continue
        rows = jr.get("rows") or []
        ans = chat(build_prompt(q, 3, False, rows))
        results.append({"i": i, "query": q, "cls": jr.get("cls"),
                        "k": 3, "framing": False,
                        "jev_idx": jr.get("idx"), "abstain_p": jr.get("abstain_p"),
                        "response": ans})
        if (i + 1) % 10 == 0:
            print(f"  k3 QA {i+1}/{len(jev_rows)} ({time.time()-t0:.0f}초)", flush=True)
            json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"k3 QA 완료: {len(results)}건", flush=True)

    # 2) claude 판정 (정답 활용 여부)
    judge_out = OUT.replace(".json", "_judge.json")
    judged = []
    if os.path.exists(judge_out):
        try:
            judged = json.load(open(judge_out, encoding="utf-8"))
        except Exception:
            pass
    done_j = {(x["query"]) for x in judged if x.get("verdict") in ("yes","no")}
    targets = [x for x in results if x["query"] not in done_j]
    print(f"판정 대상: {len(targets)}건", flush=True)

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
                        judged.append({"query": x["query"], "cls": x["cls"],
                                       "verdict": v, "reason": reason})
                    else:
                        next_p.append(x)
        pending = next_p
        if pending:
            print(f"  🔄 판정 재시도: {len(pending)}건", flush=True)
    json.dump(judged, open(judge_out, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"판정 완료: {len(judged)}건", flush=True)

    # 3) 즉석 요약
    from collections import Counter
    for cls in ["yes", "valid"]:
        sub = [x for x in judged if x.get("cls") == cls and x.get("verdict") in ("yes","no")]
        if sub:
            yes = sum(1 for x in sub if x["verdict"] == "yes")
            print(f"  {cls}: 정답 활용 {yes}/{len(sub)} ({yes/len(sub)*100:.1f}%)")

if __name__ == "__main__":
    main()