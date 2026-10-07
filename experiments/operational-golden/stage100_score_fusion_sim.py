# -*- coding: utf-8 -*-
"""stage100: 점수 융합(convex combination α) 0콜 사전 시뮬 — RRF vs score fusion

배경 (2026-10-08):
- Hindsight/core.today 실측: 등가중 RRF는 약한 lane에 잡아먹히고, min-max 정규화 +
  convex combination(α·vec + (1−α)·BM25)이 α=0.9에서 RRF를 이김 (외부 코퍼스).
- 우리는 RRF(k=30)만 사용. α 융합은 우리가 안 해본 레버.
- 목표: op-90(스냅샷 고정)에서 lane 원점수(FTS rank→score 변환, vec sim)를 재현해
  RRF vs α 스윕의 gold rank 분포·hit 상한을 0콜로 비교 → '유망 α 구간' 좁히기.
  (시뮬은 검색 정책 시뮬: '시뮬 유망 ≠ 실측 승리' — stage79/80 경험. 결론은
   same-session paired + flip 대조표로만.)

주의:
- 스냅샷 DB read-only. JEV 콜 0회.
- lane 원점수는 빌트인 함수가 rank만 주는 경우가 있어 직접 수집:
  FTS `rank`(낮을수록 좋음 → score 변환), vec `sim`(높을수록 좋음),
  imp/graph는 rank만 있음 → rank 기반 1/(k+r) 기여.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)

from gateway import j1_pipeline as j1p
from mnemosyne.core import beam as beam_mod
from mnemosyne.core import embeddings as emb_mod

SNAP = os.path.join(REPO, "experiments", "operational-golden", "snapshots", "mnemosyne_snapshot_20261006.db")
DATA = os.path.join(REPO, "experiments", "operational-golden", "data")

# op-90 쿼리 + gold id: stage54 raw에서 추출 (같은 스냅샷 기준)
def load_op90():
    with open(os.path.join(DATA, "stage54_op90_regress.json"), encoding="utf-8") as fh:
        d = json.load(fh)
    # stage54는 cond dict 내부 records or list
    recs = None
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, list) and v and isinstance(v[0], dict) and "gold" in v[0]:
                recs = v
                break
    if recs is None:
        raise SystemExit("stage54 op-90 구조 인식 실패")
    out = []
    for r in recs:
        q = r.get("query") or r.get("q")
        g = r.get("gold") or r.get("gold_id")
        if q and g:
            out.append({"q": q, "gold": g})
    return out

def lane_scores(s, query, k=200):
    """4-lane 원점수 수집 → {id: {lane: score(높을수록 좋음), rank}}"""
    out = {}
    def add(lane, rows):
        for i, r in enumerate(rows, start=1):
            cid = r["id"]
            e = out.setdefault(cid, {})
            e[f"{lane}_rank"] = i
            if lane == "fts":
                e["fts_score"] = -float(r.get("rank", 0.0))  # FTS rank 낮을수록 좋음 → 부호 반전
            elif lane == "vec":
                e["vec_score"] = float(r.get("sim", 0.0))
            elif lane == "imp":
                e["imp_rank_only"] = True
            elif lane == "graph":
                e["graph_rank_only"] = True
    # fts
    try:
        add("fts", beam_mod._fts_search_working(s, query, k=k))
    except Exception:
        pass
    # vec
    try:
        qemb = emb_mod.embed([query])
        if qemb is not None and len(qemb):
            add("vec", beam_mod._wm_vec_search(s, qemb[0], k=k))
    except Exception:
        pass
    # imp
    try:
        add("imp", j1p._imp_search(s, k=k))
    except Exception:
        pass
    # graph
    try:
        add("graph", j1p._graph_lane_search(s, query, k=k))
    except Exception:
        pass
    return out

def rrf_score(e, k=30):
    """현행 RRF — lane rank 기여 합"""
    total = 0.0
    for lane in ("fts_rank", "vec_rank", "imp_rank", "graph_rank"):
        r = e.get(lane)
        if r is not None:
            total += 1.0 / (k + r)
    return total

def fusion_score(e, alpha, lane_scores_all):
    """점수 융합: FTS·vec 원점수를 min-max 정규화 후 α·vec + (1−α)·fts.
    imp/graph는 순위만 있으므로 RRF 기여(1/(k+r))를 작은 보조 항으로 포함.
    min-max는 호출부에서 lane 전체에 대해 계산."""
    # e: {fts_score, vec_score, imp_rank, graph_rank}
    s_fts = e.get("fts_score")
    s_vec = e.get("vec_score")
    norm = {}
    for lane, key in (("fts", "fts_score"), ("vec", "vec_score")):
        vals = lane_scores_all.get(lane, [])
        if not vals:
            norm[key] = 0.0
            continue
        lo, hi = min(vals), max(vals)
        v = e.get(key)
        if v is None:
            norm[key] = 0.0
        else:
            norm[key] = (v - lo) / (hi - lo) if hi > lo else 0.5
    aux = 0.0
    for lane in ("imp_rank", "graph_rank"):
        r = e.get(lane)
        if r is not None:
            aux += 1.0 / (30 + r)
    return alpha * norm.get("vec_score", 0.0) + (1 - alpha) * norm.get("fts_score", 0.0) + 0.05 * aux

def main():
    s = sqlite3.connect(f"file:{SNAP}?mode=ro", uri=True)
    s.row_factory = sqlite3.Row
    queries = load_op90()
    print(f"op-90 쿼리: {len(queries)}")

    results = []
    for qi, item in enumerate(queries):
        q, gold = item["q"], item["gold"]
        # pool: 게이트 통과 후보 (운영과 동일: _filter_and_rank)
        # lane_scores는 id+rank+score만 수집하므로, 전체 후보를 hydrate하여
        # 운영 게이트(_filter_and_rank)를 그대로 적용해야 유효한 비교가 된다.
        # (stage100 v1은 게이트 없이 4-lane 유니온 전체를 pool로 써 RRF rank1이
        #  44/90으로 부풀려짐 — 게이트 통과 후 RRF 순위가 실제 운영과 다름.)
        # 여기서는 게이트 근사: content를 가져와 _filter_and_rank 호출.
        def recall_raw(kind, arg, kk):
            if kind == "fts":
                return beam_mod._fts_search_working(s, arg, k=kk)
            if kind == "vec":
                qemb = emb_mod.embed([arg])
                if qemb is None or not len(qemb):
                    return []
                return beam_mod._wm_vec_search(s, qemb[0], k=kk)
            if kind == "imp":
                return j1p._imp_search(s, k=kk)
            if kind == "graph":
                return j1p._graph_lane_search(s, arg, k=kk)
            if kind == "get":
                r = s.execute("SELECT id, content, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
                if not r:
                    r = s.execute("SELECT id, content, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
                return dict(r) if r else None
            return []
        pool = j1p.build_lane_pool(recall_raw, q)
        pool = j1p._filter_and_rank(pool, q)[:j1p.POOL_BUDGET]
        lanes = {c["id"]: {
            "fts_rank": (c.get("_lane_ranks") or {}).get("fts_rank"),
            "vec_rank": (c.get("_lane_ranks") or {}).get("vec_rank"),
            "imp_rank": (c.get("_lane_ranks") or {}).get("imp_rank"),
            "graph_rank": (c.get("_lane_ranks") or {}).get("graph_rank"),
        } for c in pool}
        # lane 원점수는 게이트 통과 후보에 대해 다시 수집 (pool이 작아짐)
        raw_scores = lane_scores(s, q)
        for cid, e in lanes.items():
            rs = raw_scores.get(cid, {})
            e["fts_score"] = rs.get("fts_score")
            e["vec_score"] = rs.get("vec_score")
        # 원점수 min-max 정규화를 lane 전체에 대해 계산
        lane_vals = {"fts": [], "vec": []}
        for e in lanes.values():
            if e.get("fts_score") is not None:
                lane_vals["fts"].append(e["fts_score"])
            if e.get("vec_score") is not None:
                lane_vals["vec"].append(e["vec_score"])
        # gold 포함 여부
        gold_in = gold in lanes
        rank_rrf = None
        ranks_fusion = {}
        if gold_in:
            rank_rrf = sorted(lanes, key=lambda cid: -rrf_score(lanes[cid])).index(gold) + 1
            for alpha in [0.0, 0.3, 0.5, 0.7, 0.8, 0.9, 0.95]:
                order = sorted(lanes, key=lambda cid: -fusion_score(lanes[cid], alpha, lane_vals))
                ranks_fusion[alpha] = order.index(gold) + 1
        results.append({
            "q": q, "gold": gold, "gold_in": gold_in, "pool_n": len(lanes),
            "rrf_rank": rank_rrf,
            "fusion_rank": ranks_fusion,
        })
        if (qi + 1) % 20 == 0:
            print(f"  {qi+1}/{len(queries)}", flush=True)

    json.dump(results, open(os.path.join(DATA, "stage100_fusion_sim_raw.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # 요약
    n_in = sum(1 for r in results if r["gold_in"])
    print(f"\ngold in pool: {n_in}/{len(results)}")
    print(f"RRF gold rank1: {sum(1 for r in results if r['rrf_rank'] == 1)} / rank<=3: {sum(1 for r in results if r['rrf_rank'] and r['rrf_rank'] <= 3)} / rank<=10: {sum(1 for r in results if r['rrf_rank'] and r['rrf_rank'] <= 10)}")
    for alpha in [0.0, 0.3, 0.5, 0.7, 0.8, 0.9, 0.95]:
        r1 = sum(1 for r in results if r["fusion_rank"].get(alpha) == 1)
        r3 = sum(1 for r in results if r["fusion_rank"].get(alpha) and r["fusion_rank"][alpha] <= 3)
        r10 = sum(1 for r in results if r["fusion_rank"].get(alpha) and r["fusion_rank"][alpha] <= 10)
        print(f"fusion α={alpha}: rank1={r1} rank<=3={r3} rank<=10={r10}")

if __name__ == "__main__":
    main()