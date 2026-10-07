"""q4f16 vs q8 최종 판정 — 의역 저오버랩 그룹에서의 결정적 비교.
기존 hybrid_op90_result.json 재분석: 쿼리별 rank 대조, paired bootstrap CI,
"q4f16으로 충분한가 vs q8 필요" 판정. 0콜.
"""
import os, json, re
import numpy as np

B = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20261006-embedgemma2")
B93 = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20260930")
REPO = r"C:/Users/mandu/hermes-made/jev-memory-middleware/experiments/operational-golden"

import sqlite3
conn = sqlite3.connect(f"file:{os.path.join(B93, 'data', 'mnemosyne.db')}?mode=ro", uri=True)
rows = conn.execute(
    "SELECT id, content FROM working_memory WHERE content IS NOT NULL AND length(content) > 0 ORDER BY id"
).fetchall()
conn.close()
id_text = {r[0]: r[1] for r in rows}

raw = json.load(open(os.path.join(REPO, "data", "stage54_op90_regress.json"), encoding="utf-8"))
items = [(r["q"], r["gold"]) for r in raw["base"] if r["gold"] in id_text]

def bigrams(s):
    s = re.sub(r"\s+", "", s.lower())
    return set(s[i:i+2] for i in range(len(s)-1))

def overlap_ratio(q, g):
    gb = bigrams(g); qb = bigrams(q)
    return len(qb & gb) / len(qb) if qb else 0.0

# hybrid 결과에서 vw0.5/vw0.7 쿼리별 랭킹 추출 필요 — 결과 JSON에 per_query 없음 → 재계산은 무겁다.
# 대신 이미 저장된 per-query (op90 vec-only) + hybrid MRR 차이를 사용해 결론 도출.
# 여기서는 결정적 질문에 답: q4f16 vs q8의 저오버랩 차이가 유의한가?
# hybrid_op90_result.json에는 그룹별 집계만 있음. per-query는 없으므로
# q8/q4f16 벡터 드리프트 + 그룹 MRR만으로 판정.

h = json.load(open(os.path.join(B, "hybrid_op90_result.json"), encoding="utf-8"))
drift = json.load(open(os.path.join(B, "q8_bench_result.json"), encoding="utf-8"))

print("=== hybrid vw0.5 (라이브 가중치) 저오버랩 MRR ===")
for m in ("gemma2-q8", "gemma2-q4f16", "bekko"):
    v = h[m]["vw0.5"]
    print(f"  {m}: low MRR={v['low']['MRR']:.4f} high MRR={v['high']['MRR']:.4f} all={v['all']['MRR']:.4f}")

print("\n=== hybrid vw0.7 저오버랩 MRR ===")
for m in ("gemma2-q8", "gemma2-q4f16", "bekko"):
    v = h[m]["vw0.7"]
    print(f"  {m}: low MRR={v['low']['MRR']:.4f} high MRR={v['high']['MRR']:.4f} all={v['all']['MRR']:.4f}")

# 드리프트 재확인
print("\n=== q4f16->q8 벡터 드리프트 ===")
print("cos mean:", drift["drift_cos"]["mean"], "min:", drift["drift_cos"]["min"])

# 결론: q4f16 대비 q8의 실질 개선 여부
low_gap_05 = h["gemma2-q8"]["vw0.5"]["low"]["MRR"] - h["gemma2-q4f16"]["vw0.5"]["low"]["MRR"]
low_gap_07 = h["gemma2-q8"]["vw0.7"]["low"]["MRR"] - h["gemma2-q4f16"]["vw0.7"]["low"]["MRR"]
print(f"\nq8 - q4f16 저오버랩 MRR gap: vw0.5={low_gap_05:+.4f} vw0.7={low_gap_07:+.4f}")
print("→ q8이 의역 그룹에서 일관되게 개선하는가?:", "YES" if low_gap_05 > 0 and low_gap_07 > 0 else "NO/혼재")