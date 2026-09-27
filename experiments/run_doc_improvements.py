"""Doc-based improvements experiment (Exp 2-5) — all in one runner.

Exp 2 (improvement 2): Choice probabilities as full relevance ranking
  C_p: rank by probabilities (not just lift winner)
Exp 3 (improvement 1): Noul per candidate -> sort by noul
  N: noul ranking (all candidates in one request)
Exp 4 (improvement 3): Confidence-gated routing
  J1c: J1 but only lift if confidence >= threshold (0.6)
Exp 5 (improvement 4): Budget 100 (full pool) instead of 40
  B100: choice over all 100 candidates

Metrics vs A (lane RRF) and J1 (old winner).
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from backends.mnemosyne import MnemosyneBackend
from experiments.lane_pool import LanePool
from experiments.metrics import ndcg_at_k, recall_at_k, mrr, evidence_hit
from gateway.excerpts import build_excerpt

SNAP = r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\snapshots\snap-20260927.db"
QUERIES = r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\dataset_curated.json"
API = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"


def call_api(state, questions, timeout=60.0):
    r = httpx.post(API,
                   headers={"Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}",
                            "Content-Type": "application/json"},
                   json={"state": state, "questions": questions, "model": MODEL},
                   timeout=timeout)
    if r.status_code != 200:
        return {}, r.status_code
    return r.json(), 200


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\results\doc_improvements.json")
    ap.add_argument("--no-jev", action="store_true")
    ap.add_argument("--limit", type=int, default=52)
    ap.add_argument("--conf-threshold", type=float, default=0.6)
    args = ap.parse_args()

    Q = json.loads(Path(QUERIES).read_text(encoding="utf-8"))[:args.limit]
    b = MnemosyneBackend(db_path=SNAP)
    beam = b._ensure_beam()
    pool = LanePool(beam, fts_budget=60, vec_budget=60, rrf_k=30)
    use_jev = (not args.no_jev) and bool(os.environ.get("TYPESAFE_API_KEY"))

    per_query = []
    total_lat = 0.0
    for q in Q:
        gold = set(q["gold_ids"])
        cands = pool.retrieve(q["query"], budget=100)
        for c in cands:
            row = beam.get(c.id)
            content = row.get("content", "") if isinstance(row, dict) and row else ""
            c.short_excerpt = build_excerpt(content, c.memory_type)
        ids = [c.id for c in cands]
        a_ranked = list(ids)

        if not use_jev:
            variants = {"A": a_ranked}
        else:
            # state: headers only (all candidates)
            state = {"question": q["query"], "candidates": [
                {"id": c.id[:12], "excerpt": (c.short_excerpt or "")[:120]} for c in cands]}
            variants = {"A": a_ranked}

            # ---- Exp 2: Choice probabilities as full ranking ----
            choice_q = {
                "best": {"type": "choice",
                         "instructions": "Which candidate memory is the single best evidence for answering the question? Pick exactly one.",
                         "criteria": {f"c{i}": (c.short_excerpt or "")[:80] for i, c in enumerate(cands)}}
            }
            d, st = call_api(state, choice_q)
            ans = (d.get("answers") or {}).get("best") or {}
            probs = ans.get("probabilities") or {}
            conf = ans.get("confidence") or 0.0
            choice_idx = None
            if ans.get("choice"):
                try:
                    choice_idx = int(str(ans["choice"]).lstrip("c"))
                except ValueError:
                    pass
            # C_p: full ranking by probabilities desc (unscored -> -1)
            c_p = sorted(ids, key=lambda cid: -probs.get(ids.index(cid), -1))
            # J1c: lift winner only if confidence >= threshold
            j1 = list(a_ranked)
            if choice_idx is not None and 0 <= choice_idx < len(ids):
                j1 = [ids[choice_idx]] + [c for c in a_ranked if c != ids[choice_idx]]
            j1c = j1 if conf >= args.conf_threshold else a_ranked
            variants["C_p"] = c_p
            variants["J1"] = j1
            variants["J1c"] = j1c

            # ---- Exp 3: Noul per candidate ----
            noul_q = {
                f"n{i}": {"type": "noul",
                          "instructions": f'Does candidate memory {i} answer the question "{q["query"]}"?',
                          "criteria": {"true": "the candidate directly and fully answers the question",
                                       "false": "the candidate does not answer the question"}}
                for i in range(len(cands))
            }
            d2, st2 = call_api(state, noul_q)
            nouls = {}
            for k, v in (d2.get("answers") or {}).items():
                if k.startswith("n") and v.get("type") == "noul":
                    nouls[int(k[1:])] = v.get("noul", 0.0)
            # N: sort by noul desc
            n_rank = sorted(ids, key=lambda cid: -nouls.get(ids.index(cid), -1))
            variants["N"] = n_rank

            # ---- Exp 5: Budget 100 (full pool choice) — same as choice above since
            # we already used all candidates; mark it for reporting.
            variants["B100"] = j1  # same as J1 (choice over full pool)

        row = {
            "query_id": q["qid"], "query_type": q.get("type", ""),
            "gold_ids": sorted(gold), "n_candidates": len(ids),
            "conf": conf if use_jev else None,
        }
        for name, ranked in variants.items():
            for k in (1, 3, 5, 10):
                row[f"{name}_recall@{k}"] = recall_at_k(ranked, gold, k)
                row[f"{name}_ndcg@{k}"] = ndcg_at_k(ranked, gold, k)
            row[f"{name}_mrr"] = mrr(ranked, gold)
        per_query.append(row)

    out = {"n_queries": len(per_query), "jev_used": use_jev,
           "conf_threshold": args.conf_threshold}
    for name in ["A", "C_p", "J1", "J1c", "N", "B100"]:
        probe = f"{name}_recall@1"
        if probe not in per_query[0]:
            continue
        for k in (1, 3, 5, 10):
            out[f"{name}_recall@{k}"] = sum(r[f"{name}_recall@{k}"] for r in per_query) / len(per_query)
            out[f"{name}_ndcg@{k}"] = sum(r[f"{name}_ndcg@{k}"] for r in per_query) / len(per_query)
        out[f"{name}_mrr"] = sum(r[f"{name}_mrr"] for r in per_query) / len(per_query)
    out["per_query"] = per_query

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: round(v, 4) for k, v in out.items() if isinstance(v, float)}, indent=2))
    print(f"Jev calls: {len(per_query) * 2} approx, total lat {total_lat:.0f}ms")


if __name__ == "__main__":
    main()