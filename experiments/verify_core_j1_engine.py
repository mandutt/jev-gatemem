"""P1 검증 — core.j1_engine.run() 라이브 DB 동작 확인 (Hermes 런타임 venv 실행).

- core.j1_engine이 실제 mnemosyne.db에서 lane pool → gate → Jev rerank를
  수행해 '## Mnemosyne Context' 블록을 반환하는지 확인
- 실패 시 "" 반환 (fallback 계약) 확인
- Hermes 런타임 venv python으로 실행 (mnemosyne 3.15.1 + mnemosyne_hermes)
"""
import os
import sys
import sqlite3
from pathlib import Path

REPO = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware")
sys.path.insert(0, str(REPO))

from mnemosyne.core import beam as beam_mod

# 라이브 beam 준비 (Mnemosyne BeamMemory — prefetch에서 사용하는 동일 클래스)
DB = r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db"
beam = beam_mod.BeamMemory(db_path=DB)

# pipeline 주입: standalone이므로 직접 import (섀도잉 없음)
from gateway import j1_pipeline as j1

from core import j1_engine

# TYPESAFE_API_KEY: Hermes .env에서 읽기
env_path = Path(r"C:\Users\mandu\AppData\Local\hermes\.env")
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            if k.strip() == "TYPESAFE_API_KEY":
                os.environ.setdefault("TYPESAFE_API_KEY", v.strip().strip('"').strip("'"))

# 1) kill switch off 확인
print("j1_on:", j1_engine.j1_on(j1))

# 2) 실제 쿼리로 run() 실행
queries = [
    "Hermes 메모리 write gate assistant 저장",
    "텔레그램 게이트웨이 서비스 상태",
]
for q in queries:
    client = j1_engine.typesafe_client()
    out = j1_engine.run(beam, q, pipeline=j1, client=client, top_k=5)
    if out:
        lines = out.splitlines()
        print(f"\n=== query: {q!r} ===")
        print(f"block lines: {len(lines)} | first: {lines[0]!r}")
        for l in lines[1:4]:
            print("  ", l[:110])
    else:
        print(f"\n=== query: {q!r} -> '' (fallback 계약 OK) ===")

# 3) 실패 시 fallback 계약: 잘못된 beam 전달 → "" 반환, 예외 없음
try:
    out = j1_engine.run(object(), "test", pipeline=j1, client=None)
    print("\nbad beam -> return:", repr(out), "(예외 없음 OK)" if out == "" else "(UNEXPECTED)")
except Exception as e:
    print("\nbad beam -> RAISED:", type(e).__name__, "(실패)")

print("\nDONE")