"""Probe TypeSafe multi-question behavior: noul x3/x10, score x3, choice x100.

Precondition check for Exp 3 (Noul rerank): does one request answer many
questions, or is it capped (as score questions appeared to be at 2 earlier)?
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

b = MnemosyneBackend(db_path=SNAP)
beam = b._ensure_beam()
pool = LanePool(beam, fts_budget=60, vec_budget=60, rrf_k=30)

q = Q[0]  # q101
cands = pool.retrieve(q["query"], budget=100)
for c in cands:
    row = beam.get(c.id)
    content = row.get("content", "") if isinstance(row, dict) and row else ""
    c.short_excerpt = build_excerpt(content, c.memory_type)
state = {"question": q["query"], "candidates": [
    {"id": c.id[:12], "excerpt": (c.short_excerpt or "")[:120]} for c in cands]}
print(f"query: {q['query'][:50]} | pool size: {len(cands)}")


def call(questions, label, timeout=40.0):
    t0 = time.perf_counter()
    r = httpx.post("https://api.typesafe.ai/v1/systemone",
                   headers={"Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}",
                            "Content-Type": "application/json"},
                   json={"state": state, "questions": questions, "model": "jev-latest"},
                   timeout=timeout)
    dt = time.perf_counter() - t0
    d = r.json() if r.status_code == 200 else {"error": r.text[:200]}
    ans = d.get("answers", {})
    print(f"{label}: status={r.status_code} n_answers={len(ans)} "
          f"names={list(ans.keys())[:10]} time={dt:.1f}s")
    return d


# 1) noul x3
n3 = {f"n{i}": {"type": "noul",
                 "instructions": f'Does candidate {i} answer the question "{q["query"]}"?',
                 "criteria": {"true": "directly answers the question",
                              "false": "does not answer it"}}
      for i in range(3)}
d = call(n3, "noul x3")
if d.get("answers"):
    print("   values:", {k: v.get("noul") for k, v in d["answers"].items()})

# 2) noul x10
n10 = {f"n{i}": {"type": "noul",
                  "instructions": f'Does candidate {i} answer the question "{q["query"]}"?',
                  "criteria": {"true": "directly answers the question",
                               "false": "does not answer it"}}
       for i in range(10)}
d = call(n10, "noul x10")
if d.get("answers"):
    print("   values:", {k: round(v.get("noul", -1), 2) for k, v in d["answers"].items()})

# 3) score x3 (reconfirm earlier cap finding)
s3 = {f"s{i}": {"type": "score", "instructions": "How relevant is candidate i?",
                "criteria": ["irrelevant", "somewhat related", "relevant", "exactly answers"]}
      for i in range(3)}
call(s3, "score x3")

# 4) choice x100
qs = {"best": {"type": "choice",
               "instructions": "Which candidate is the single best evidence for answering the question?",
               "criteria": {f"c{i}": (c.short_excerpt or "")[:80] for i, c in enumerate(cands)}}}
d = call(qs, f"choice x{len(cands)}")
a = (d.get("answers") or {}).get("best") or {}
if a:
    probs = a.get("probabilities", {})
    print(f"   choice={a.get('choice')} conf={a.get('confidence')} n_probs={len(probs)}")
    top = sorted(probs.items(), key=lambda x: -x[1])[:5]
    print("   top probs:", top)