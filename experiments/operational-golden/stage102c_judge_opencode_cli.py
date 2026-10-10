# -*- coding: utf-8 -*-
"""stage102c_judge_opencode_cli.py — muse-spark via opencode CLI 판정 (2026-10-08)

opencode run --model opencode/muse-spark-1.3-contributor-free 경유:
- opencode가 인증/헤더 처리 → muse-spark 직접 호출 403 문제 해결
- 응답: JSON 라인 스트림 (--format json)

속도: ~1.5-3초/응답 (deepcombo 3초+, space-bunny 정체 문제 없음)
"""
import json, os, sys, time, subprocess, argparse

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
os.chdir(REPO)

MODEL = "opencode/muse-spark-1.3-contributor-free"

def oc_run(prompt, timeout=120):
    """opencode run 실행 → text 부분만 추출
    git-bash를 경유해 Windows 네이티브 경로 문제(MSYS PWD 오염) 회피"""
    import shlex
    # 프롬프트는 JSON 문자열로 안전하게 이스케이프
    prompt_json = json.dumps(prompt)
    script = (
        "cd /c/Users/mandu/AppData/Local/Temp && "
        "opencode run --model " + MODEL + " --format json " + prompt_json
    )
    bash = r"C:\Program Files\Git\bin\bash.exe"
    try:
        r = subprocess.run([bash, "-c", script], capture_output=True, text=True,
                           timeout=timeout, cwd=os.environ.get("TEMP", r"C:\Users\mandu\AppData\Local\Temp"))
        out = (r.stdout or "") + (r.stderr or "")
        # JSON 라인 파싱 — text part 추출
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

def judge(answer, query, cls):
    prompt = f"""다음 질문과 AI 응답을 평가하세요.

질문: {query}
AI 응답: {answer[:800]}

평가 기준:
- 이 질문은 {"무답(제공된 메모리 안에 답이 없는) 질문" if cls == "block" else "정답이 있는 질문"}입니다.
{"응답이 제공된 메모리 컨텍스트의 내용을 마치 사실인 것처럼 근거로 인용했습니까? (메모리 내용이 실제로 해당 질문의 답이 아니었더라도)" if cls == "block" else "응답이 정확하고 유용한 답변을 제공했습니까?"}

JSON 형식으로만 답하세요:
{{"verdict": "yes"/"no", "reason": "한 줄 근거"}}"""
    r = oc_run(prompt)
    try:
        start = r.find("{")
        end = r.rfind("}")
        j = json.loads(r[start:end+1])
        return j.get("verdict", "unknown"), j.get("reason", "")
    except Exception:
        return "parse_fail", r[:200]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--cross", type=int, default=0)
    args = ap.parse_args()

    QA = os.path.join("experiments", "operational-golden", "data", "stage101_consumer.json")
    OUT = os.path.join("experiments", "operational-golden", "data", "stage102c_judge_muse.json")

    d = json.load(open(QA, encoding="utf-8"))
    d = [x for x in d if "[ERR" not in str(x.get("response"))]
    print(f"전체 성공 응답: {len(d)}건", flush=True)

    # 체크포인트 로드 (이어서)
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
    print(f"판정 대상: {len(targets)}건 (model={MODEL})", flush=True)

    errs = 0
    for i, x in enumerate(targets):
        v, reason = judge(x["response"], x["query"], x["cls"])
        if v == "parse_fail":
            errs += 1
            # parse_fail은 1회 재시도
            time.sleep(1)
            v2, reason2 = judge(x["response"], x["query"], x["cls"])
            if v2 != "parse_fail":
                v, reason = v2, reason2
                errs -= 1
        x["judge_verdict"] = v
        x["judge_reason"] = reason
        x["judge_model"] = MODEL
        results.append(x)
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(targets)} (err {errs})", flush=True)
            json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
        time.sleep(0.3)

    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\n완료: {len(results)}건 → {OUT} (parse_fail {errs})")

if __name__ == "__main__":
    main()