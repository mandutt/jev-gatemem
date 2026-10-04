"""400 임계 정밀 — 후보 1300~1400자 × 32개"""
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

def run(n_q, cand_len):
    qs={f"q{i}":{"type":"noul","instructions":{"question":"Score 0-1.","candidate":"가"*cand_len}} for i in range(n_q)}
    body={"model":MODEL,"state":{"query":q,"candidates":[]},"questions":qs}
    raw=json.dumps(body).encode()
    s,_=post(body)
    print(f"질문 {n_q}개 × 후보 {cand_len}자: {s} (요청 {len(raw)//1024}KB)", flush=True)
    time.sleep(0.5)

print("=== 질문 32개, 후보 1300~1400자 ===")
for cl in (1300, 1320, 1340, 1360, 1380, 1400):
    run(32, cl)
PYEOF