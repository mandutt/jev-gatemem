# -*- coding: utf-8 -*-
"""stage103_paired_k2_framing.py — k=2 framing 페어드 추가 실험 (2026-10-10)

목적: k=2에서 fF(무프레이밍) vs fT(프레이밍) 메모리 인용 차이를 통계적으로 검정.
- 60개 질문 전체 (block 38 + yes 17 + valid 5) — 기존 180쌍에 신규 180쌍 추가 (총 360쌍)
- 각 질문 fF/fT × 3샘플 = 6건 → 총 360건
- 응답: deepcombo (기존과 동일), JEV 재호출로 pick 결정 (운영과 동일)
- 판정: tokenharbor/claude-haiku-5.5:free (배치 5)
"""
import os, sys, json, time, argparse, csv, io

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)

import urllib.request
import stage48_live60_cross as m48
import gateway.j1_pipeline as j1p
from jev_mem_core.pipeline import _jev_client
from canary_run import build_pool_prodex, ABSTAIN_CUR, INSTR
from core import j1_engine
from stage101_consumer_rerun import run_choice_full, build_prompt, chat

def load_key():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as k:
            for name in ("EXPLABS_API_KEY", "TYPESAFE_API_KEY"):
                try:
                    v, _ = winreg.QueryValueEx(k, name)
                    if v and not os.environ.get(name):
                        os.environ[name] = v
                except OSError:
                    pass
    except Exception:
        pass

load_key()
CLIENT = _jev_client()
assert CLIENT, "EXPLABS_API_KEY 필요"

JUDGE_URL = "http://localhost:20128/v1/chat/completions"
JUDGE_MODEL = "tokenharbor/claude-haiku-5.5:free"

def judge_batch(items, retries=2):
    lines = []
    for idx, x in enumerate(items):
        lines.append(f"[{idx}] 질문: {x['query']}\n    AI 응답: {str(x['response'])[:600]}\n    이 질문은 정답이 있는 질문입니다.")
    prompt = ("다음 각 항목의 AI 응답을 평가하세요.\n\n" + "\n\n".join(lines) +
              "\n\n판정 기준: 응답이 **사용자 고유의 특정 정보**(파일 경로, 설정 값, 실험 수치, 과거 사건/결론, 사용자 고유 규칙)를 구체적으로 인용했는가? 일반 지식/추론으로도 답할 수 있는 내용만 있으면 no.\n"
              '각 항목에 대해 JSON 배열로만 답하세요: [{"i": 0, "verdict": "yes/no", "reason": "한 줄"}, ...] (verdict는 "yes" 또는 "no"만, reason은 한 줄, 다른 텍스트 금지)')
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
                time.sleep(30); continue
            return {}
        except Exception:
            time.sleep(3)
    return {}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60, help="질문 수 (기본 60 전체)")
    ap.add_argument("--samples", type=int, default=3)
    args = ap.parse_args()

    out_dir = os.path.join("experiments", "operational-golden", "data")
    QA_OUT = os.path.join(out_dir, "stage103_paired.json")
    JUDGE_OUT = os.path.join(out_dir, "stage103_paired_judge.json")

    # 1) 60개 질문 전체 선별 (stage101 고유 질문)
    d101 = json.load(open(os.path.join(out_dir, "stage101_consumer.json"), encoding="utf-8"))
    uniq = {}
    for x in d101:
        uniq.setdefault(x["query"], x["cls"])
    queries = list(uniq.keys())[:args.limit]
    print(f"질문 {len(queries)}개 (전체 {len(uniq)}개)", flush=True)

    # 2) JEV 재호출 (pick 결정) — 캐시/체크포인트
    JEV_CACHE = os.path.join(out_dir, "stage103_jev.json")
    jev_map = {}
    if os.path.exists(JEV_CACHE):
        try:
            for r in json.load(open(JEV_CACHE, encoding="utf-8")):
                jev_map[r["q"]] = r
        except Exception:
            pass
    for i, q in enumerate(queries):
        if q in jev_map:
            continue
        r = run_choice_full(q)
        r["q"] = q
        jev_map[q] = r
        if (i+1) % 10 == 0:
            print(f"  JEV {i+1}/{len(queries)} err={r.get('err')} ap={r.get('abstain_p',0):.2f}", flush=True)
        json.dump(list(jev_map.values()), open(JEV_CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"JEV 완료: {len(jev_map)}콜", flush=True)

    # 3) 소비 QA: fF/fT × 3샘플
    results = []
    temps = [0.2, 0.5, 0.8]
    for i, q in enumerate(queries):
        jr = jev_map[q]
        ordered = jr.get("ordered") or []
        rows_k = ordered[:2]  # k=2
        for framing in (False, True):
            for ti, temp in enumerate(temps):
                prompt = build_prompt(q, rows_k, framing)
                ans = chat(prompt, temperature=temp)
                results.append({"i": i, "query": q, "cls": "yes",
                                "k": 2, "framing": framing, "sample": ti, "temp": temp,
                                "pick_id": jr.get("pick_id"), "abstain_p": jr.get("abstain_p"),
                                "response": ans})
        if (i+1) % 5 == 0:
            print(f"  QA {i+1}/{len(queries)} ({len(results)}건)", flush=True)
            json.dump(results, open(QA_OUT, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(results, open(QA_OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"QA 완료: {len(results)}건 → {QA_OUT}", flush=True)

    # 4) claude-haiku 판정 (배치 5, 2워커)
    judged = []
    if os.path.exists(JUDGE_OUT):
        try:
            judged = json.load(open(JUDGE_OUT, encoding="utf-8"))
        except Exception:
            pass
    done = {(x["query"], x["framing"], x["sample"]) for x in judged if x.get("verdict") in ("yes","no")}
    targets = [x for x in results if (x["query"], x["framing"], x["sample"]) not in done]
    if targets:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        pending = targets
        t0 = time.time()
        while pending:
            next_pending = []
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
                            next_pending.append(x)
            pending = next_pending
            if pending:
                print(f"  🔄 판정 재시도: {len(pending)}건", flush=True)
        json.dump(judged, open(JUDGE_OUT, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"판정 완료: {len(judged)}건 ({time.time()-t0:.0f}초)", flush=True)
    else:
        print(f"판정 체크포인트: {len(judged)}건 (변화 없음)", flush=True)

if __name__ == "__main__":
    main()