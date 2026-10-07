import json, os, sys
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden")
import run_r_recall_strength as R

gold = json.load(open(os.path.join(R.DATA, "golden_eval_v2.json"), encoding="utf-8"))
op = [x for x in gold if x.get("gold_id") and x.get("cat") != "NO_ANSWER"][:5]

import sqlite3
conn = sqlite3.connect(f"file:{R.LIVE_DB}?mode=ro", uri=True)
by_id = {}
for r in conn.execute("SELECT id, recall_count, importance FROM working_memory UNION ALL SELECT id, recall_count, importance FROM episodic_memory"):
    by_id[r[0]] = {"recall_count": r[1] or 0, "importance": r[2] or 0.0}
conn.close()
print("by_id:", len(by_id), "with_rc:", sum(1 for v in by_id.values() if v["recall_count"]>0), flush=True)

recall_raw, j1p, b = R.get_beam_refs()
print("beam refs OK", flush=True)
for x in op:
    q = x["query"]
    pool = R.stage1_pool(recall_raw, j1p, q, k=40)
    pool = [p for p in pool if p.get("id") in by_id]
    for p in pool:
        meta = by_id.get(p.get("id"), {})
        p["recall_count"] = meta.get("recall_count", 0)
        p["importance"] = meta.get("importance", 0.0)
    ap = R.apply_alpha(pool, 0.3) if pool else []
    print(f"\nQ: {q[:50]}")
    print(f"  pool={len(pool)} alpha_pool={len(ap)}")
    for i, c in enumerate(pool[:4]):
        st = R.recall_boost(c, 0.3)
        rc = by_id.get(c.get("id"), {}).get("recall_count", 0)
        print(f"    base[{i}] rc={rc} strength={st:.3f} | {c.get('content','')[:40]!r}")
    for i, c in enumerate(ap[:4]):
        print(f"    ar [{i}] strength={c.get('_strength'):.3f} | {c.get('content','')[:40]!r}")
    key = R.rot.next()
    idx, cost, err = R.choice_call(key, q, ap[:R.MAX_CAND])
    print(f"  JEV: idx={idx} cost={cost} err={err}")
    if idx is not None and idx >= 0:
        print(f"  winner: {ap[idx].get('content','')[:40]!r}")
print("SMOKE DONE")
