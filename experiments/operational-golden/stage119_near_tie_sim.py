# -*- coding: utf-8 -*-
"""stage119_near_tie_sim.py — OMEGA near-tie bounded metadata 0콜 시뮬레이션 v2 (2026-10-10)

v1 교훈: _adjusted 점수는 importance lane 동점(0.045)이 지배해 Δ=0 149/150 인공물.
운영 순서는 build_lane_pool의 RRF 순서(안정 정렬 유지) — RRF가 진짜 semantic score.

v2: RRF 점수를 semantic score로, RRF 순위를 기준 순위로 사용.
  - 1·2위 RRF Δ로 near-tie 판정 (OMEGA SEMANTIC_NEAR_TIE_DELTA 상당)
  - bounded boost: near-tie 후보 2위(또는 gold)에 priority/access 기여(±b)를 RRF에 가산
    → 1위 추월(flip) 여부 + gold rank 이동 + gold 노출(상위 5) 영향
  - JEV winner 영향: Run R 실측(순서 변경 winner 무영향)으로 판정 — JEV 콜 0.

0콜. 스냅샷(2026-10-06)만 사용.
"""
import os, sys, json, sqlite3

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
os.chdir(REPO)

import gateway.j1_pipeline as j1p
from mnemosyne.core import beam as beam_mod
from mnemosyne.core import embeddings as emb_mod

SNAP = os.path.join(REPO, "experiments", "operational-golden", "snapshots", "mnemosyne_snapshot_20261006.db")
DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
OUT = os.path.join(DATA, "stage119_near_tie_raw_v2.json")

RRF_K = j1p.RRF_K
# OMEGA 상수 근사: SEMANTIC_NEAR_TIE_DELTA는 소스에서 확인 불가 — RRF Δ 분위로 스윕
NEAR_TIE_DELTAS = [1e-5, 1e-4, 5e-4, 1e-3, 2e-3, 5e-3, 1e-2]
BOOSTS = [0.0025, 0.01, 0.05]
EXPOSURE_K = 5  # 노출 상한 (hit 해석용)


def recall_raw_factory(conn):
    def recall_raw(kind, arg, k):
        if kind == "fts":
            return beam_mod._fts_search_working(conn, arg, k=k)
        if kind == "vec":
            qe = emb_mod.embed([arg])
            if qe is None or not len(qe):
                return []
            return beam_mod._wm_vec_search(conn, qe[0], k=k)
        if kind == "imp":
            return j1p._imp_search(conn, k=k)
        if kind == "graph":
            return j1p._graph_lane_search(conn, arg, k=k)
        if kind == "get":
            r = conn.execute("SELECT id, content, importance, created_at FROM working_memory WHERE id=?", (arg,)).fetchone()
            if not r:
                r = conn.execute("SELECT id, content, importance, created_at FROM episodic_memory WHERE id=?", (arg,)).fetchone()
            return dict(r) if r else None
        return []
    return recall_raw


def main():
    s = sqlite3.connect(SNAP)
    s.row_factory = sqlite3.Row

    gv3 = json.load(open(os.path.join(DATA, "golden_eval_v3.json"), encoding="utf-8"))
    noans = json.load(open(os.path.join(DATA, "golden_noanswer_queries.json"), encoding="utf-8"))

    qitems = []
    for q in gv3:
        qitems.append({"qid": "gv3_" + str(len(qitems)), "query": q["query"],
                       "gold": q["gold"], "cat": q.get("cat", "?")})
    for q in noans:
        if isinstance(q, dict) and q.get("query"):
            qitems.append({"qid": "noans_" + str(len(qitems)), "query": q["query"],
                           "gold": (q.get("gold_ids") or [None])[0], "cat": "NO_ANSWER"})

    results = []
    stats = {"total": 0, "pool_ok": 0, "gold_in_pool": 0}

    for item in qitems:
        query, gold = item["query"], item["gold"]
        pool = j1p.build_lane_pool(recall_raw_factory(s), query)
        passed = j1p._filter_and_rank(pool, query)[:j1p.POOL_BUDGET]
        stats["total"] += 1
        if not passed:
            continue
        stats["pool_ok"] += 1

        rows = []
        for r in passed:
            lr = r.get("_lane_ranks") or {}
            rows.append({
                "id": r["id"],
                "importance": float(r.get("importance") or 0.0),
                "rrf": sum(1.0 / (RRF_K + v) for v in lr.values()) if lr else 0.0,
                "lane_ranks": {k: v for k, v in lr.items()},
            })
        if not rows:
            continue
        if gold in [r["id"] for r in rows]:
            stats["gold_in_pool"] += 1

        # RRF 순위 (운영 순서 = build_lane_pool RRF 정렬 후 안정 정렬 → RRF 순위)
        rows.sort(key=lambda x: -x["rrf"])
        for i, r in enumerate(rows, start=1):
            r["rrf_rank"] = i

        gold_row = next((r for r in rows if r["id"] == gold), None)
        gold_rank = gold_row["rrf_rank"] if gold_row else None

        delta_top = rows[0]["rrf"] - rows[1]["rrf"] if len(rows) > 1 else None

        sims = {}
        for dt in NEAR_TIE_DELTAS:
            near = delta_top is not None and delta_top <= dt
            for b in BOOSTS:
                k = f"dt{dt}_b{b}"
                if not near or len(rows) < 2:
                    sims[k] = "not_near" if not near else "no_second"
                else:
                    # 2위 + boost > 1위? (2위가 priority/access로 추월)
                    sims[k] = "flip" if (rows[1]["rrf"] + b) > rows[0]["rrf"] else "no_flip"
        # gold 승격 시나리오 (gold가 2위 이하이고 near-tie일 때 gold+boost → 1위?)
        for dt in NEAR_TIE_DELTAS:
            for b in BOOSTS:
                k = f"g{dt}_b{b}"
                if gold_row is None or gold_rank == 1:
                    sims[k] = "gold_top1_or_none"
                else:
                    near = delta_top is not None and delta_top <= dt
                    if not near:
                        sims[k] = "not_near"
                    else:
                        sims[k] = "gold_top1" if (gold_row["rrf"] + b) > rows[0]["rrf"] else "no"

        # gold 노출 영향: gold가 노출(상위5) 경계 밖이었다가 boost로 진입/이탈
        gold_exp_before = gold_rank is not None and gold_rank <= EXPOSURE_K
        # 6위 gold가 boost 받으면 노출 진입 (승격 시나리오에서만)
        results.append({
            "qid": item["qid"], "cat": item["cat"], "query": query[:50],
            "gold": gold, "gold_rank": gold_rank,
            "gold_exp_before": gold_exp_before,
            "pool_n": len(rows),
            "delta_top_rrf": delta_top,
            "top1_rrf": rows[0]["rrf"], "top2_rrf": rows[1]["rrf"] if len(rows) > 1 else None,
            "top1_lanes": rows[0]["lane_ranks"], "top2_lanes": rows[1]["lane_ranks"] if len(rows) > 1 else {},
            "sims": sims,
        })

    s.close()

    n_ok = stats["pool_ok"]
    near_counts = {dt: sum(1 for r in results if r["delta_top_rrf"] is not None and r["delta_top_rrf"] <= dt) for dt in NEAR_TIE_DELTAS}
    flip_counts, gold_top1_counts = {}, {}
    for r in results:
        for k, v in r["sims"].items():
            if v == "flip":
                flip_counts[k] = flip_counts.get(k, 0) + 1
            elif v == "gold_top1":
                gold_top1_counts[k] = gold_top1_counts.get(k, 0) + 1
    from collections import Counter
    grd = Counter(r["gold_rank"] for r in results if r["gold_rank"] is not None)

    summary = {
        "total": stats["total"], "pool_ok": n_ok, "gold_in_pool": stats["gold_in_pool"],
        "near_tie_counts_rrf": near_counts,
        "near_tie_ratio_rrf": {str(dt): round(near_counts[dt] / max(n_ok, 1), 4) for dt in NEAR_TIE_DELTAS},
        "flip_counts": flip_counts,
        "gold_top1_counts": gold_top1_counts,
        "gold_rank_dist": dict(sorted(grd.items())),
        "gold_rank_top1": grd.get(1, 0),
        "gold_rank_le5": sum(v for k, v in grd.items() if 1 <= k <= 5),
        "gold_exp_before_count": sum(1 for r in results if r["gold_exp_before"]),
    }
    json.dump({"summary": summary, "results": results}, open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print("OUT:", OUT)


if __name__ == "__main__":
    main()
