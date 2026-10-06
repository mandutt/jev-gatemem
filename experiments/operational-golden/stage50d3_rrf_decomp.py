# -*- coding: utf-8 -*-
"""stage50d-3: RRF 정밀 시뮬레이션 — 답이 8~9위로 밀리는 정확한 원인 + 가중치 개선 여지

실제 코드(_rrf_merge)를 재현:
  rrf = sum_lane 1/(RRF_K=30 + lane_rank)
  lane_rank는 lane의 예산 내 순위 (fts/vec 60, imp 8, graph 10)
목표: 18건에서 답 후보의 rrf 순위가 8~9인 이유를 lane rank 조합으로 분해하고,
      가중치/예산 변화 시뮬레이션으로 개선 여지 확인 (0콜).
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

RRF_K = 30
BUDGET = {"fts": 60, "vec": 60, "imp": 8, "graph": 10}

def kw(q): return [w for w in re.sub(r"[?？]", "", q).split() if len(w) >= 2][:5]

def build_ranks(q):
    """실제 lane 예산으로 ranks map 구성 (id → {lane: rank})"""
    ranks = {}
    def add(kind, res):
        for i, r in enumerate(res, 1):
            ranks.setdefault(r["id"], {})[f"{kind}_rank"] = i
    try:
        add("fts", beam_mod._fts_search_working(s, q, k=BUDGET["fts"]))
    except Exception: pass
    qemb = emb_mod.embed([q])
    if qemb is not None and len(qemb):
        try:
            add("vec", beam_mod._wm_vec_search(s, qemb[0], k=BUDGET["vec"]))
        except Exception: pass
    try:
        add("imp", j1p._imp_search(s, k=BUDGET["imp"]))
    except Exception: pass
    try:
        add("graph", j1p._graph_lane_search(s, q, k=BUDGET["graph"]))
    except Exception: pass
    return ranks

def rrf_score(lr, k=RRF_K):
    return sum(1.0 / (k + r) for r in lr.values())

def run_policy(ranks, weights):
    """가중치 적용 RRF — lane별 가중치 곱. ranks: id→{lane_rank}"""
    scored = []
    for mid, lr in ranks.items():
        sc = 0.0
        for lane_name, w in weights.items():
            r = lr.get(f"{lane_name}_rank")
            if r:
                sc += w / (RRF_K + r)
        scored.append((mid, sc))
    scored.sort(key=lambda x: -x[1])
    return scored

LANES = ("fts", "vec", "imp", "graph")
out = []
for d in d49d:
    idx = d["idx"]; q = qtext[idx]
    kws = kw(q)
    ans = next((c for c in d["cands"] if sum(1 for k in kws if k in c["text"]) >= 2), None)
    if not ans: continue
    ans_id = ans["id"]
    ranks = build_ranks(q)
    # 현재 정책 (동일 가중치) 순위
    cur = run_policy(ranks, {l: 1.0 for l in LANES})
    cur_ans_rank = next((i+1 for i, (mid, sc) in enumerate(cur) if mid == ans_id), None)
    ans_lr = ranks.get(ans_id, {})
    # 상위 8 후보의 lane rank (왜 답보다 높은지)
    top8 = []
    for mid, sc in cur[:8]:
        top8.append({"id": mid[:12], "lr": {k2.split("_")[0]: v for k2, v in ranks.get(mid, {}).items()},
                     "score": round(sc, 6)})
    out.append({"idx": idx, "ans_id": ans_id, "ans_lr": {k.split("_")[0]: v for k, v in ans_lr.items()},
                "cur_ans_rank": cur_ans_rank, "top8": top8})
    print(f"#{idx:02d} ans_rank={cur_ans_rank} ans_lr={ {k.split('_')[0]: v for k, v in ans_lr.items()} }", flush=True)

json.dump(out, open(os.path.join(DATA, "stage50d3_decomp.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\n저장: stage50d3_decomp.json ({len(out)}건)")