"""Stage-2 finalize: merge user verdicts (with idx 21 corrected to VALID/mid=YES
per agent review + user confirm) into a final gold set.

Final gold = items with v_row==VALID, v_mid==YES
Emits stage2_final_gold.json with {query, row_id, table}.
Also prints summary stats.
"""
import json, os

V = r"C:/Users/mandu/hermes-made/jev-memory-middleware/experiments/operational-golden/data/stage2_row_verdicts.json"
ITEMS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stage2_row_adjudicate.json")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stage2_final_gold.json")

verdicts = json.load(open(V, encoding="utf-8"))
items = json.load(open(ITEMS, encoding="utf-8"))
assert len(verdicts) == len(items) == 38

# correction: idx 21 -> VALID/mid=YES (user confirmed my review)
verdicts[21]["v_row"] = "VALID"
verdicts[21]["v_mid"] = "YES"

gold = []
for i, (vd, it) in enumerate(zip(verdicts, items)):
    if vd["v_row"] == "VALID" and vd["v_mid"] == "YES":
        gold.append({
            "idx": i,
            "query": it["user_query"],
            "row_id": it["row_id"],
            "table": it["table"],
            "row_len": it["row_len"],
        })

json.dump(gold, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"final gold (VALID + mid=YES): {len(gold)} / 38")
# stats
from collections import Counter
print("verdict distribution (after correction):", Counter(vd["v_row"] for vd in verdicts))
print("mid distribution:", Counter(vd["v_mid"] for vd in verdicts))
# rows involved
rows = set(g["row_id"] for g in gold)
print(f"distinct rows: {len(rows)}")
for g in gold:
    print(f"  idx={g['idx']:2d} {g['table'][:4]} {g['row_id'][:14]} len={g['row_len']:>5} | {g['query'][:55]!r}")