# -*- coding: utf-8 -*-
"""stage50d-2: RRF 상위 후보 lane 조합 vs 답 — 이유 규명 + 가중치 시뮬레이션 (0콜)"""
import os, sys, json, re, sqlite3, itertools, math

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "operational-golden"))
os.chdir(REPO)
import stage48_live60_cross as m48
import gateway.j1_pipeline as j1p
from mnemosyne.core import beam as beam_mod
from mnemosyne.core import embeddings as emb_mod

SNAP = m48.SNAP
DATA = os.path.join(REPO, "experiments", "operational-golden", "data")
s = sqlite3.connect(SNAP); s.row_factory = sqlite3.Row

d49d = json.load(open(os.path.join(DATA, "stage49d_poolinscan_input.json"), encoding="utf-8"))
d49c = json.load(open(os.path.join(DATA, "stage49c_label_booster_input.json"), encoding="utf-8"))
qtext = {d["idx"]: d["query"] for d in d49c}

def kw(q): return [w for w in re.sub(r"[?？]", "", q).split() if len(w) >= 2][:5]

def _recall_raw_factory(q):
    def recall_raw(kind, arg, kk):
        if kind == "fts": return beam_mod._fts_search_working(s, arg, k=kk)
        if kind == "vec":
            qemb = emb_mod.embed([arg])
            if qemb is None or not len(qemb): return []
            return beam_mod._wm_vec_search(s, qemb[0], k=kk)
        if kind == "imp": return j1p._imp_search(s, k=kk)
        if kind == "graph": return j1p._graph_lane_search(s, arg, k=kk)
        if kind == "get":
            r = s.execute("SELECT id, content, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
            if not r:
                r = s.execute("SELECT id, content, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
            return dict(r) if r else None
        return []
    return recall_raw

def lane_ranks_for(q, pid):
    out = {}
    res = beam_mod._fts_search_working(s, q, k=200)
    ids = [r["id"] for r in res]
    out["fts"] = ids.index(pid) + 1 if pid in ids else None
    qemb = emb_mod.embed([q])
    if qemb is not None and len(qemb):
        res = beam_mod._wm_vec_search(s, qemb[0], k=200)
        ids = [r["id"] for r in res]
        out["vec"] = ids.index(pid) + 1 if pid in ids else None
    else:
        out["vec"] = None
    res = j1p._imp_search(s, k=200)
    ids = [r["id"] for r in res]
    out["imp"] = ids.index(pid) + 1 if pid in ids else None
    res = j1p._graph_lane_search(s, q, k=200)
    ids = [r["id"] for r in res]
    out["graph"] = ids.index(pid) + 1 if pid in ids else None
    return out

K = 60
def rrf_score(lr, weights):
    score = 0.0
    for lane in ("fts", "vec", "imp", "graph"):
        r = lr.get(lane)
        if r:
            score += weights[lane] / (K + r)
    return score

out = []
for d in d49d:
    idx = d["idx"]; q = qtext[idx]
    kws = kw(q)
    ans = next((c for c in d["cands"] if sum(1 for k in kws if k in c["text"]) >= 2), None)
    if not ans: continue
    ans_lr = lane_ranks_for(q, ans["id"])
    # 현행 가중치 (equal) 기준 답 점수와 상위8 후보 점수
    eq = {"fts": 1.0, "vec": 1.0, "imp": 1.0, "graph": 1.0}
    ans_sc = rrf_score(ans_lr, eq)
    # pool 전체의 lane rank를 매번 재계산하지 않고, lane_ranks_for를 상위후보들에만
    pool = j1p.build_lane_pool(_recall_raw_factory(q), q)
    pool = j1p._filter_and_rank(pool, q)[:8]
    tops = []
    for p in pool:
        pid = (p.get("id") or "")[:16]
        lr = lane_ranks_for(q, pid)
        tops.append((pid, lr, rrf_score(lr, eq)))
    # 답 순위 (등가중)
    ranked = sorted(tops, key=lambda x: -x[2])
    ans_rank_eq = next((i+1 for i, (pid, lr, sc) in enumerate(ranked) if pid == ans["id"]), None)
    out.append({"idx": idx, "ans_fts": ans_lr["fts"], "ans_vec": ans_lr["vec"],
                "ans_score": round(ans_sc, 6), "ans_rank_eq": ans_rank_eq,
                "top_scores": [round(sc, 6) for _, _, sc in ranked]})
    print(f"#{idx:02d} ans(lane {ans_lr['fts']},{ans_lr['vec']}) score={ans_sc:.6f} eq_rank~{ans_rank_eq}", flush=True)

json.dump(out, open(os.path.join(DATA, "stage50d_rrf_top8.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\n저장: stage50d_rrf_top8.json ({len(out)}건)")