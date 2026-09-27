"""Check how often gold appears in top-k recall candidates (Jev improvement ceiling)."""
import sys, json
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
from backends.mnemosyne import MnemosyneBackend

SNAP = r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\snapshots\snap-20260927.db"
Q = json.loads(open(r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\dataset_curated.json", encoding="utf-8").read())
b = MnemosyneBackend(db_path=SNAP)

for topk in [30, 50, 100]:
    hit = miss = 0
    for q in Q:
        hits = [h.id for h in b.recall(q["query"], top_k=topk)]
        if set(q["gold_ids"]) & set(hits):
            hit += 1
        else:
            miss += 1
    print(f"top-{topk}: gold 포함 {hit}/{len(Q)} ({hit/len(Q)*100:.0f}%), miss {miss}", flush=True)