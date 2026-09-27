"""Excerpt-length retest: longer excerpt (400 chars) on q149/q150."""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")

import httpx

from backends.mnemosyne import MnemosyneBackend
from experiments.lane_pool import LanePool
from gateway.excerpts import build_excerpt

SNAP = r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\snapshots\snap-20260927.db"
Q = json.loads(Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\dataset_curated.json").read_text(encoding="utf-8"))
RES = json.load(open(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\results\phase1v2_picks3.json", encoding="utf-8"))

b = MnemosyneBackend(db_path=SNAP)
beam = b._ensure_beam()
pool = LanePool(beam, fts_budget=60, vec_budget=60, rrf_k=30)

PROMPT = (
    "Which candidate memory BEST ANSWERS the question as a whole — the one that "
    "contains the most complete and accurate answer, covering all aspects of what "
    "is asked, even if another candidate mentions a related keyword more prominently? "
    "Pick exactly one. Prioritize comprehensive direct answers over partial mentions."
)
key = os.environ.get("TYPESAFE_API_KEY", "")

for qid in ["q149", "q150"]:
    q = next(x for x in Q if x["qid"] == qid)
    gold = {g for r2 in RES["per_query"] if r2["query_id"] == qid for g in r2["gold_ids"]}
    cands = pool.retrieve(q["query"], budget=40)
    for c in cands:
        row = beam.get(c.id)
        content = row.get("content", "") if isinstance(row, dict) and row else ""
        c.short_excerpt = build_excerpt(content, c.memory_type)
    print(f"===== {qid}: {q['query'][:60]}")
    for chars in (120, 300, 500):
        state = {"question": q["query"], "candidates": [
            {"id": c.id[:12], "type": c.memory_type or "", "excerpt": (c.short_excerpt or "")[:chars]}
            for c in cands]}
        labels = [(c.short_excerpt or "")[:chars] for c in cands]
        questions = {"best": {"type": "choice", "instructions": PROMPT,
                              "criteria": {f"c{i}": labels[i] for i in range(len(cands))}}}
        t0 = time.perf_counter()
        resp = httpx.post("https://api.typesafe.ai/v1/systemone",
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                          json={"state": state, "questions": questions, "model": "jev-latest"},
                          timeout=40)
        lat = (time.perf_counter() - t0) * 1000
        ans = (resp.json().get("answers") or {}).get("best") or {}
        choice = ans.get("choice")
        idx = int(str(choice).lstrip("c")) if choice is not None else -1
        picked = cands[idx] if 0 <= idx < len(cands) else None
        is_gold = picked.id in gold if picked else False
        gold_rank = [i for i, c in enumerate(cands) if c.id in gold]
        print(f"  excerpt={chars}: choice={choice} gold_rank={gold_rank} is_gold={is_gold} ({lat:.0f}ms)")