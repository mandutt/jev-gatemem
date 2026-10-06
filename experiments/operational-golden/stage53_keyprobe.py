# -*- coding: utf-8 -*-
"""키 상태 진단 — 두 키 모두 1콜씩 발사해 상태 확인 (429/200/크레딧)"""
import os, sys, time, json

sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware")

from jev_mem_core.keyring import SmartRotator, get_keys, get_key_names
import httpx

names = get_key_names()
keys = get_keys()

for n, k in zip(names, keys):
    for api_url, label in [("https://api.experientiallabs.ai/v1/systemone", "explabs"),
                            ("https://api.typesafe.ai/v1/systemone", "typesafe")]:
        try:
            resp = httpx.post(api_url,
                headers={"Authorization": f"Bearer {k}", "Content-Type": "application/json"},
                json={"state": {"utterance": "키 상태 진단"},
                      "questions": {"q": {"type": "choice", "criteria": {"c0": "yes", "c1": "no"}}},
                      "model": "jev-latest"}, timeout=15)
            body = resp.text[:200]
            print(f"{n} via {label}: {resp.status_code} {body}")
        except Exception as e:
            print(f"{n} via {label}: EXC {str(e)[:120]}")
        time.sleep(1)