"""400 임계 — 질문 수 + 총 바이트/토큰 조합 정밀 측정"""
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
        return e.code, e.read().decode()[:150]

q="라우팅 플립 트리거 가설 맞았어?"
short="후보 문장 관련성 판단용 짧은 텍스트"

def build(n_q, long_every=None, long_len=12000):
    qs={}; i=0
    for n in range(n_q):
        if long_every and n % long_every == 0:
            c="긴"*long_len
            for part in [c[j:j+8000] for j in range(0,len(c),8000)]:
                qs[f"q{i}"]={"type":"noul","instructions":{"question":"Score 0-1.","candidate":part}}; i+=1
        else:
            qs[f"q{i}"]={"type":"noul","instructions":{"question":"Score 0-1.","candidate":short}}; i+=1
    return qs

def run(label, qs):
    body={"model":MODEL,"state":{"query":q,"candidates":[]},"questions":qs}
    raw=json.dumps(body).encode()
    s,_=post(body)
    print(f"{label}: {s} (요청 {len(raw)//1024}KB, 질문 {len(qs)}개)", flush=True)
    time.sleep(0.5)

# 질문 32개 고정, 후보 길이 변화
print("=== 질문 32개, 총 바이트 변화 ===")
run("32×짧", build(32))
run("32×6000자", build(32, None) | {f"q{i}":{"type":"noul","instructions":{"question":"Score 0-1.","candidate":"가"*6000}} for i in range(32)})
PYEOF