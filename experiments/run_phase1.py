"""Phase 1 — Jev rerank + RRF over lane-based candidate pool.

Pipeline (spec §9):
  query -> lane pool (FTS+vec, top-100) -> candidate headers
        -> Jev scoring (Decisions API) -> RRF(Mnemosyne rank, Jev rank)
        -> top-k -> metrics vs gold

Systems compared (spec §11):
  A: lane pool RRF-only (no Jev)         [lane baseline]
  B: Jev rerank alone (Jev rank top-k)
  C: RRF(mnemosyne, Jev) with k=10/20/30/60

Run: .venv/Scripts/python.exe -m experiments.run_phase1 --out results/phase1.json
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
from experiments.metrics import ndcg_at_k, recall_at_k, mrr, evidence_hit, summarize
from gateway.excerpts import build_excerpt
from jev_controller.fusion import rrf_rank, rank_from_scores
from jev_controller.scorer import JevScorer

SNAP = r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\snapshots\snap-20260927.db"
QUERIES = r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\dataset_curated.json"


def build_headers(cands) -> list[dict]:
    """cands: list of MemoryCandidate (from LanePool.retrieve)."""
    out = []
    for c in cands:
        out.append({
            "id": c.id,
            "memory_type": c.memory_type,
            "scope": c.scope,
            "importance": c.importance,
            "source_agent": c.source_agent,
            "excerpt": c.short_excerpt,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\results\phase1.json")
    ap.add_argument("--no-jev", action="store_true", help="skip Jev call (A-only)")
    ap.add_argument("--jev-budget", type=int, default=40, help="max candidates scored by Jev per query")
    ap.add_argument("--jev-scale", choices=["3", "5"], default="5", help="Jev score rubric width")
    args = ap.parse_args()

    Q = json.loads(Path(QUERIES).read_text(encoding="utf-8"))
    b = MnemosyneBackend(db_path=SNAP)
    beam = b._ensure_beam()
    pool = LanePool(beam, fts_budget=60, vec_budget=60, rrf_k=30)

    scorer = None
    if not args.no_jev:
        key = os.environ.get("TYPESAFE_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
        if not key:
            print("[phase1] API key 없음 — A-only로 진행")
            args.no_jev = True
        else:
            # TypeSafe direct (TYPESAFE_API_KEY) else OpenRouter Decisions
            if os.environ.get("TYPESAFE_API_KEY"):
                scorer = JevScorer(api_key=key, timeout=25.0, batch_size=args.jev_budget,
                                   endpoint="https://api.typesafe.ai/v1/systemone",
                                   mode="typesafe", model="jev-latest")
            else:
                scorer = JevScorer(api_key=key, timeout=20.0, batch_size=args.jev_budget)

    per_query = []
    for q in Q:
        gold = set(q["gold_ids"])
        cands = pool.retrieve(q["query"], budget=100)
        # candidate headers (excerpt)
        cands = prepare_candidates_for_pool(cands, beam)
        ids = [c.id for c in cands]

        # A: lane pool RRF ranking (mnemosyne_rank = pool order)
        a_ranked = list(ids)  # already RRF-ordered by pool

        # B/C: Jev scoring on top-jev_budget
        jev_scores = {}
        if scorer and not args.no_jev:
            scored = cands[:args.jev_budget]
            try:
                jev_scores = scorer.score_candidates(q["query"], scored) or {}
            except Exception as e:
                print(f"[phase1] Jev fail {q['qid']}: {e}")
                jev_scores = {}

        jev_rank = {cid: i + 1 for i, cid in enumerate(
            sorted(ids, key=lambda cid: -jev_scores.get(cid, -1)))} if jev_scores else {}

        # B: Jev rerank alone
        b_ranked = [cid for cid, _ in sorted(
            ((cid, jev_scores.get(cid, -1)) for cid in ids), key=lambda x: -x[1])] if jev_scores else a_ranked

        # C: RRF for each k
        c_ranked = {}
        if jev_scores:
            m_rank = {c.id: i + 1 for i, c in enumerate(cands)}
            j_rank = rank_from_scores(jev_scores, tiebreak=m_rank)
            for k in (10, 20, 30, 60):
                c_ranked[k] = rrf_rank(m_rank, j_rank, k=k)
        else:
            for k in (10, 20, 30, 60):
                c_ranked[k] = a_ranked

        row = {
            "query_id": q["qid"], "query_type": q.get("type", ""),
            "gold_ids": sorted(gold),
            "n_candidates": len(ids),
            "jev_scores_count": len(jev_scores),
            "A_ranked": a_ranked[:10],
            "B_ranked": b_ranked[:10] if jev_scores else [],
            "C_ranked": {str(k): v[:10] for k, v in c_ranked.items()} if jev_scores else {},
        }
        for k in (1, 3, 5, 10):
            row[f"A_recall@{k}"] = recall_at_k(a_ranked, gold, k)
            row[f"A_ndcg@{k}"] = ndcg_at_k(a_ranked, gold, k)
            row[f"B_recall@{k}"] = recall_at_k(b_ranked, gold, k) if jev_scores else 0.0
            row[f"B_ndcg@{k}"] = ndcg_at_k(b_ranked, gold, k) if jev_scores else 0.0
            for kk in (10, 20, 30, 60):
                row[f"C{kk}_recall@{k}"] = recall_at_k(c_ranked[kk], gold, k) if jev_scores else 0.0
                row[f"C{kk}_ndcg@{k}"] = ndcg_at_k(c_ranked[kk], gold, k) if jev_scores else 0.0
        row["A_mrr"] = mrr(a_ranked, gold)
        row["B_mrr"] = mrr(b_ranked, gold) if jev_scores else 0.0
        row["A_evidence@30"] = evidence_hit(a_ranked, gold, 30)
        per_query.append(row)

    # aggregate
    out = {"n_queries": len(per_query), "jev_used": scorer is not None and not args.no_jev, "per_query": per_query}
    for prefix in ("A", "B"):
        for k in (1, 3, 5, 10):
            out[f"{prefix}_recall@{k}"] = sum(r[f"{prefix}_recall@{k}"] for r in per_query) / len(per_query)
            out[f"{prefix}_ndcg@{k}"] = sum(r[f"{prefix}_ndcg@{k}"] for r in per_query) / len(per_query)
        out[f"{prefix}_mrr"] = sum(r[f"{prefix}_mrr"] for r in per_query) / len(per_query)
    for kk in (10, 20, 30, 60):
        for k in (1, 3, 5, 10):
            out[f"C{kk}_recall@{k}"] = sum(r[f"C{kk}_recall@{k}"] for r in per_query) / len(per_query)
            out[f"C{kk}_ndcg@{k}"] = sum(r[f"C{kk}_ndcg@{k}"] for r in per_query) / len(per_query)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: round(v, 4) for k, v in out.items() if isinstance(v, float)}, indent=2))


def prepare_candidates_for_pool(cands, beam):
    """Fill short_excerpt from full content for scorer headers."""
    out = []
    for c in cands:
        row = beam.get(c.id)
        content = row.get("content", "") if isinstance(row, dict) and row else ""
        c.short_excerpt = build_excerpt(content, c.memory_type)
        out.append(c)
    return out


if __name__ == "__main__":
    main()