# -*- coding: utf-8 -*-
"""stage102g_judge_rotation.py — opencode 무료 모델 로테이션 판정 (2026-10-08)

문제: 모든 무료 모델에 일일 할당량(429 provider.quota)이 있고, 단일 모델로
1,074건을 끝낼 수 없음 (실측: fledge 87건, ling 44건에서 소진).

해법: 10개 무료 모델을 로테이션. 한 모델이 429면 쿨다운 후 다음 모델로.
- 실측 429만 감지 (stderr 'line 429' 노이즈 오탐 방지 — 2026-10-08)
- 프롬프트는 임시 파일로 전달 (백틱/특수문자 쉘 해석 방지 — 2026-10-08)
- 체크포인트 25건마다, judge_model 기록 → 판정자별 교차 분석 가능
"""
import json, os, sys, time, subprocess, argparse, threading, uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
os.chdir(REPO)

MODELS = [
    "opencode/nemotron-3.5-lightning-free",
    "opencode/longcat-2.5-preview-free",
    "opencode/ling-3.1-flash-free",
    "opencode/fledge-alpha-free",
    "opencode/nemotron-3-ultra-free",
    "opencode/exo-free",
    "opencode/ling-3.0-flash-fin-free",
    "opencode/mimo-v2.6-flash-free",
    "opencode/space-bunny-free",
    "opencode/muse-spark-1.3-contributor-free",
]
BASH = r"C:\Program Files\Git\bin\bash.exe"
TEMP = r"C:\Users\mandu\AppData\Local\Temp"
CONFIG = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\opencode_judge_config.json"
OUT = os.path.join("experiments", "operational-golden", "data", "stage102g_judge_rotation.json")
QA = os.path.join("experiments", "operational-golden", "data", "stage101_consumer.json")

COOLDOWN = 900   # 429 모델 쿨다운 15분 (그 사이 다른 모델로)

_lock = threading.Lock()
_model_lock = threading.Lock()
_model_state = {m: {"cool_until": 0.0, "ok": 0, "fail": 0} for m in MODELS}

def pick_model(exclude):
    now = time.time()
    with _model_lock:
        healthy = [m for m in MODELS if _model_state[m]["cool_until"] <= now and m not in exclude]
        if not healthy:
            return None
        # 성공 횟수 적은 모델 우선 (균등 분배)
        return min(healthy, key=lambda m: _model_state[m]["ok"])

def oc_run(model, prompt, timeout=120):
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
                or '"type":"provider.quota"' in out):
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

def judge_one(x):
    """모델 로테이션으로 판정 — 429 모델은 쿨다운, 성공까지 다음 모델 시도"""
    prompt = build_prompt(x)
    tried = set()
    last_err = None
    while len(tried) < len(MODELS):
        m = pick_model(tried)
        if m is None:
            time.sleep(20)   # 전 모델 쿨다운 — 대기 후 재시도
            continue
        tried.add(m)
        r = oc_run(m, prompt)
        if r == "[REAL429]":
            with _model_lock:
                _model_state[m]["cool_until"] = time.time() + COOLDOWN
                _model_state[m]["fail"] += 1
            last_err = f"429:{m}"
            continue
        # 파싱
        try:
            start = r.find("{")
            end = r.rfind("}")
            j = json.loads(r[start:end+1])
            v = j.get("verdict", "")
            if v in ("yes", "no"):
                with _model_lock:
                    _model_state[m]["ok"] += 1
                return v, j.get("reason", ""), m
            last_err = f"badverdict:{m}:{r[:80]}"
        except Exception:
            last_err = f"parse:{m}:{r[:80]}"
        # 파싱 실패면 다음 모델로 (재시도 낭비 방지)
    return "parse_fail", str(last_err)[:200], None

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
    print(f"판정 대상: {len(targets)}건 (rotation {len(MODELS)}모델, workers={args.workers})", flush=True)

    errs = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(judge_one, x): x for x in targets}
        for i, fut in enumerate(as_completed(futs)):
            x = futs[fut]
            try:
                v, reason, jm = fut.result()
            except Exception as e:
                v, reason, jm = "parse_fail", f"[ERR {e}]", None
            if v == "parse_fail":
                errs += 1
            x["judge_verdict"] = v
            x["judge_reason"] = reason
            x["judge_model"] = jm
            with _lock:
                results.append(x)
                if (i + 1) % 25 == 0:
                    el = time.time() - t0
                    rate = (i + 1) / el * 60
                    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
                    with _model_lock:
                        st = {m.split("/")[-1]: s["ok"] for m, s in _model_state.items() if s["ok"]}
                    print(f"  {i+1}/{len(targets)} (err {errs}) {rate:.1f}건/분 | {st}", flush=True)

    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    el = time.time() - t0
    with _model_lock:
        st = {m.split("/")[-1]: (s["ok"], s["fail"]) for m, s in _model_state.items()}
    print(f"\n완료: {len(results)}건 → {OUT} (parse_fail {errs}, {el/60:.1f}분)", flush=True)
    print(f"모델별 (ok, fail): {st}", flush=True)

if __name__ == "__main__":
    main()