"""Noul+Choice 동시 호출 API 검증 (1콜) — C AI 주장 확인

C AI: "한 SystemOne 요청에 여러 질문(choice+noul)을 병렬로 넣을 수 있다"고 주장.
우리 스킬 메모리: "1요청 1질문 하드 제약 (2026-10-05 실측, questions 2개 → 400)".

다만 그 실측은 'choice+entails' 조합이었고, 'choice+noul' 조합은 미검증일 수 있음.
본 파일럿: choice 1개 + noul N개를 같은 요청에 넣어 200/400 판정.
"""
import json, os, sys, time, urllib.request, urllib.error
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden")

from keyring import SmartRotator
rot = SmartRotator()
key = rot.next()

URL = "https://api.experientiallabs.ai/v1/systemone"
MODEL = "jev-latest"

def post(url, body, key, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body_err = e.read().decode()[:300]
        return e.code, {"__msg": body_err}

# 실험 1: choice(1) + noul(2) 동시 — 같은 state
print("=== 실험 1: choice + noul 2개 = 3질문 (1요청) ===", flush=True)
body1 = {
    "model": MODEL,
    "state": {"question": "웹 추출 백엔드 설정이 뭐야?", "candidates": []},
    "questions": {
        "best": {"type": "choice", "instructions": "Which candidate is the best evidence? Pick one.",
                 "criteria": {"c0": "tavily 설정", "c1": "Exa mojibake"}},
        "q1": {"type": "noul", "instructions": {"question": "이 후보가 답인가?", "candidate": "tavily 설정"}},
        "q2": {"type": "noul", "instructions": {"question": "이 후보가 답인가?", "candidate": "Exa mojibake"}},
    },
}
st1, r1 = post(URL, body1, key)
print(f"status={st1}", flush=True)
if st1 == 200:
    print("answers:", json.dumps(r1.get("answers", {}), ensure_ascii=False)[:400], flush=True)
else:
    print("err:", json.dumps(r1.get("__msg", r1), ensure_ascii=False)[:300], flush=True)

# 실험 2: choice(1) + noul(1) = 2질문
print("\n=== 실험 2: choice + noul 1개 = 2질문 ===", flush=True)
body2 = {
    "model": MODEL,
    "state": {"question": "웹 추출 백엔드 설정이 뭐야?", "candidates": []},
    "questions": {
        "best": {"type": "choice", "instructions": "Which candidate is the best evidence? Pick one.",
                 "criteria": {"c0": "tavily 설정", "c1": "Exa mojibake"}},
        "q1": {"type": "noul", "instructions": {"question": "이 후보가 답인가?", "candidate": "tavily 설정"}},
    },
}
st2, r2 = post(URL, body2, key)
print(f"status={st2}", flush=True)
if st2 == 200:
    print("answers:", json.dumps(r2.get("answers", {}), ensure_ascii=False)[:400], flush=True)
else:
    print("err:", json.dumps(r2.get("__msg", r2), ensure_ascii=False)[:300], flush=True)

# 실험 3: noul 여러 개만 (배치) — 기존 pointwise와 동일 패턴 (성공 기준)
print("\n=== 실험 3: noul 3개만 (기존 배치 패턴) ===", flush=True)
body3 = {
    "model": MODEL,
    "state": {"question": "웹 추출 백엔드 설정이 뭐야?", "candidates": []},
    "questions": {
        "q0": {"type": "noul", "instructions": {"question": "이 후보가 답인가?", "candidate": "tavily 설정"}},
        "q1": {"type": "noul", "instructions": {"question": "이 후보가 답인가?", "candidate": "Exa mojibake"}},
        "q2": {"type": "noul", "instructions": {"question": "이 후보가 답인가?", "candidate": "프록시 설명"}},
    },
}
st3, r3 = post(URL, body3, key)
print(f"status={st3}", flush=True)
print("answers:", json.dumps(r3.get("answers", {}), ensure_ascii=False)[:300] if st3 == 200 else json.dumps(r3.get("__msg", r3), ensure_ascii=False)[:200], flush=True)