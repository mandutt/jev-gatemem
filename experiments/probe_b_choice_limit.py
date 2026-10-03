"""B 조건 probe: choice 1콜에 대량 criteria를 넣을 수 있는가?

B = full corpus(1,310행) + choice 1콜.
EXPERLABS/SystemOne은 choice 질문에 criteria(N개 선택지)를 딸려 보낸다.
criteria 수가 많아지면 400/거부될 수 있으므로 경계를 실측.
- N = 32, 100, 200, 400, 800, 1310 (excerpt 120자 기준)
- 요청 바이트 수도 기록 (1,310 × 120자 ≈ 157KB)
"""
import json
import os
import sys
import time
import winreg

sys.stdout.reconfigure(encoding="utf-8")
URL = "https://api.experientiallabs.ai/v1/systemone"


def _resolve_explabs_key():
    k = os.environ.get("EXPLABS_API_KEY", "")
    try:
        hk = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment")
        try:
            reg_k, _ = winreg.QueryValueEx(hk, "EXPLABS_API_KEY")
            if reg_k:
                k = reg_k
        finally:
            winreg.CloseKey(hk)
    except FileNotFoundError:
        pass
    return k


def main():
    key = _resolve_explabs_key()
    if not key:
        print("FAIL: no key")
        return 2
    import httpx

    # 담백한 criteria 생성 (실제 러닝타임 excerpt처럼 120자 캡)
    base = "이것은 테스트 후보 메모리입니다. 실제 시스템 상태 설명: 설정이 적용되어 있고 관련 절차가 문서화되어 있습니다. "
    def crit(i):
        t = f"[{i}] " + base
        return t[:120]

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    for n in [32, 100, 200, 400, 800, 1310]:
        labels = {f"c{i}": crit(i) for i in range(n)}
        body = {
            "model": "jev-latest",
            "state": {"question": "지금 사용 중인 임베딩 모델은 무엇인가요?", "candidates": []},
            "questions": {"best": {
                "type": "choice",
                "instructions": "Which candidate memory is the single best evidence for answering the question? Pick exactly one.",
                "criteria": labels,
            }},
        }
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        b = len(payload.encode())
        t0 = time.monotonic()
        try:
            r = httpx.post(URL, content=payload.encode(), headers=headers, timeout=180.0)
            dt = time.monotonic() - t0
            ans = None
            if r.status_code == 200:
                ans = (r.json().get("answers") or {}).get("best") or {}
            print(f"n={n:5d} bytes={b:8d}: HTTP {r.status_code} ({dt:.1f}s) "
                  f"choice={ans.get('choice') if ans else ''} {r.text[:120] if r.status_code != 200 else ''}", flush=True)
        except Exception as e:
            print(f"n={n:5d} bytes={b:8d}: EXC {type(e).__name__}: {e}", flush=True)
        time.sleep(1.0)
    return 0


if __name__ == "__main__":
    sys.exit(main())