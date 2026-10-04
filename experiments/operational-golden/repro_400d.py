"""가설 검증: 8000자 초과 후보(긴 콘텐츠) 존재 시 질문 수 33+ → 400"""
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
        return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:120]

q="라우팅 플립 트리거 가설 맞았어?"

# 후보 30개, 그중 2개는 8000자 초과 (12000자) → 조각 2개 → 질문 32개
# 28개 짧은 후보 + 2개 긴 후보(각 2조각) = 28+4=32개 질문 → 200 기대
short="후보 문장 관련성 판단용 짧은 텍스트"
long_c="긴 후보 콘텐츠입니다. " * 500  # 12000자

def build(n_short, n_long, long_len_chars):
    qs={}; i=0
    for _ in range(n_short):
        qs[f"q{i}"]={"type":"noul","instructions":{"question":"Score 0-1.","candidate":short}}; i+=1
    for _ in range(n_long):
        c="긴"*long_len_chars
        for part in [c[j:j+8000] for j in range(0,len(c),8000)]:
            qs[f"q{i}"]={"type":"noul","instructions":{"question":"Score 0-1.","candidate":part}}; i+=1
    return qs

print("=== 28짧+2긴(12000자→4조각) = 32 질문 ===")
qs=build(28,2,12000)
body={"model":MODEL,"state":{"query":q,"candidates":[]},"questions":qs}
s,_=post(body); print(f"  32개: {s}")

print("=== 29짧+2긴(12000자) = 33 질문 ===")
qs=build(29,2,12000)
body={"model":MODEL,"state":{"query":q,"candidates":[]},"questions":qs}
s,_=post(body); print(f"  33개: {s}")

print("=== 25짧+2긴(16000자→4조각)+1긴(12000→2조각)=33 질문 ===")
qs=build(25,3,12000)
body={"model":MODEL,"state":{"query":q,"candidates":[]},"questions":qs}
s,_=post(body); print(f"  33개(긴3): {s}")
PYEOF