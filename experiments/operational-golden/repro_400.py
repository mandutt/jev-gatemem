"""400 오류 재현 테스트 — 성공/실패 쿼리 쌍을 동일 폼으로 호출해 차이 규명"""
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
        return e.code, e.read().decode()[:300]

# 성공 쿼리 1 (n_pool 40) vs 실패 쿼리 1 (n_pool 40)
cases=[]
d=json.load(open('experiments/operational-golden/data/diag6_op_scores.json',encoding='utf-8'))
ok=[r for r in d['records'] if r.get('max_score') is not None and not r.get('err') and r['n_pool']==40]
err=[r for r in d['records'] if r.get('err')]
print(f"성공(n_pool40): {len(ok)} 실패: {len(err)}")
# 각각 첫 1건
ok1=ok[0]; er1=err[0]
print("성공:", ok1['qid'][:8], ok1['query'][:40])
print("실패:", er1['qid'][:8], er1['query'][:40])

# 실패 쿼리로 candidates 없이 + noul 1건만
q=er1['query']
body={"model":MODEL,"state":{"query":q,"candidates":[]},"questions":{"q0":{"type":"noul","instructions":{"question":"Score relevance 0-1.","candidate":"test candidate 문장입니다."}}}}
s,r=post(body); print(f"\n실패쿼리 단독 noul(candidates=[]): {s} | {str(r)[:150]}")

# 성공 쿼리 동일 폼
q2=ok1['query']
body["state"]["query"]=q2
s,r=post(body); print(f"성공쿼리 단독 noul(candidates=[]): {s} | {str(r)[:150]}")
PYEOF