"""Phase 0 runner — Mnemosyne-only baseline against a snapshot DB.

Usage:
    .venv/Scripts/python.exe -m experiments.run_baseline \
        --snapshot <path-to-snapshot.db> \
        --queries experiments/dataset/queries.json \
        --out experiments/results/baseline_<ts>.json

Reads queries.json: [{"id","query","type","gold_ids":[...]}]
Writes results JSON + appends one ledger row (experiments/results/ledger.jsonl).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from backends.mnemosyne import MnemosyneBackend
from experiments.metrics import summarize, ndcg_at_k, recall_at_k, mrr, evidence_hit


def run_queries(backend: MnemosyneBackend, queries: list[dict], top_k: int = 30) -> list[dict]:
    per_query = []
    for q in queries:
        qid = q.get("qid") or q.get("id")
        gold = set(q.get("gold_ids", []))
        t0 = time.perf_counter()
        hits = backend.recall(q["query"], top_k=top_k)
        dt = (time.perf_counter() - t0) * 1000
        recalled = [h.id for h in hits]
        row = {
            "query_id": qid,
            "query_type": q.get("type", ""),
            "recalled_ids": recalled,
            "n_candidates": len(recalled),
            "latency_ms": round(dt, 1),
            "gold_ids": sorted(gold),
        }
        for k in (1, 3, 5, 10):
            row[f"recall@{k}"] = recall_at_k(recalled, gold, k)
            row[f"ndcg@{k}"] = ndcg_at_k(recalled, gold, k)
            row[f"evidence_hit@{k}"] = evidence_hit(recalled, gold, k)
        row["mrr"] = mrr(recalled, gold)
        per_query.append(row)
    return per_query


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--queries", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--top-k", type=int, default=30)
    args = ap.parse_args()

    queries = json.loads(Path(args.queries).read_text(encoding="utf-8"))
    backend = MnemosyneBackend(db_path=args.snapshot)

    t0 = time.perf_counter()
    per_query = run_queries(backend, queries, top_k=args.top_k)
    total_s = time.perf_counter() - t0

    agg = summarize(per_query)
    result = {
        "phase": "baseline",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "snapshot": args.snapshot,
        "queries_file": args.queries,
        "top_k": args.top_k,
        "n_queries": len(queries),
        "total_seconds": round(total_s, 2),
        "aggregate": agg,
        "per_query": per_query,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # ledger row (one line per run)
    ledger = Path(args.out).with_name("ledger.jsonl")
    with ledger.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": result["timestamp"], "phase": "baseline", "top_k": args.top_k,
            "n_queries": len(queries),
            "recall@10": agg["recall@10"], "ndcg@10": agg["ndcg@10"], "mrr": agg["mrr"],
            "evidence_hit@10": agg["evidence_hit@10"],
            "total_seconds": round(total_s, 2), "out": str(out),
        }, ensure_ascii=False) + "\n")

    print(json.dumps(agg, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()