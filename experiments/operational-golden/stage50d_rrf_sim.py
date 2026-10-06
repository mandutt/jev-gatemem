# -*- coding: utf-8 -*-
"""stage50d: RRF 병합 시뮬레이션 — 답이 rank 8~9로 밀리는 원인 + 가중치 개선 여지 (0콜)

1) 현재 RRF 점수 구성 분해: 답 후보가 각 lane에서 받는 rank → RRF 점수, 
   상위 7 후보가 어느 lane에서 오는가 (왜 답보다 높은가)
2) 가중치 시뮬레이션: lane 가중치 벡터를 바꿔 답 후보가 rank 1~3으로 올라오는지
   (RRF = sum w_l / (k + rank_l) 형태 재현)
"""
import os, sys, json, re, sqlite3, itertools

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

def kw(q):
    return [w for w in re.sub(r"[?？]", "", q).split() if len(w) >= 2][:5]

def lane_ranks(q, ans_id):
    """4개 lane 각각에서 ans_id의 rank를 뽑음 (없으면 None)"""
    out = {}
    # fts
    res = beam_mod._fts_search_working(s, q, k=200)
    ids = [r["id"] for r in res]
    out["fts"] = ids.index(ans_id) + 1 if ans_id in ids else None
    # vec
    qemb = emb_mod.embed([q])
    if qemb is not None and len(qemb):
        res = beam_mod._wm_vec_search(s, qemb[0], k=200)
        ids = [r["id"] for r in res]
        out["vec"] = ids.index(ans_id) + 1 if ans_id in ids else None
    else:
        out["vec"] = None
    # imp (importance lane — 상위 중요도 N)
    res = j1p._imp_search(s, k=200)
    ids = [r["id"] for r in res]
    out["imp"] = ids.index(ans_id) + 1 if ans_id in ids else None
    # graph
    res = j1p._graph_lane_search(s, q, k=200)
    ids = [r["id"] for r in res]
    out["graph"] = ids.index(ans_id) + 1 if ans_id in ids else None
    return out

def top_pool_ranks(q, k=60):
    """전체 pool (RRF 합산 전)의 후보별 lane rank 조합 — 상위 k의 구성을 보기 위함"""
    pool = j1p.build_lane_pool(_recall_raw_factory(q), q)
    pool = j1p._filter_and_rank(pool, q)[:k]
    return pool

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

# ---- 실측 1: 답 후보의 lane rank 4종 ----
print("=== 답 후보 lane rank (현행 RRF 60) ===")
rows = []
for d in d49d:
    idx = d["idx"]; q = qtext[idx]
    kws = kw(q)
    ans = next((c for c in d["cands"] if sum(1 for k in kws if k in c["text"]) >= 2), None)
    if not ans: continue
    lr = lane_ranks(q, ans["id"])
    rows.append({"idx": idx, "ans_id": ans["id"], "lane": lr})
    print(f"#{idx:02d} fts={lr['fts']} vec={lr['vec']} imp={lr['imp']} graph={lr['graph']}", flush=True)

json.dump(rows, open(os.path.join(DATA, "stage50d_lane_ranks.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# 요약: 답이 어느 lane 조합에서 오는가
from collections import Counter
comb = Counter()
for r in rows:
    lr = r["lane"]
    key = "".join(sorted([k for k, v in lr.items() if v is not None]))
    comb[key] += 1
print(f"\nlane 조합 분포: {dict(comb)}")
print("fts 단독 1~2위 비율:", sum(1 for r in rows if r['lane']['fts'] in (1, 2)), "/", len(rows))