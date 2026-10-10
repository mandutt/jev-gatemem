# -*- coding: utf-8 -*-
"""stage102m_judge_api_resume.py — opencode 서버 API로 잔여 판정 (2026-10-09)

경로: space-bunny 직접 HTTP 429 소진(Retry-After ~22h, 640건 판정 후).
→ 서버 API(127.0.0.1:49374)가 zen 인증 위임 + nemotron-3-ultra-free 응답 확인(2026-10-09).
이 러너는 stage102k(space-bunny)의 잔여 건을 서버 API + nemotron-3-ultra-free로 판정한다.

- 병렬 2 세션 (동시 3건 프로브: 3번째 21.5s 지연 → 2로 제한)
- poll 방식: 프롬프트 후 GET /api/session/{id}/message 3초 간격
- content[].text 수집 (reasoning 무시)
- 체크포인트 5건마다 저장, 타임아웃/에러는 [ERR]로 남기고 다음 라운드 재시도 (최대 3라운드)
"""
import json, os, sys, time, base64, threading, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
os.chdir(REPO)

SERVER = "http://127.0.0.1:49374"
SERVICE_JSON = os.path.expanduser(r"~\.config\opencode\service.json")
MODEL = "nemotron-3-ultra-free"   # providerID=opencode (프리픽스 없이 id)
OUT = os.path.join("experiments", "operational-golden", "data", "stage102m_judge_api.json")
MAIN = os.path.join("experiments", "operational-golden", "data", "stage102h_judge_fixed.json")
QA = os.path.join("experiments", "operational-golden", "data", "stage101_consumer.json")
K_OUT = os.path.join("experiments", "operational-golden", "data", "stage102k_judge_sb_all.json")

PARALLEL = 4   # 프로브: 4건/11.6s → 병렬 4가 안전(3건 시 3번째만 지연), 2는 6건/분으로 느림

def auth_header():
    pw = json.load(open(SERVICE_JSON, encoding="utf-8"))["password"]
    token = base64.b64encode(f"opencode:{pw}".encode()).decode()
    return {"Authorization": f"Basic {token}", "x-opencode-ticket": "1",
            "Content-Type": "application/json"}

def api(method, path, body=None, timeout=30):
    req = urllib.request.Request(SERVER + path, method=method, headers=auth_header(),
                                 data=json.dumps(body).encode() if body else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_msg": e.read().decode()[:200]}
    except Exception as e:
        return {"_error": "ERR", "_msg": str(e)[:200]}

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

JSON 형식으로만 답하세요 (reason은 20단어 이내로 짧게):
{{"verdict": "yes"/"no", "reason": "한 줄 근거"}}"""

def judge_one(x, timeout=170):
    """서버 API로 1건 판정 — poll 방식"""
    d = api("POST", "/api/session", {"title": "judge-m", "model": {"id": MODEL, "providerID": "opencode"}})
    if "_error" in d:
        return "parse_fail", f"session:{d.get('_error')}"
    sid = d["data"]["id"]
    try:
        r = api("POST", f"/api/session/{sid}/prompt", {"text": build_prompt(x)}, timeout=90)
        if "_error" in r:
            return "parse_fail", f"prompt:{r.get('_error')}"
        deadline = time.time() + timeout
        texts = []
        while time.time() < deadline:
            m = api("GET", f"/api/session/{sid}/message", timeout=30)
            if "_error" not in m:
                for msg in m.get("data", []):
                    if msg.get("type") == "assistant":
                        content = msg.get("content", [])
                        for c in content:
                            if isinstance(c, dict) and c.get("type") == "text":
                                t = c.get("text", "")
                                if t:  # 빈 text(스트리밍 초기)는 완료로 인정하지 않음
                                    texts.append(t)
                    elif msg.get("type") == "error":
                        payload = msg.get("payload", {})
                        return "parse_fail", f"err:{json.dumps(payload, ensure_ascii=False)[:150]}"
                if texts:
                    resp = "".join(texts)
                    try:
                        start = resp.find("{\"verdict\"")
                        if start == -1:
                            start = resp.find("{")
                        end = resp.rfind("}")
                        j = json.loads(resp[start:end+1])
                        v = j.get("verdict", "")
                        if v in ("yes", "no"):
                            return v, j.get("reason", "")
                        return "parse_fail", f"badverdict:{resp[:120]}"
                    except Exception:
                        try:
                            start = resp.find('{"verdict"')
                            end = resp.rfind('"}')
                            j = json.loads(resp[start:end+2])
                            v = j.get("verdict", "")
                            if v in ("yes", "no"):
                                return v, j.get("reason", "")
                        except Exception:
                            pass
                        return "parse_fail", resp[:200]
            time.sleep(3)
        return "parse_fail", "[ERR timeout]"
    finally:
        api("DELETE", f"/api/session/{sid}")

def key(x):
    return (x["query"], x["k"], x["framing"], x.get("sample"))

def main():
    qa = json.load(open(QA, encoding="utf-8"))
    qa = [x for x in qa if "[ERR" not in str(x.get("response"))]

    # stage102k(space-bunny) 체크포인트에서 이미 판정된 키 제외
    k_done = set()
    if os.path.exists(K_OUT):
        try:
            kl = json.load(open(K_OUT, encoding="utf-8"))
            k_done = {key(x) for x in kl if x.get("judge_verdict") in ("yes", "no")}
            print(f"stage102k(space-bunny) 유효 판정: {len(k_done)}건", flush=True)
        except Exception:
            pass

    results = []
    done_keys = set()
    if os.path.exists(OUT):
        try:
            results = json.load(open(OUT, encoding="utf-8"))
            done_keys = {key(x) for x in results if x.get("judge_verdict") in ("yes", "no")}
            print(f"stage102m 체크포인트: {len(results)}건 (유효 {len(done_keys)})", flush=True)
        except Exception:
            pass

    targets = [x for x in qa if key(x) not in k_done and key(x) not in done_keys]
    print(f"판정 대상: {len(targets)}건 (서버 API, model={MODEL}, 병렬 {PARALLEL})", flush=True)

    round_no = 1
    t_total = time.time()
    while targets and round_no <= 4:
        print(f"--- 라운드 {round_no}: {len(targets)}건 ---", flush=True)
        pending = list(targets)
        results_round = []
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=PARALLEL) as ex:
            futs = {}
            idx = 0
            while pending or futs:
                # 슬롯 채우기
                while len(futs) < PARALLEL and pending:
                    x = pending.pop(0)
                    futs[ex.submit(judge_one, x)] = x
                if not futs:
                    break
                done_futs = set()
                for f in list(futs):
                    if f.done():
                        x = futs[f]
                        try:
                            v, reason = f.result()
                        except Exception as e:
                            v, reason = "parse_fail", f"[ERR {e}]"
                        x["judge_verdict"] = v
                        x["judge_reason"] = reason
                        x["judge_model"] = MODEL
                        results_round.append(x)
                        done_futs.add(f)
                        idx += 1
                        if idx % 5 == 0:
                            el = time.time() - t_total
                            rate = (len(results) + idx) / el * 60
                            json.dump(results + results_round, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
                            print(f"  {idx}건 (누적 {len(results)+idx}) {rate:.1f}건/분", flush=True)
                for f in done_futs:
                    del futs[f]
                if futs:
                    time.sleep(1.5)
        el = time.time() - t0
        for x in results_round:
            results.append(x)
        json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
        done_keys = {key(x) for x in results if x.get("judge_verdict") in ("yes", "no")}
        # 실패분만 다음 라운드
        targets = [x for x in qa if key(x) not in k_done and key(x) not in done_keys]
        fails = [x for x in results_round if x.get("judge_verdict") not in ("yes", "no")]
        print(f"라운드 {round_no} 종료: {len(results_round)}건 처리 / 유효 {len(results_round)-len(fails)} / 실패 {len(fails)} ({el/60:.1f}분)", flush=True)
        round_no += 1

    el = time.time() - t_total
    ok = sum(1 for x in results if x.get("judge_verdict") in ("yes", "no"))
    print(f"\n판정 완료: {len(results)}건 처리 / 유효 {ok}건 / parse_fail {len(results)-ok}건 ({el/60:.1f}분)", flush=True)

    # 병합: stage102k(space-bunny) + stage102m(nemotron) → stage102h
    k_list = [x for x in json.load(open(K_OUT, encoding="utf-8")) if x.get("judge_verdict") in ("yes", "no")]
    merged = {key(x): x for x in k_list}
    for x in results:
        if x.get("judge_verdict") in ("yes", "no"):
            merged[key(x)] = x
    merged_list = list(merged.values())
    total_ok = len(merged_list)
    if total_ok == len(qa):
        json.dump(merged_list, open(MAIN, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"stage102h 최종 교체: {total_ok}/{len(qa)}건 (space-bunny {len(k_list)} + nemotron {ok})", flush=True)
    else:
        print(f"⚠️ 유효 {total_ok}/{len(qa)} — stage102h 교체 보류, 미판정 {len(qa)-total_ok}건", flush=True)
        # 부분 병합도 저장 (이어서 재개 가능하게)
        json.dump(merged_list, open(OUT.replace("stage102m", "stage102m_merged"), "w", encoding="utf-8"), ensure_ascii=False)
    from collections import Counter
    print("판정자 분포:", dict(Counter(x.get("judge_model") for x in merged_list)), flush=True)

if __name__ == "__main__":
    main()