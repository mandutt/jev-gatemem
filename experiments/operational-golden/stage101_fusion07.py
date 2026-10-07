# -*- coding: utf-8 -*-
"""stage101: 점수 융합(α=0.7) 실측 — RRF(cu) vs fusion α=0.7 (2026-10-08)

stage100 0콜 시뮬: fusion α=0.7이 gold rank1 +6(44→50), rank<=3 +8, rank<=10 +5로
유망. 단 stage80 교훈(JEV는 rank1 전용 picker가 아님)대로 '시뮬 유망 ≠ 실측 승리'
— same-session paired 3셋 회귀(op-90 + noans-50 + live-60) + flip 대조표로 확정.

설계 (stage54/63/82 절차 재사용):
- cond cu: 게이트 통과 후 RRF 순서 보존(_filter_and_rank 그대로) → JEV choice
- cond fu: 게이트 통과 후보를 fusion α=0.7 재정렬 → JEV choice
  fusion score = α·norm(vec_score) + (1-α)·norm(fts_score) + 0.05·(imp+graph RRF 기여)
  (min-max 정규화는 쿼리별 lane 전체에 대해)
- 같은 세션에서 두 cond를 쿼리별로 alternate (paired)
- 셋: op-90(gold 존재) + noans-50(FP) + live-60(교차)
- 콜: 200쿼리 × 2 cond = 400콜 ≈ 1.9M 토큰 (일일 47.6M의 4%)
"""
from __future__ import annotations

import json
import os
import sys
import time
import sqlite3

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)

import stage48_live60_cross as m48
import gateway.j1_pipeline as j1p
from jev_mem_core.pipeline import _jev_client
from mnemosyne.core import beam as beam_mod
from mnemosyne.core import embeddings as emb_mod

SNAP = m48.SNAP
DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
s = sqlite3.connect(f"file:{SNAP}?mode=ro", uri=True)
s.row_factory = sqlite3.Row

ABSTAIN_CUR = m48.ABSTAIN_CURRENT
ALPHA = 0.7

def recall_raw_factory(q):
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
    return recall_raw

def build_pool(q, cap=60):
    """게이트 통과 후보 (운영과 동일) — lane rank·raw score 부착"""
    pool = j1p.build_lane_pool(recall_raw_factory(q), q)
    pool = j1p._filter_and_rank(pool, q)[:cap]
    # lane raw score 수집 (fts_score, vec_score)
    raw = lane_scores(q)
    for c in pool:
        rs = raw.get(c["id"], {})
        c["_fts_score"] = rs.get("fts_score")
        c["_vec_score"] = rs.get("vec_score")
    return pool

def lane_scores(q, k=200):
    out = {}
    try:
        for i, r in enumerate(beam_mod._fts_search_working(s, q, k=k), start=1):
            out.setdefault(r["id"], {})["fts_score"] = -float(r.get("rank", 0.0))
    except Exception:
        pass
    try:
        qemb = emb_mod.embed([q])
        if qemb is not None and len(qemb):
            for i, r in enumerate(beam_mod._wm_vec_search(s, qemb[0], k=k), start=1):
                out.setdefault(r["id"], {})["vec_score"] = float(r.get("sim", 0.0))
    except Exception:
        pass
    return out

def fusion_reorder(pool, alpha=ALPHA):
    """쿼리별 min-max 정규화 후 fusion 점수로 재정렬."""
    fts_vals = [c["_fts_score"] for c in pool if c.get("_fts_score") is not None]
    vec_vals = [c["_vec_score"] for c in pool if c.get("_vec_score") is not None]
    def norm(v, vals):
        if v is None or not vals:
            return 0.0
        lo, hi = min(vals), max(vals)
        return (v - lo) / (hi - lo) if hi > lo else 0.5
    def fscore(c):
        nf = norm(c.get("_fts_score"), fts_vals)
        nv = norm(c.get("_vec_score"), vec_vals)
        # imp/graph: RRF 기여 보조 (lane rank)
        aux = 0.0
        lr = c.get("_lane_ranks") or {}
        for lane in ("imp_rank", "graph_rank"):
            r = lr.get(lane)
            if r is not None:
                aux += 1.0 / (30 + r)
        return alpha * nv + (1 - alpha) * nf + 0.05 * aux
    return sorted(pool, key=fscore, reverse=True)

# ---- JEV 호출 (stage54 post 재사용) ----
CLIENT = _jev_client()
assert CLIENT
_API = getattr(CLIENT, "_jev_api", None) or "https://api.typesafe.ai/v1/systemone"
_rot = getattr(CLIENT, "_jev_rotator", None)
# 시작 키: 키2 우선
if _rot is not None and hasattr(_rot, "_active"):
    try:
        act = _rot._active()
        if len(act) >= 2:
            CLIENT.headers["Authorization"] = f"Bearer {act[1][1]}"
    except Exception:
        pass

_LAST = [0.0]
def throttle():
    while True:
        now = time.time()
        if now - _LAST[0] >= 0.34:
            _LAST[0] = now
            return
        time.sleep(0.05)

def post(state, questions):
    for attempt in range(10):
        throttle()
        try:
            resp = CLIENT.post(_API, json={"state": state, "questions": questions, "model": "jev-latest"}, timeout=25)
            if resp.status_code == 429:
                body = resp.text or ""
                if "daily free allowance" in body or "resets at" in body:
                    try:
                        _rot.exhausted_until[_rot.last_key] = time.monotonic() + 3600
                    except Exception:
                        pass
                if _rot is not None and hasattr(_rot, "on_429"):
                    try:
                        nk = _rot.on_429()
                    except Exception:
                        nk = None
                    if nk:
                        CLIENT.headers["Authorization"] = f"Bearer {nk}"
                time.sleep(2.0)
                continue
            if resp.status_code == 503:
                time.sleep(3.0)
                continue
            return resp
        except Exception:
            time.sleep(2.0)
    return None

def run_choice(q, rows):
    labels = [j1p._excerpt(j1p._query_window((c.get("content") or ""), q, 300), 150) or "n/a" for c in rows[:60]]
    j_labels = labels + [ABSTAIN_CUR]
    state = j1p.build_state(q, rows)
    questions = {"best": {"type": "choice", "instructions": m48.INSTR,
                          "criteria": {f"c{i}": j_labels[i] for i in range(len(j_labels))}}}
    resp = post(state, questions)
    if resp is None:
        return None, None, "noresp"
    if resp.status_code != 200:
        return None, None, f"http{resp.status_code}"
    ans = (resp.json().get("answers") or {}).get("best") or {}
    probs = ans.get("probabilities") or {}
    ap = float(probs.get(f"c{len(j_labels)-1}", 0.0)) if probs else 0.0
    try:
        idx = int(str(ans.get("choice")).lstrip("c"))
    except Exception:
        idx = None
    abstain = (idx is None) or (idx == len(j_labels) - 1) or (ap > 0.3)
    return idx, abstain, None

# ---- 쿼리 셋 ----
def load_op90():
    with open(os.path.join(DATA, "stage54_op90_regress.json"), encoding="utf-8") as fh:
        d = json.load(fh)
    recs = None
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, list) and v and isinstance(v[0], dict) and "gold" in v[0]:
                recs = v
                break
    return [{"q": r.get("query") or r.get("q"), "gold": r.get("gold") or r.get("gold_id"), "src": "op"} for r in recs if (r.get("query") or r.get("q")) and (r.get("gold") or r.get("gold_id"))]

def load_noans():
    # noans-50: stage45 스냅샷 raw에서 grp=noans인 쿼리 (text 포함)
    with open(os.path.join(DATA, "stage45_abstain_label_snapshot.json"), encoding="utf-8") as fh:
        d = json.load(fh)
    for run in d.get("runs", []):
        if run.get("cond") != "current":
            continue
        recs = run.get("records") or []
        out = [{"q": r["query"], "gold": None, "src": "noans"} for r in recs if r.get("grp") == "noans" and r.get("query")]
        if out:
            return out[:50]
    return []

def load_live():
    # live-60: stage48에 하드코딩된 60쿼리
    qs = m48.load_queries(SNAP)
    return [{"q": q, "gold": None, "src": "live"} for q in qs]

def main():
    queries = load_op90() + load_noans() + load_live()
    print(f"쿼리: op={len(load_op90())} noans={len(load_noans())} live={len(load_live())} total={len(queries)}")
    # paired: 쿼리별 두 cond alternate
    results = []
    for qi, item in enumerate(queries):
        q = item["q"]
        gold = item.get("gold")
        pool = build_pool(q)
        if not pool:
            results.append({"q": q, "src": item["src"], "gold": gold, "err": "empty_pool", "cu": None, "fu": None})
            print(f"  [{qi}] empty pool", flush=True)
            continue
        gold_rank_cu = None
        if gold:
            ids = [c["id"] for c in pool]
            gold_rank_cu = ids.index(gold) + 1 if gold in ids else None
        # cond cu: RRF 순서 보존
        idx_cu, abst_cu, err_cu = run_choice(q, pool)
        # cond fu: fusion 재정렬
        fpool = fusion_reorder(pool)
        idx_fu, abst_fu, err_fu = run_choice(q, fpool)
        results.append({
            "q": q, "src": item["src"], "gold": gold,
            "pool_n": len(pool), "gold_rank_cu": gold_rank_cu,
            "cu": {"idx": idx_cu, "abstain": abst_cu, "err": err_cu},
            "fu": {"idx": idx_fu, "abstain": abst_fu, "err": err_fu},
        })
        if (qi + 1) % 20 == 0:
            print(f"  {qi+1}/{len(queries)}", flush=True)

    json.dump(results, open(os.path.join(DATA, "stage101_fusion07_raw.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n저장: stage101_fusion07_raw.json")

if __name__ == "__main__":
    main()