"""Noul+Choice hybrid — API 한도 검증 (1콜) → 본 실험 전 확인

질문: 후보 60개에 대해 noul 60 + choice 1 = 61질문이 1요청에 드는가?
(스킬: "질문 수×후보 길이" 한도 존재 — MAX_QS 32 배치 권장이나, 최신 API가 병렬 허용)
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
        return e.code, {"__msg": e.read().decode()[:300]}

# 후보 60 + abstain = 61 criteria, noul 60 + choice 1 = 61 questions
cands = [f"후보 메모리 {i} — 설명 텍스트용 placeholder" for i in range(60)]
j_labels = list(cands) + ["No candidate is usable evidence"]
qs = {"best": {"type": "choice", "instructions": "Which candidate is the best evidence? Pick one.",
               "criteria": {f"c{i}": j_labels[i] for i in range(len(j_labels))}}}
for i in range(60):
    qs[f"n{i}"] = {"type": "noul", "instructions": {"question": "이 후보가 질문의 답을 담고 있나?", "candidate": cands[i]}}

body = {"model": MODEL, "state": {"question": "테스트: 웹 추출 백엔드는?", "candidates": []},
        "questions": qs}
print(f"질문 수: {len(qs)} (choice 1 + noul 60), criteria: {len(j_labels)}", flush=True)
st, r = post(URL, body, key)
print(f"status={st}", flush=True)
if st == 200:
    ans = r.get("answers", {})
    print(f"answers: {len(ans)}개", flush=True)
    print("best:", json.dumps(ans.get("best", {}), ensure_ascii=False)[:200], flush=True)
    # noul 몇 개 응답 왔는지
    noul_cnt = sum(1 for k, v in ans.items() if k != "best")
    print(f"noul 응답: {noul_cnt}/60", flush=True)
else:
    print("err:", json.dumps(r.get("__msg", r), ensure_ascii=False)[:300], flush=True)