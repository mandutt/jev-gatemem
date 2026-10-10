# -*- coding: utf-8 -*-
"""stage113_lmev_judge.py — LongMemEval-S 채점 (LLM judge, deepcombo 로컬) (2026-10-10)

입력: stage112_lmev_results.jsonl (500문항 응답)
판정: LongMemEval 공식 evaluate_qa.py의 get_anscheck_prompt 사용, LLM만 deepcombo로
  - yes/no 판정 → autoeval_label
  - abstention(_abs): unanswerable 식별 여부
출력: data/stage113_lmev_judged.jsonl (문항 + label + 정확도 요약)
"""
import os, sys, json, time, concurrent.futures, urllib.request

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)

RESULTS = os.path.join(REPO, "experiments", "operational-golden", "data", "stage112_lmev_results.jsonl")
OUT = os.path.join(REPO, "experiments", "operational-golden", "data", "stage113_lmev_judged.jsonl")
DEEPCOMBO_URL = "http://localhost:20128/v1/chat/completions"

# LongMemEval 공식 judge prompt (evaluate_qa.py get_anscheck_prompt 재현)
def judge_prompt(qtype, q, ans, hyp, abstention=False):
    if not abstention:
        t = ("I will give you a question, a correct answer, and a response from a model. "
             "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
             "If the response is equivalent to the correct answer or contains all the intermediate steps to get the correct answer, you should also answer yes. "
             "If the response only contains a subset of the information required by the answer, answer no.\n\n"
             f"Question: {q}\n\nCorrect Answer: {ans}\n\nModel Response: {hyp}\n\n"
             "Is the model response correct? Answer yes or no only.")
    else:
        t = ("I will give you an unanswerable question, an explanation, and a response from a model. "
             "Please answer yes if the model correctly identifies the question as unanswerable. "
             "The model could say that the information is incomplete, or some other information is given but the asked information is not.\n\n"
             f"Question: {q}\n\nExplanation: {ans}\n\nModel Response: {hyp}\n\n"
             "Does the model correctly identify the question as unanswerable? Answer yes or no only.")
    return t

def chat_once(prompt, retries=5):
    """9router deepcombo — 503 지수 백오프 재시도"""
    body = {"model": "deepcombo",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 10, "temperature": 0.0}
    for attempt in range(retries):
        try:
            req = urllib.request.Request(DEEPCOMBO_URL, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=90) as r:
                raw = r.read().decode()
            if raw.lstrip().startswith("{"):
                d = json.loads(raw.split("data:")[0])
            else:
                d = None
                for line in raw.splitlines():
                    line = line.strip()
                    if line.startswith("data:") and "[DONE]" not in line:
                        d = json.loads(line[5:].strip())
                        break
                if d is None:
                    raise ValueError(f"parse fail: {raw[:80]}")
            return d["choices"][0]["message"]["content"].strip().lower()
        except Exception as e:
            if attempt == retries - 1:
                return f"[ERR {e}]"
            time.sleep(1.5 * (2 ** attempt))
    return "[ERR]"

def judge_one(item):
    qid = item["question_id"]
    abstention = qid.endswith("_abs")
    qtype = item["question_type"]
    q = item.get("question", "")
    ans = item.get("answer", "")
    hyp = item.get("hypothesis") or ""
    prompt = judge_prompt(qtype, q, ans, hyp, abstention)
    resp = chat_once(prompt)
    label = "yes" in resp if not resp.startswith("[ERR") else None
    return {"question_id": qid, "question_type": qtype, "abstention": abstention,
            "model_answer": hyp[:200], "resp": resp, "label": label,
            "jev_idx": (item.get("jev") or {}).get("idx"),
            "jev_abstain": (item.get("jev") or {}).get("abstain"),
            "jev_abstain_p": (item.get("jev") or {}).get("abstain_p")}

def main():
    rows = [json.loads(l) for l in open(RESULTS, encoding="utf-8") if l.strip()]
    print(f"[inputs] {len(rows)}문항", flush=True)

    done = set()
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["question_id"])
                except Exception:
                    pass
    todo = [r for r in rows if r["question_id"] not in done]
    print(f"[resume] 완료 {len(done)} / 실행 {len(todo)}", flush=True)

    t0 = time.time()
    n_ok = 0
    # 병렬 6 (deepcombo 동시 6에서 503 나오므로 4로)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(judge_one, r): r for r in todo}
        for i, fut in enumerate(concurrent.futures.as_completed(futures)):
            res = fut.result()
            with open(OUT, "a", encoding="utf-8") as f:
                f.write(json.dumps(res, ensure_ascii=False) + "\n")
            if res["label"] is not None:
                n_ok += 1
            if (i + 1) % 25 == 0:
                el = time.time() - t0
                print(f"  [{i+1}/{len(todo)}] {el:.0f}s 경과, label={res['label']} resp={res['resp'][:40]!r}", flush=True)

    # 요약
    judged = [json.loads(l) for l in open(OUT, encoding="utf-8") if l.strip()]
    labeled = [j for j in judged if j["label"] is not None]
    import collections
    acc = sum(1 for j in labeled if j["label"]) / len(labeled) if labeled else 0
    by_type = collections.defaultdict(lambda: [0, 0])
    for j in labeled:
        by_type[j["question_type"]][1] += 1
        if j["label"]:
            by_type[j["question_type"]][0] += 1
    abs_j = [j for j in labeled if j["abstention"]]
    abs_acc = sum(1 for j in abs_j if j["label"]) / len(abs_j) if abs_j else 0
    print(f"\n[요약] 판정 {len(labeled)}/{len(judged)} 정확도 {acc*100:.1f}%")
    print(f"[요약] abstention {len(abs_j)}문항 정확도 {abs_acc*100:.1f}%")
    for t, (c, n) in sorted(by_type.items()):
        print(f"  {t}: {c}/{n} = {c/n*100:.1f}%")
    # jev abstain vs judge label 교차
    jev_abs = [j for j in labeled if j["jev_abstain"]]
    jev_abs_correct = sum(1 for j in jev_abs if j["label"])
    print(f"\n[JEV abstain 261건 중 judge 정답: {jev_abs_correct}/{len(jev_abs)} = {jev_abs_correct/len(jev_abs)*100:.1f}%")

if __name__ == "__main__":
    main()