"""Phase 1-v2 — Jev choice-based rerank (TypeSafe System One).

score questions are capped at 2 answers per request on typesafe jev-latest
(measured), so reranking by score is useless. Choice questions work: the model
picks the single best candidate from the whole pool with a probability vector.

Pipeline:
  query -> lane pool (FTS+vec, top-100) -> candidate headers
        -> Jev choice: "pick the single best evidence" (1 call per query)
        -> rerank: chosen candidate first, rest by pool order (or by
           probability-weighted RRF)
        -> top-k -> metrics vs gold

Systems compared:
  A: lane pool RRF-only (no Jev)            [baseline, from phase1_jev40]
  J1: Jev choice top1 lifted to rank 1, rest pool order
  J3: Jev choice top3 (3 calls) lifted to ranks 1-3, rest pool order
  JP: Jev choice probabilities -> weighted RRF with mnemosyne rank

Run: .venv/Scripts/python.exe -m experiments.run_phase1_v2 --out results/phase1v2.json
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backends.mnemosyne import MnemosyneBackend
from experiments.lane_pool import LanePool
from experiments.metrics import ndcg_at_k, recall_at_k, mrr, evidence_hit
from gateway.excerpts import build_excerpt
from jev_controller.scorer import JevScorer

SNAP = r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\snapshots\snap-20260927.db"
QUERIES = r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\dataset_curated.json"


def build_state(query: str, candidates) -> dict:
    """State = question + candidate headers (spec §18: headers only)."""
    headers = []
    for c in candidates:
        headers.append({
            "id": c.id[:12],
            "type": c.memory_type or "",
            "scope": c.scope or "",
            "importance": c.importance,
            "source": c.source_agent or "",
            "excerpt": (c.short_excerpt or "")[:120],
        })
    return {"question": query, "candidates": headers}


def jev_choice(client, state: dict, labels: list[str], n_picks: int = 1,
               timeout: float = 30.0) -> list[str]:
    """Ask Jev to pick the single best candidate. Returns chosen labels (c0..)."""
    questions = {
        "best": {
            "type": "choice",
            "instructions": (
                "Which candidate memory is the single best evidence for answering "
                "the question? Pick exactly one. Consider directness and specificity."
            ),
            "criteria": {f"c{i}": labels[i] for i in range(len(labels))},
        }
    }
    t0 = time.perf_counter()
    resp = client.post(
        "https://api.typesafe.ai/v1/systemone",
        json={"state": state, "questions": questions, "model": "jev-latest"},
        timeout=timeout,
    )
    latency = (time.perf_counter() - t0) * 1000
    if resp.status_code != 200:
        print(f"[jeVchoice] HTTP {resp.status_code}: {resp.text[:150]}")
        return [], latency
    d = resp.json()
    ans = (d.get("answers") or {}).get("best") or {}
    choice = ans.get("choice")
    if choice is None:
        return [], latency
    # choice like "c3" -> index 3
    try:
        idx = int(str(choice).lstrip("c"))
        return [f"c{idx}"], latency
    except ValueError:
        return [], latency


def rerank_jevlift(pool_ranked: list, jev_idx: int) -> list:
    """Chosen candidate to front, rest keep pool order."""
    out = [pool_ranked[jev_idx]] if 0 <= jev_idx < len(pool_ranked) else []
    for i, cid in enumerate(pool_ranked):
        if i != jev_idx:
            out.append(cid)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\results\phase1v2.json")
    ap.add_argument("--no-jev", action="store_true")
    ap.add_argument("--budget", type=int, default=40, help="candidates in Jev choice pool")
    ap.add_argument("--picks", type=int, default=3, help="how many choice questions (best1..bestN)")
    args = ap.parse_args()

    Q = json.loads(Path(QUERIES).read_text(encoding="utf-8"))
    b = MnemosyneBackend(db_path=SNAP)
    beam = b._ensure_beam()
    pool = LanePool(beam, fts_budget=60, vec_budget=60, rrf_k=30)

    key = os.environ.get("TYPESAFE_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    use_jev = (not args.no_jev) and bool(key)
    client = None
    if use_jev:
        client = JevScorer(api_key=key, timeout=30.0, batch_size=args.budget,
                           endpoint="https://api.typesafe.ai/v1/systemone",
                           mode="typesafe", model="jev-latest")._client_sync()

    per_query = []
    total_lat = 0.0
    n_calls = 0
    for q in Q:
        gold = set(q["gold_ids"])
        cands = pool.retrieve(q["query"], budget=100)
        for c in cands:
            row = beam.get(c.id)
            content = row.get("content", "") if isinstance(row, dict) and row else ""
            c.short_excerpt = build_excerpt(content, c.memory_type)
        ids = [c.id for c in cands]
        a_ranked = list(ids)  # lane RRF order

        if use_jev:
            sub = cands[:args.budget]
            state = build_state(q["query"], sub)
            labels = [(c.short_excerpt or "")[:100] or "n/a" for c in sub]
            picks_idx = []
            for p in range(args.picks):
                chosen, lat = jev_choice(client, state, labels)
                total_lat += lat
                n_calls += 1
                if chosen:
                    picks_idx.append(int(chosen[0].lstrip("c")))
            # build variants
            j1 = rerank_jevlift(a_ranked, picks_idx[0] if picks_idx else -1)
            # j3: lift up to 3 picks (in pick order), rest pool order
            j3 = list(a_ranked)
            for rank, idx in enumerate(picks_idx[:3]):
                # move chosen to front progressively
                j3 = rerank_jevlift(j3, j3.index(a_ranked[idx]) if a_ranked[idx] in j3 else -1)
            # jp: probability-weighted — use pool order but lift chosen to front
            jp = j3 if picks_idx else a_ranked
        else:
            j1 = j3 = jp = a_ranked

        row = {
            "query_id": q["qid"], "query_type": q.get("type", ""),
            "gold_ids": sorted(gold), "n_candidates": len(ids),
            "jev_picks": picks_idx if use_jev else [],
            "A_ranked": a_ranked[:10],
            "J1_ranked": j1[:10], "J3_ranked": j3[:10] if use_jev else [],
        }
        for k in (1, 3, 5, 10):
            row[f"A_recall@{k}"] = recall_at_k(a_ranked, gold, k)
            row[f"A_ndcg@{k}"] = ndcg_at_k(a_ranked, gold, k)
            row[f"J1_recall@{k}"] = recall_at_k(j1, gold, k)
            row[f"J1_ndcg@{k}"] = ndcg_at_k(j1, gold, k)
            if use_jev:
                row[f"J3_recall@{k}"] = recall_at_k(j3, gold, k)
                row[f"J3_ndcg@{k}"] = ndcg_at_k(j3, gold, k)
        row["A_mrr"] = mrr(a_ranked, gold)
        row["J1_mrr"] = mrr(j1, gold)
        if use_jev:
            row["J3_mrr"] = mrr(j3, gold)
        per_query.append(row)

    out = {
        "n_queries": len(per_query), "jev_used": use_jev,
        "budget": args.budget, "picks": args.picks,
        "total_jev_calls": n_calls, "total_latency_ms": round(total_lat, 1),
    }
    for prefix in ("A", "J1", "J3"):
        if prefix == "J3" and not use_jev:
            continue
        for k in (1, 3, 5, 10):
            out[f"{prefix}_recall@{k}"] = sum(r[f"{prefix}_recall@{k}"] for r in per_query) / len(per_query)
            out[f"{prefix}_ndcg@{k}"] = sum(r[f"{prefix}_ndcg@{k}"] for r in per_query) / len(per_query)
        out[f"{prefix}_mrr"] = sum(r[f"{prefix}_mrr"] for r in per_query) / len(per_query)
    out["per_query"] = per_query

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: round(v, 4) for k, v in out.items() if isinstance(v, float)}, indent=2))
    print(f"Jev calls: {n_calls}, total latency {total_lat:.0f}ms")


if __name__ == "__main__":
    main()