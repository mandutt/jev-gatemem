# -*- coding: utf-8 -*-
"""stage108_k3_3run.py — k=3 정답 활용률 3-run 안정성 실측 (2026-10-10)

stage107(k=3 정답 활용 88.2%, 1회)의 안정성 확인.
- run1: 기존 stage107 결과 재사용 (deepcombo 응답 + claude 판정)
- run2/run3: deepcombo 재생성(새 응답) + claude 재판정 — 온도 0.2 동일
- JEV choice 결과(stage93_jev_rows.json)는 결정적이므로 재호출 없음 (3-run 공통)
- 지표: yes/valid 정답 활용률이 run 간 얼마나 안정적인가 (stage92 선례)

실행: python stage108_k3_3run.py [--limit N]  (deepcombo ~120콜 + claude 판정 24콜)
"""
import os, sys, json, time, argparse, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)

from stage101_consumer_rerun import chat  # deepcombo
import stage107_k3_answer_util as s107  # build_prompt, judge_batch, JUDGE_*

DATA = os.path.join("experiments", "operational-golden", "data")
JEV_ROWS = os.path.join(DATA, "stage93_jev_rows.json")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--run", type=int, default=0, help="2 또는 3 (1은 기존 결과)")
    args = ap.parse_args()

    assert args.run in (0, 2, 3), "run은 0(양쪽 모두), 2, 3만"
    jev_rows = json.load(open(JEV_ROWS, encoding="utf-8"))
    if args.limit:
        jev_rows = jev_rows[:args.limit]
    print(f"대상: {len(jev_rows)}건 (run={args.run or '2+3'})", flush=True)

    runs = [2, 3] if args.run == 0 else [args.run]
    for run in runs:
        t0 = time.time()
        QA_OUT = os.path.join(DATA, f"stage108_k3_run{run}.json")
        JDG_OUT = os.path.join(DATA, f"stage108_k3_run{run}_judge.json")

        # 1) deepcombo 응답 생성 (체크포인트)
        results = []
        if os.path.exists(QA_OUT):
            try:
                results = json.load(open(QA_OUT, encoding="utf-8"))
            except Exception:
                pass
        done = {x["query"] for x in results}
        for i, jr in enumerate(jev_rows):
            q = jr["q"]
            if q in done:
                continue
            rows = jr.get("rows") or []
            ans = chat(s107.build_prompt(q, 3, False, rows))
            results.append({"i": i, "query": q, "cls": jr.get("cls"),
                            "k": 3, "framing": False,
                            "jev_idx": jr.get("idx"), "abstain_p": jr.get("abstain_p"),
                            "response": ans})
            if (i + 1) % 15 == 0:
                print(f"  run{run} QA {i+1}/{len(jev_rows)} ({time.time()-t0:.0f}초)", flush=True)
                json.dump(results, open(QA_OUT, "w", encoding="utf-8"), ensure_ascii=False)
        json.dump(results, open(QA_OUT, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"run{run} QA: {len(results)}건 ({time.time()-t0:.0f}초)", flush=True)

        # 2) claude 판정 (체크포인트)
        judged = []
        if os.path.exists(JDG_OUT):
            try:
                judged = json.load(open(JDG_OUT, encoding="utf-8"))
            except Exception:
                pass
        done_j = {x["query"] for x in judged if x.get("verdict") in ("yes", "no")}
        targets = [x for x in results if x["query"] not in done_j]
        pending = targets
        while pending:
            next_p = []
            batches = [pending[i:i+5] for i in range(0, len(pending), 5)]
            with ThreadPoolExecutor(max_workers=2) as ex:
                futs = {ex.submit(s107.judge_batch, b): b for b in batches}
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
                print(f"  run{run} 판정 재시도: {len(pending)}건", flush=True)
        json.dump(judged, open(JDG_OUT, "w", encoding="utf-8"), ensure_ascii=False)

        # 3) 요약
        yes = [x for x in judged if x.get("cls") in ("yes", "valid") and x.get("verdict") in ("yes", "no")]
        if yes:
            n_yes = sum(1 for x in yes if x["verdict"] == "yes")
            print(f"run{run}: 정답 활용 {n_yes}/{len(yes)} ({n_yes/len(yes)*100:.1f}%)", flush=True)
        bl = [x for x in judged if x.get("cls") == "block" and x.get("verdict") in ("yes", "no")]
        if bl:
            n_bl = sum(1 for x in bl if x["verdict"] == "yes")
            print(f"run{run}: block 환각(인용) {n_bl}/{len(bl)} ({n_bl/len(bl)*100:.1f}%)", flush=True)

if __name__ == "__main__":
    main()