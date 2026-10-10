# -*- coding: utf-8 -*-
"""STEP 3b 실행판: 데몬 RPC prefetch로 갭 대화 회수 검증 (운영 경로 동일)"""
import sys

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
from jev_mem_core.client import JevMemClient

QUERIES = [
    ("granite 임베딩", "granite 임베딩 모델 검토한 적 있어?"),
    ("sift 저장소", "sift 저장소에서 jev-mem에 반영할 사항"),
    ("agentmemory", "agentmemory 프로젝트 분석 결과"),
    ("GPU 램 양자화", "RX580 GPU 경로 램 점유 양자화 대안"),
    ("hippo 비교", "hippo-memory와 jev-mem 비교 검토"),
]

c = JevMemClient(agent="backfill-verify", port=47821)
for label, q in QUERIES:
    ctx = c.prefetch(q, timeout_ms=15000)
    print(f"[{label}] len={len(ctx)}")
    for ln in ctx.strip().splitlines()[:6]:
        print("   ", ln[:110])
    hit = any(k in ctx for k in ("granite", "sift", "agentmemory", "hippo", "RX580", "양자화"))
    print(f"   -> 회수 신호: {hit}")
    print()