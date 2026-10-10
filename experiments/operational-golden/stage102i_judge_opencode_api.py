# -*- coding: utf-8 -*-
"""stage102i_judge_opencode_api.py — opencode 서버 API 직접 호출 판정 (2026-10-08)

핵심: opencode CLI 프로세스를 스폰하지 않고, 로컬 서버(127.0.0.1:49374)의
HTTP API로 세션 생성 → 프롬프트 → SSE로 응답 수신.
- 서버가 zen 인증(TLS 지문+세션)을 담당 → 403 게이트 통과
- 프로세스 스폰 없음 → 교착/과부하 문제 원천 제거
- 429는 서버가 처리하며, SSE에서 에러 이벤트로 수신

인증: Basic (opencode:service.json password) + x-opencode-ticket: 1
"""
import json, os, sys, time, urllib.request, urllib.error, uuid, ssl, base64
import threading, queue

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
os.chdir(REPO)

SERVER = "http://127.0.0.1:49374"
SERVICE_JSON = os.path.expanduser(r"~\.config\opencode\service.json")
OUT = os.path.join("experiments", "operational-golden", "data", "stage102i_judge_api.json")
QA = os.path.join("experiments", "operational-golden", "data", "stage101_consumer.json")
MODEL = "space-bunny-free"   # 200 확인된 모델 (서버 경유라 다른 모델도 가능할 수 있음)

def auth_header():
    pw = json.load(open(SERVICE_JSON, encoding="utf-8"))["password"]
    token = base64.b64encode(f"opencode:{pw}".encode()).decode()
    return {"Authorization": f"Basic {token}", "x-opencode-ticket": "1",
            "Content-Type": "application/json"}

def api(method, path, body=None, timeout=30):
    req = urllib.request.Request(SERVER + path, method=method,
                                 headers=auth_header(),
                                 data=json.dumps(body).encode() if body else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_msg": e.read().decode()[:200]}
    except Exception as e:
        return {"_error": "ERR", "_msg": str(e)[:200]}

def create_session(title="judge"):
    d = api("POST", "/api/session", {"title": title, "model": {"id": MODEL, "providerID": "opencode"}})
    if "_error" in d:
        return None, d
    return d["data"]["id"], d

def send_prompt(sid, text, timeout=120):
    """프롬프트 전송 후 SSE poll로 응답 수신"""
    # SSE 스트림을 스레드로 열어 이벤트 수집
    result_q = queue.Queue()
    stop = threading.Event()

    def sse_listen():
        try:
            req = urllib.request.Request(SERVER + "/api/event", method="GET", headers=auth_header())
            with urllib.request.urlopen(req, timeout=timeout + 10) as r:
                buf = b""
                while not stop.is_set():
                    chunk = r.read(4096)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n\n" in buf:
                        raw, buf = buf.split(b"\n\n", 1)
                        text = raw.decode("utf-8", "replace")
                        if text.startswith("data: "):
                            try:
                                evt = json.loads(text[6:])
                                result_q.put(evt)
                            except Exception:
                                pass
        except Exception as e:
            result_q.put({"_sse_err": str(e)})

    t = threading.Thread(target=sse_listen, daemon=True)
    t.start()
    time.sleep(0.5)  # SSE 연결 대기

    # 프롬프트 전송
    api("POST", f"/api/session/{sid}/prompt", {"text": text}, timeout=30)

    # 해당 세션의 assistant 메시지 이벤트 대기
    deadline = time.time() + timeout
    texts = []
    while time.time() < deadline:
        try:
            evt = result_q.get(timeout=3)
        except queue.Empty:
            continue
        et = evt.get("type", "")
        data = evt.get("data", {})
        if et == "session.message" and data.get("sessionID") == sid:
            msg = data.get("message", {})
            if msg.get("type") == "assistant":
                payload = msg.get("payload", {})
                # parts 형식
                parts = payload.get("parts", []) if isinstance(payload, dict) else []
                for p in parts:
                    if p.get("type") == "text":
                        texts.append(p.get("text", ""))
                if texts or payload.get("done"):
                    break
        elif et in ("session.error", "session.aborted"):
            texts.append(f"[{et}] {str(data)[:100]}")
            # 429 등
            break
    stop.set()
    return "\n".join(texts)

def build_prompt(x):
    cls = x["cls"]
    q = x["query"]
    ans = str(x["response"])[:800]
    judge_cls = "무답(제공된 메모리 안에 답이 없는) 질문" if cls == "block" else "정답이 있는 질문"
    judge_q = ("응답이 제공된 메모리 컨텍스트의 내용을 마치 사실인 것처럼 근거로 인용했습니까?"
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
    sid, err = create_session()
    if not sid:
        return "parse_fail", f"session_err: {err}", None
    try:
        prompt = build_prompt(x)
        resp = send_prompt(sid, prompt)
        # JSON 파싱
        start = resp.find("{")
        end = resp.rfind("}")
        j = json.loads(resp[start:end+1])
        v = j.get("verdict", "")
        if v in ("yes", "no"):
            return v, j.get("reason", ""), "opencode-api"
        return "parse_fail", f"badverdict:{resp[:120]}", "opencode-api"
    except Exception as e:
        return "parse_fail", f"parse:{resp[:120] if 'resp' in dir() else str(e)}", "opencode-api"
    finally:
        # 세션 정리
        api("DELETE", f"/api/session/{sid}")

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    d = json.load(open(QA, encoding="utf-8"))
    d = [x for x in d if "[ERR" not in str(x.get("response"))]
    if args.limit:
        d = d[:args.limit]
    print(f"전체: {len(d)}건", flush=True)

    done_keys = set()
    results = []
    if os.path.exists(OUT):
        try:
            results = json.load(open(OUT, encoding="utf-8"))
            done_keys = {(x["query"], x["k"], x["framing"], x.get("sample")) for x in results}
            print(f"체크포인트: {len(results)}건", flush=True)
        except Exception:
            pass

    targets = [x for x in d if (x["query"], x["k"], x["framing"], x.get("sample")) not in done_keys]
    print(f"대상: {len(targets)}건 (opencode API, model={MODEL})", flush=True)

    errs = 0
    t0 = time.time()
    for i, x in enumerate(targets):
        v, reason, jm = judge_one(x)
        if v == "parse_fail":
            errs += 1
        x["judge_verdict"] = v
        x["judge_reason"] = reason
        x["judge_model"] = jm
        results.append(x)
        if (i + 1) % 10 == 0:
            el = time.time() - t0
            rate = (i + 1) / el * 60
            json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"  {i+1}/{len(targets)} (err {errs}) {rate:.1f}건/분", flush=True)

    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    el = time.time() - t0
    print(f"\n완료: {len(results)}건 (err {errs}, {el/60:.1f}분)", flush=True)

if __name__ == "__main__":
    main()