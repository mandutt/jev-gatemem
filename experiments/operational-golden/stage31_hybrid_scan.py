"""Noul+Choice 동시 호출 한도 스윕 — 몇 개 질문까지 200인가 (이분 탐색)"""
import json, os, sys, time, urllib.request, urllib.error
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden")

from keyring import SmartRotator
rot = SmartRotator()
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
        return e.code, {"__msg": e.read().decode()[:200]}

def probe(n_noul):
    cands = [f"후보 {i} 설명" for i in range(n_noul)]
    j_labels = list(cands) + ["No candidate"]
    qs = {"best": {"type": "choice", "instructions": "Pick one.",
                   "criteria": {f"c{i}": j_labels[i] for i in range(len(j_labels))}}}
    for i in range(n_noul):
        qs[f"n{i}"] = {"type": "noul", "instructions": {"question": "답인가?", "candidate": cands[i]}}
    body = {"model": MODEL, "state": {"question": "t", "candidates": []}, "questions": qs}
    key = rot.next()
    st, _ = post(URL, body, key)
    return st

# 이분 탐색: 0 ~ 60 noul (질문 수 = noul+1)
print("=== noul 수 스윕 ===", flush=True)
for n in [30, 40, 50, 55, 20]:
    st = probe(n)
    print(f"noul {n:2}(질문 {n+1:2}): status={st}", flush=True)