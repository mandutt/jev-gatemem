"""400 임계 규명 — 질문 수 증가 + 후보 길이/콘텐츠 의존성"""
import json, os, sys, time, winreg, urllib.request, urllib.error
sys.stdout.reconfigure(encoding="utf-8")
URL="https://api.experientiallabs.ai/v1/systemone"; MODEL="jev-latest"

def key():
    k=os.environ.get("EXPLABS_API_KEY","")
    try:
        hk=winreg.OpenKey(winreg.HKEY_CURRENT_USER,r"Environment")
        try: k,_=winreg.QueryValueEx(hk,"EXPLABS_API_KEY")
        finally: winreg.CloseKey(hk)
    except FileNotFoundError: pass
    return k.strip().strip('"')

def post(body):
    req=urllib.request.Request(URL,data=json.dumps(body).encode(),method="POST")
    req.add_header("Authorization",f"Bearer {key()}"); req.add_header("Content-Type","application/json")
    try:
        r=urllib.request.urlopen(req,timeout=120)
        return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:250]

# 실패 쿼리 + 실패 당시 후보 콘텐츠를 가져오려면: pool 재구성 필요 → 대신 짧은 문장 N개로 질문 수 테스트
q_fail="92번 호출 실험에서 라우팅 결과 어땠지?"
q_ok="web_extract API 키 없이 쓸 수 있어?"

def test(q, n_questions, cand_len):
    qs={}
    for i in range(n_questions):
        c="테스트 후보 문장입니다. 관련성 판단용 예시 텍스트 " * (cand_len//40 if cand_len else 1)
        qs[f"q{i}"]={"type":"noul","instructions":{"question":"Score relevance 0-1.","candidate":c[:80]}}
    body={"model":MODEL,"state":{"query":q,"candidates":[]},"questions":qs}
    s,r=post(body)
    return s

# 1) 질문 수: 2,4,8,16,32 (짧은 후보)
for n in (2,4,8,16,32,40):
    s=test(q_fail,n,0)
    print(f"실패쿼리 질문 {n}개: {s}")
    time.sleep(0.5)
print()
for n in (2,4,8,16,32,40):
    s=test(q_ok,n,0)
    print(f"성공쿼리 질문 {n}개: {s}")
    time.sleep(0.5)
PYEOF