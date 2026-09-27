"""Prompt-improvement retest on the 4 Jev-miss queries.

New prompt: emphasize comprehensiveness & direct answer coverage, not
"best-sounding" specificity. Compare old vs new choice on q110/q148/q149/q150.
"""
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

OLD_PROMPT = (
    "Which candidate memory is the single best evidence for answering "
    "the question? Pick exactly one. Consider directness and specificity."
)
NEW_PROMPT = (
    "Which candidate memory BEST ANSWERS the question as a whole — the one that "
    "contains the most complete and accurate answer, covering all aspects of what "
    "is asked, even if another candidate mentions a related keyword more prominently? "
    "Pick exactly one. Prioritize comprehensive direct answers over partial mentions."
)

MISS = {"q110", "q148", "q149", "q150"}

key = os.environ.get("TYPESAFE_API_KEY", "")


def choice_call(prompt: str, state: dict, labels: list[str], n: int):
    questions = {"best": {"type": "choice", "instructions": prompt,
                          "criteria": {f"c{i}": labels[i] for i in range(n)}}}
    t0 = time.perf_counter()
    resp = httpx.post("https://api.typesafe.ai/v1/systemone",
                      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                      json={"state": state, "questions": questions, "model": "jev-latest"},
                      timeout=30)
    lat = (time.perf_counter() - t0) * 1000
    if resp.status_code != 200:
        return None, lat, resp.status_code
    ans = (resp.json().get("answers") or {}).get("best") or {}
    return ans.get("choice"), lat, resp.status_code


for name, prompt in [("OLD", OLD_PROMPT), ("NEW", NEW_PROMPT)]:
    print(f"\n===== {name} PROMPT =====")
    for r in RES["per_query"]:
        if r["query_id"] not in MISS:
            continue
        q = next(x for x in Q if x["qid"] == r["query_id"])
        gold = set(r["gold_ids"])
        cands = pool.retrieve(q["query"], budget=40)
        for c in cands:
            row = beam.get(c.id)
            content = row.get("content", "") if isinstance(row, dict) and row else ""
            c.short_excerpt = build_excerpt(content, c.memory_type)
        state = {"question": q["query"], "candidates": [
            {"id": c.id[:12], "type": c.memory_type or "", "excerpt": (c.short_excerpt or "")[:120]}
            for c in cands]}
        labels = [(c.short_excerpt or "")[:100] for c in cands]
        choice, lat, status = choice_call(prompt, state, labels, len(cands))
        print(f"  {r['query_id']}: status={status} choice={choice} ({lat:.0f}ms) ", end="")
        if choice is None:
            print("NO ANSWER")
            continue
        try:
            idx = int(str(choice).lstrip("c"))
        except ValueError:
            print("BAD CHOICE", choice)
            continue
        picked = cands[idx] if idx < len(cands) else None
        is_gold = picked.id in gold if picked else False
        gold_rank = [i for i, c in enumerate(cands) if c.id in gold]
        print(f"gold_rank={gold_rank} picked_is_gold={is_gold} picked={picked.short_excerpt[:50] if picked else '?'}")