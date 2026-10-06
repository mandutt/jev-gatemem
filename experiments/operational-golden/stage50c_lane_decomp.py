# -*- coding: utf-8 -*-
"""stage50c: RRF 순위 개선 여지 + lane 분해 실측 (0콜) — '답이 rank 8~9'의 구조 규명
1) 답 후보가 RRF에서 왜 rank 8~9인가 (lane별 기여)
2) lane별 단독 순위 (fts vec imp graph 단독으로 뽑으면 몇 위?)
3) RRF 가중치/점수 변화로 답을 상위로 올릴 여지가 있는가 (0콜 시뮬레이션)
"""
import os, sys, json, re, sqlite3

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

def recall_raw_factory(q):
    def recall_raw(kind, arg, k):
        if kind == "fts": return beam_mod._fts_search_working(s, arg, k=k)
        if kind == "vec":
            qemb = emb_mod.embed([arg])
            if qemb is None or not len(qemb): return []
            return beam_mod._wm_vec_search(s, qemb[0], k=k)
        if kind == "imp": return j1p._imp_search(s, k=k)
        if kind == "graph": return j1p._graph_lane_search(s, arg, k=k)
        if kind == "get":
            r = s.execute("SELECT id, content, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
            if not r:
                r = s.execute("SELECT id, content, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
            return dict(r) if r else None
        return []
    return recall_raw

# lane 단독 검색 헬퍼 (RRF 없이 해당 lane만)
def lane_search(kind, q):
    rr = recall_raw_factory(q)
    if kind == "fts":
        res = beam_mod._fts_search_working(s, q, k=100)
        return [r["id"] for r in res[:100]]
    if kind == "vec":
        qemb = emb_mod.embed([q])
        if qemb is None or not len(qemb): return []
        res = beam_mod._wm_vec_search(s, qemb[0], k=100)
        return [r["id"] for r in res[:100]]
    return []

results = []
for d in d49d:
    idx = d["idx"]; q = qtext[idx]
    kws = kw(q)
    ans = None
    for c in d["cands"]:
        if sum(1 for k in kws if k in c["text"]) >= 2:
            ans = c; break
    if not ans:
        results.append({"idx": idx, "ans_rank": None, "note": "answer candidate not found by keyword"})
        continue
    ans_id = ans["id"]
    # 1) RRF 순위 재현
    pool = j1p.build_lane_pool(recall_raw_factory(q), q)
    pool = j1p._filter_and_rank(pool, q)[:j1p.POOL_BUDGET]
    rrf_rank = next((i + 1 for i, p in enumerate(pool) if (p.get("id") or "")[:16] == ans_id), None)
    # 2) lane 단독 순위
    fts_rank = vec_rank = None
    fts_ids = lane_search("fts", q)
    vec_ids = lane_search("vec", q)
    if ans_id in fts_ids: fts_rank = fts_ids.index(ans_id) + 1
    if ans_id in vec_ids: vec_rank = vec_ids.index(ans_id) + 1
    results.append({"idx": idx, "q": q[:30], "ans_rank_49d": ans["rank"], "rrf_rank": rrf_rank,
                    "fts_rank": fts_rank, "vec_rank": vec_rank})
    print(f"#{idx:02d} ans_rank(49d)={ans['rank']:3} rrf={rrf_rank} fts={fts_rank} vec={vec_rank} | {q[:30]}", flush=True)

json.dump(results, open(os.path.join(DATA, "stage50c_lane_decomp.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\n저장: stage50c_lane_decomp.json ({len(results)}건)")
# 요약: 답이 어느 lane에서도 안 잡히는 건?
no_lane = [r["idx"] for r in results if r.get("fts_rank") is None and r.get("vec_rank") is None]
only_vec = [r["idx"] for r in results if r.get("vec_rank") is not None and r.get("fts_rank") is None]
only_fts = [r["idx"] for r in results if r.get("fts_rank") is not None and r.get("vec_rank") is None]
print(f"\nfts도 vec도 안 잡음: {no_lane}")
print(f"vec만 잡음: {only_vec}")
print(f"fts만 잡음: {only_fts}")