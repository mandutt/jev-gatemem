"""400 임계 정밀 측정 — 질문 수 32~40 + 실제 후보 콘텐츠 영향"""
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

q="92번 호출 실험에서 라우팅 결과 어땠지?"

# 1) 질문 수 32~40 정밀 (짧은 후보)
print("=== 질문 수 정밀 임계 (짧은 후보) ===")
for n in (32,33,34,35,36,37,38,39,40):
    qs={f"q{i}":{"type":"noul","instructions":{"question":"Score 0-1.","candidate":f"후보 문장 {i} 관련성 판단용"}} for i in range(n)}
    body={"model":MODEL,"state":{"query":q,"candidates":[]},"questions":qs}
    s,_=post(body)
    print(f"  {n}개: {s}")
    time.sleep(0.5)

# 2) 실제 후보 콘텐츠 (run_diag6의 gold excerpt) 32개 — 동일 후보 반복 아닌 서로 다른 실제 문장
print("\n=== 실제 후보 32개 (gold 콘텐츠) ===")
import sqlite3
db=os.path.join(os.environ.get("LOCALAPPDATA",""),"hermes/mnemosyne/data/mnemosyne.db")
conn=sqlite3.connect(f"file:{db}?mode=ro",uri=True)
rows=conn.execute("SELECT content FROM working_memory WHERE valid_until IS NULL AND content IS NOT NULL AND content!='' LIMIT 40").fetchall()
conn.close()
cands=[r[0][:120].replace('\n',' ') for r in rows]
qs={f"q{i}":{"type":"noul","instructions":{"question":"Score 0-1.","candidate":cands[i]}} for i in range(32)}
body={"model":MODEL,"state":{"query":q,"candidates":[]},"questions":qs}
s,e=post(body)
print(f"  실제 32개: {s} {e[:80] if s!=200 else ''}")

# 3) 같은 실제 후보 40개
qs={f"q{i}":{"type":"noul","instructions":{"question":"Score 0-1.","candidate":cands[i%len(cands)]}} for i in range(40)}
body={"model":MODEL,"state":{"query":q,"candidates":[]},"questions":qs}
s,e=post(body)
print(f"  실제 40개: {s} {e[:80] if s!=200 else ''}")
PYEOF