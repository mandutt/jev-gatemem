"""가설 검증: op-90 열세가 '자가 유래 쿼리 편향'(lexical overlap) 때문인가?
op-90 쿼리 84개를 gold 텍스트와의 lexical overlap으로 두 그룹으로 나눠
bekko vs gemma2-q8 vs gemma2-q4f16의 hit@1/MRR을 분해한다.
overlap = 쿼리 토큰(간단화: 한국어 형태소 단위 대신 문자 2-gram)이 gold에 포함된 비율.
0콜, 기존 결과 JSON만 재계산.
"""
import os, json, re

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

per90 = json.load(open(os.path.join(B, "op90_result.json"), encoding="utf-8"))["per_query"]
q8res = json.load(open(os.path.join(B, "q8_bench_result.json"), encoding="utf-8"))
perq8 = q8res["per_query"]

def bigrams(s):
    s = re.sub(r"\s+", "", s.lower())
    return set(s[i:i+2] for i in range(len(s)-1))

def overlap_ratio(q, gold):
    """쿼리 문자 2-gram 중 gold에 포함된 비율 (0~1)."""
    g = bigrams(gold)
    qb = bigrams(q)
    if not qb:
        return 0.0
    return len(qb & g) / len(qb)

groups = {"high_overlap": [], "low_overlap": []}  # key: (q, rank_bekko, rank_q8, ratio)

for i, (q, gid) in enumerate(items):
    gold = id_text[gid]
    ratio = overlap_ratio(q, gold)
    r_b = per90[str(i)]["bekko"]
    r_8 = perq8[i]["q8"]
    r_4 = per90[str(i)]["gemma2"]
    grp = "high_overlap" if ratio >= 0.3 else "low_overlap"
    groups[grp].append({"q": q, "ratio": round(ratio, 2), "bekko": r_b, "q8": r_8, "q4f16": r_4})

def summary(grp):
    n = len(grp)
    def hit(rank): return sum(1 for x in grp if x[rank] <= 1) / n
    def mrr(rank): return sum(1/x[rank] for x in grp) / n
    return {
        "n": n,
        "bekko_hit1": round(hit("bekko"), 3), "q8_hit1": round(hit("q8"), 3), "q4_hit1": round(hit("q4f16"), 3),
        "bekko_mrr": round(mrr("bekko"), 3), "q8_mrr": round(mrr("q8"), 3), "q4_mrr": round(mrr("q4f16"), 3),
    }

print("=== 그룹 분해 (overlap>=0.3 vs <0.3) ===")
for grp, arr in groups.items():
    print(grp, json.dumps(summary(arr), ensure_ascii=False))
    # 상위 열세 쿼리 샘플
    arr_sorted = sorted(arr, key=lambda x: x["ratio"])
    for x in arr_sorted[:3]:
        print(f"  ratio={x['ratio']:.2f} bekko={x['bekko']} q8={x['q8']} | {x['q'][:50]}")

# 연속 축: ratio 값별 산점 (binned)
print("\n=== ratio 구간별 MRR ===")
import statistics
for lo, hi in [(0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.5), (0.5, 1.01)]:
    arr = [x for x in groups["high_overlap"] + groups["low_overlap"] if hi > x["ratio"] >= lo]
    if arr:
        print(f"[{lo},{hi}) n={len(arr)} bekko_mrr={round(sum(1/x['bekko'] for x in arr)/len(arr),3)} q8_mrr={round(sum(1/x['q8'] for x in arr)/len(arr),3)}")