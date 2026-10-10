# -*- coding: utf-8 -*-
"""stage102h_judge_fixed_workers.py — 모델별 고정 워커 병렬 판정 (2026-10-08)

전략 (사용자 제안 2026-10-08):
- 활성 모델 2개(nemotron-3-ultra, nemotron-3.5-lightning): 각 2워커
- 나머지 free 모델: 각 1워커
- 모델별 고정 워커 → 429 상호 간섭 제거

구현:
- 모델당 전용 ThreadPoolExecutor + 전용 작업 큐
- 한 모델 429면 해당 워커만 쿨다운, 다른 모델 워커는 계속
- 체크포인트 25건마다 저장
"""
import json, os, sys, time, subprocess, argparse, threading, uuid, queue
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
os.chdir(REPO)

# ★2026-10-08 실측 정책:
# - opencode 동시 호출 한계: 2 (그 이상은 교착) → 워커 총 2개 고정
# - 무료 모델별 일일 할당량 소진(429) 반복 → 워커가 모델 목록을 순차 시도 (로테이션)
# - 쿨다운(600s) 지난 모델은 자동 재시도
ACTIVE_MODELS = [
    "opencode/nemotron-3.5-lightning-free",
    "opencode/nemotron-3-ultra-free",
    "opencode/longcat-2.5-preview-free",
    "opencode/ling-3.1-flash-free",
    "opencode/fledge-alpha-free",
    "opencode/mimo-v2.6-flash-free",
    "opencode/ling-3.0-flash-fin-free",
    "opencode/exo-free",
    "opencode/space-bunny-free",
    "opencode/muse-spark-1.3-contributor-free",
]
NUM_WORKERS = 2

# (호환용) — main에서 ACTIVE_MODELS/NUM_WORKERS를 사용
MODEL_WORKERS = {m: (1 if i < NUM_WORKERS else 0) for i, m in enumerate(ACTIVE_MODELS)}
BASH = r"C:\Program Files\Git\bin\bash.exe"
TEMP = r"C:\Users\mandu\AppData\Local\Temp"
CONFIG = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\opencode_judge_config.json"
OUT = os.path.join("experiments", "operational-golden", "data", "stage102h_judge_fixed.json")
QA = os.path.join("experiments", "operational-golden", "data", "stage101_consumer.json")

COOLDOWN = 600  # 429 쿨다운 10분

_lock = threading.Lock()
_model_lock = threading.Lock()
_cool = {m: 0.0 for m in MODEL_WORKERS}   # 429 쿨다운 시각
_count = {m: {"ok": 0, "fail": 0} for m in MODEL_WORKERS}

def oc_run(model, prompt, timeout=120):
    with _model_lock:
        if _cool[model] > time.time():
            return "[COOLING]"
    pf_name = f"judge_prompt_{uuid.uuid4().hex[:12]}.txt"
    pf_native = os.path.join(TEMP, pf_name)
    with open(pf_native, "w", encoding="utf-8") as f:
        f.write(prompt)
    pf_unix = "/c/Users/mandu/AppData/Local/Temp/" + pf_name
    script = (
        f"cd {TEMP.replace(chr(92), '/')} && "
        "OPENCODE_CONFIG=" + json.dumps(CONFIG.replace("\\", "/")) + " "
        "opencode run --model " + model + " --format json " + f'\"$(cat {pf_unix})\"'
    )
    try:
        r = subprocess.run([BASH, "-c", script], capture_output=True, text=True,
                           timeout=timeout, cwd=TEMP)
        out = (r.stdout or "") + (r.stderr or "")
        if ("FreeUsageLimitError" in out or "Rate limit exceeded" in out
                or '"type":"provider.quota"' in out or '"status":429' in out):
            with _model_lock:
                _cool[model] = time.time() + COOLDOWN
                _count[model]["fail"] += 1
            return "[REAL429]"
        if '"type":"provider.auth"' in out:
            # 일시적 인증 오류 (서비스 재시작으로 복구됨 — 2026-10-08 실측) → 짧은 쿨다운
            with _model_lock:
                _cool[model] = time.time() + 120
                _count[model]["fail"] += 1
            return "[REAL429]"
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

def judge_with_model(model, x):
    """특정 모델로 판정 — 429면 쿨다운 반환"""
    prompt = build_prompt(x)
    r = oc_run(model, prompt)
    if r == "[REAL429]" or r == "[COOLING]":
        return "parse_fail", r, model
    try:
        start = r.find("{")
        end = r.rfind("}")
        j = json.loads(r[start:end+1])
        v = j.get("verdict", "")
        if v in ("yes", "no"):
            with _model_lock:
                _count[model]["ok"] += 1
            return v, j.get("reason", ""), model
        return "parse_fail", f"badverdict:{r[:80]}", model
    except Exception:
        return "parse_fail", r[:200], model

def judge_any(x, active_models):
    """활성 모델 중 하나로 판정 — 429/쿨다운인 모델은 건너뛰고 다음 활성 모델로"""
    prompt = build_prompt(x)
    for model in active_models:
        with _model_lock:
            if _cool[model] > time.time():
                continue
        r = oc_run(model, prompt)
        if r == "[REAL429]" or r == "[COOLING]":
            continue
        try:
            start = r.find("{")
            end = r.rfind("}")
            j = json.loads(r[start:end+1])
            v = j.get("verdict", "")
            if v in ("yes", "no"):
                with _model_lock:
                    _count[model]["ok"] += 1
                return v, j.get("reason", ""), model
            return "parse_fail", f"badverdict:{r[:80]}", model
        except Exception:
            return "parse_fail", r[:200], model
    # 전부 쿨다운 — 쿨다운 만료까지 대기 후 재시도 (재귀)
    with _model_lock:
        wait = max(0.0, min(_cool[m] for m in active_models) - time.time())
    if wait > 0:
        time.sleep(min(wait + 1, 60))
    return judge_any(x, active_models)

def worker_loop(active_models, in_q, out_q, stop_event):
    """공유 워커 — 활성 모델 풀에서 살아있는 모델로 판정"""
    while not stop_event.is_set():
        try:
            x = in_q.get(timeout=2)
        except queue.Empty:
            if stop_event.is_set():
                break
            continue
        if x is None:
            break
        v, reason, m = judge_any(x, active_models)
        out_q.put((x, v, reason, m))
        in_q.task_done()

def main():
    ap = argparse.ArgumentParser()
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
    print(f"판정 대상: {len(targets)}건", flush=True)
    print(f"모델별 워커: { {m.split('/')[-1]: w for m, w in MODEL_WORKERS.items()} }", flush=True)

    # 공유 작업 큐 + 워커 2개. 워커는 ACTIVE_MODELS 전체를 순차 시도 (429 로테이션)
    active_models = ACTIVE_MODELS
    in_q = queue.Queue()
    out_q = queue.Queue()
    stop_event = threading.Event()

    # 워커 스레드 시작 (NUM_WORKERS 고정 — opencode 동시 호출 한계 2)
    workers = []
    for _ in range(NUM_WORKERS):
        t = threading.Thread(target=worker_loop, args=(active_models, in_q, out_q, stop_event), daemon=True)
        t.start()
        workers.append(t)

    # 작업 분배 (공유 큐)
    for x in targets:
        in_q.put(x)

    # 결과 수집
    errs = 0
    t0 = time.time()
    completed = 0
    while completed < len(targets):
        try:
            x, v, reason, m = out_q.get(timeout=5)
        except queue.Empty:
            # 전 모델 쿨다운이면 대기
            if all(_cool[m] > time.time() for m in active_models):
                time.sleep(5)
            continue
        if v == "parse_fail":
            errs += 1
        x["judge_verdict"] = v
        x["judge_reason"] = reason
        x["judge_model"] = m
        with _lock:
            results.append(x)
            completed += 1
            if completed % 25 == 0:
                el = time.time() - t0
                rate = completed / el * 60
                json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
                with _model_lock:
                    st = {mm.split("/")[-1]: _count[mm]["ok"] for mm in active_models}
                print(f"  {completed}/{len(targets)} (err {errs}) {rate:.1f}건/분 | {st}", flush=True)

    stop_event.set()
    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    el = time.time() - t0
    with _model_lock:
        st = {mm.split("/")[-1]: (_count[mm]["ok"], _count[mm]["fail"]) for mm in active_models}
    print(f"\n완료: {len(results)}건 → {OUT} (parse_fail {errs}, {el/60:.1f}분)", flush=True)
    print(f"모델별 (ok, fail): {st}", flush=True)

if __name__ == "__main__":
    main()