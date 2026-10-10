"""stage120: AMB LongMemEval leaderboard 검토 — 0콜 실측 요약 (2026-10-10)

판정 근거를 재현 가능하게 남기는 0콜 프로브:
1. reranker 실행 환경 확인 (데몬 venv 패키지 — torch/sentence_transformers 부재)
2. RRF lane 밀림 raw 대조 (stage50c/d: lane 단독 1~2위가 RRF에서 6위+로 밀림 — 랭킹 병목 존재하나
   JEV choice가 60개 전체 입력이라 winner 무영향, Run R 실측 확정)
3. AMB 벤치 점수 백본 모델 분리 표기 (비교 불가 경고)

사용: 데몬 venv python으로 실행 (fastembed 존재 확인용). JEV 호출 없음.
"""
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware")
DATA = REPO / "experiments" / "operational-golden" / "data"

print("=== 1) reranker 실행 환경 (데몬 venv) ===")
for m in ["torch", "sentence_transformers", "fastembed", "onnxruntime", "numpy"]:
    print(f"  {m}: {bool(importlib.util.find_spec(m))}")

print("\n=== 2) RRF lane 밀림 대조 (stage50c, n=21) ===")
with open(DATA / "stage50c_lane_decomp.json", encoding="utf-8") as f:
    lane_decomp = json.load(f)
n_lane_top12 = sum(
    1 for r in lane_decomp
    if r.get("fts_rank") in (1, 2) or r.get("vec_rank") in (1, 2)
)
n_pushed = sum(
    1 for r in lane_decomp
    if (r.get("fts_rank") in (1, 2) or r.get("vec_rank") in (1, 2))
    and r.get("rrf_rank", 99) > 5
)
print(f"  lane 단독 1~2위: {n_lane_top12}건")
print(f"  그중 RRF 6위+로 밀림: {n_pushed}건 (답이 하위로 밀리는 병목 실재)")
print("  → 단 JEV choice는 60개 전체 입력 — 순서 변화는 winner 무영향 (Run R 180콜 실측)")

print("\n=== 3) AMB 벤치 점수 = 백본 모델 제각각 (비교 불가) ===")
scores = [
    ("Chronos", "95.6%", "Claude Opus 4.6 (최상위 백본)"),
    ("Honcho", "90.4%", "Claude Haiku 4.5"),
    ("SmartSearch", "88.4%", "GPT-4.1-mini"),
    ("Memora", "87.4%", "GPT-4.1-mini"),
    ("EMem-G", "84.9%", "GPT-4.1-mini"),
    ("TiMem", "76.9%", "GPT-4o"),
]
for name, acc, backbone in scores:
    print(f"  {name}: {acc} = {backbone}")

print("\n판정: reranker 기각 (JEV 순서 무영향 + 환경 부재) · 시간 캘린더 기각 (발동률 1.1~1.3%) ·"
      "\n      dynamic prompting 기각 (0콜 원칙) · 정합 2 (비압축 보존·LLM-free) · 참고 2 (TiMem 계층 경계)")
print("완료 — JEV 호출 0회")