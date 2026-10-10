# -*- coding: utf-8 -*-
"""stage102e_judge_fledge_parallel.py — fledge-alpha-free 2워커 병렬 판정 (2026-10-08)

opencode CLI 경유 fledge-alpha-free:
- 429 없이 사용 가능한 무료 모델 (space-bunny/muse-spark 소진 후 확인됨)
- 2워커 병렬 (폭주 방지, Retry-After·429 즉시 중단)

핵심 절차 교훈 반영:
1. 유일 키 (query,k,framing,sample) — 중복 방지
2. 429/FreeUsageLimitError 감지 → 즉시 전체 중단
3. 체크포인트 25건마다 저장 → 재개 가능
"""
import json, os, sys, time, subprocess, argparse, threading
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
os.chdir(REPO)

MODEL = "opencode/fledge-alpha-free"
BASH = r"C:\Program Files\Git\bin\bash.exe"
TEMP = r"C:\Users\mandu\AppData\Local\Temp"
CONFIG = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\opencode_judge_config.json"
OUT = os.path.join("experiments", "operational-golden", "data", "stage102e_judge_fledge.json")
QA = os.path.join("experiments", "operational-golden", "data", "stage101_consumer.json")

_lock = threading.Lock()
_stop = threading.Event()   # 429 발생 시 전체 중단

def oc_run(prompt, timeout=120):
    if _stop.is_set():
        return "[ERR stopped]"
    # 프롬프트를 임시 파일로 전달 — 백틱/$ 등 쉘 메타문자 해석 원천 차단 (2026-10-08 실측 버그)
    import uuid
    pf_name = f"judge_prompt_{uuid.uuid4().hex[:12]}.txt"
    pf_native = os.path.join(TEMP, pf_name)
    with open(pf_native, "w", encoding="utf-8") as f:
        f.write(prompt)
    pf_unix = "/c/Users/mandu/AppData/Local/Temp/" + pf_name
    script = (
        f"cd {TEMP.replace(chr(92), '/')} && "
        "OPENCODE_CONFIG=" + json.dumps(CONFIG.replace("\\", "/")) + " "
        "opencode run --model " + MODEL + " --format json " + f'\"$(cat {pf_unix})\"'
    )
    try:
        r = subprocess.run([BASH, "-c", script], capture_output=True, text=True,
                           timeout=timeout, cwd=TEMP)
        out = (r.stdout or "") + (r.stderr or "")
        # 정밀한 rate limit 감지 (naive "429" 매치는 stderr 노이즈를 오탐함 — 2026-10-08 실측)
        if ("FreeUsageLimitError" in out or "Rate limit exceeded" in out
                or '"type":"provider.quota"' in out):
            _stop.set()
            return "[ERR 429]"
        texts = []
        for line in out.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                d = json.loads(line)
                if d.get("type") == "text":
                    texts.append(d["part"]["text"])
            except Exception:
                continue
        return "\n".join(texts) if texts else f"[ERR no text] {out[:200]}"
    except subprocess.TimeoutExpired:
        return "[ERR timeout]"
    except Exception as e:
        return f"[ERR {e}]"
    finally:
        try:
            os.remove(pf_native)
        except Exception:
            pass

def judge_one(x):
    def _build_prompt(_x):
        cls = _x["cls"]
        q = _x["query"]
        ans = str(_x["response"])[:800]
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
    prompt = _build_prompt(x)
    r = oc_run(prompt)
    try:
        start = r.find("{")
        end = r.rfind("}")
        j = json.loads(r[start:end+1])
        return j.get("verdict", "unknown"), j.get("reason", "")
    except Exception:
        # 재시도 1회 (429 아니면)
        if _stop.is_set():
            return "parse_fail", r[:200]
        time.sleep(2)
        r2 = oc_run(prompt)
        try:
            start = r2.find("{")
            end = r2.rfind("}")
            j = json.loads(r2[start:end+1])
            return j.get("verdict", "unknown"), j.get("reason", "")
        except Exception:
            return "parse_fail", r2[:200]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    d = json.load(open(QA, encoding="utf-8"))
    d = [x for x in d if "[ERR" not in str(x.get("response"))]
    if args.limit:
        d = d[:args.limit]
    print(f"전체 성공 응답: {len(d)}건", flush=True)

    done_keys = set()
    results = []
    if os.path.exists(OUT):
        try:
            results = json.load(open(OUT, encoding="utf-8"))
            done_keys = {(x["query"], x["k"], x["framing"], x.get("sample")) for x in results}
            print(f"체크포인트: {len(results)}건", flush=True)
        except Exception:
            results = []

    targets = [x for x in d if (x["query"], x["k"], x["framing"], x.get("sample")) not in done_keys]
    print(f"판정 대상: {len(targets)}건 (model={MODEL}, workers={args.workers})", flush=True)

    errs = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(judge_one, x): x for x in targets}
        for i, fut in enumerate(as_completed(futs)):
            x = futs[fut]
            try:
                v, reason = fut.result()
            except Exception as e:
                v, reason = "parse_fail", f"[ERR {e}]"
            if v == "parse_fail":
                errs += 1
            x["judge_verdict"] = v
            x["judge_reason"] = reason
            x["judge_model"] = MODEL
            with _lock:
                results.append(x)
                if (i + 1) % 25 == 0:
                    el = time.time() - t0
                    rate = (i + 1) / el * 60
                    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
                    print(f"  {i+1}/{len(targets)} (err {errs}) {rate:.0f}건/분", flush=True)
            if _stop.is_set():
                print("⚠ 429 감지 — 즉시 중단", flush=True)
                break

    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    el = time.time() - t0
    print(f"\n완료: {len(results)}건 → {OUT} (parse_fail {errs}, {el/60:.1f}분)", flush=True)

if __name__ == "__main__":
    main()