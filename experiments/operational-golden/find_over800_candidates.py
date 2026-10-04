"""② 800자 초과 샘플 평가 — pool 내 800자 초과 후보 탐색 (2026-10-04)

목적: head-only 800자 캡의 실손실 검증.
방법: exp8a 쿼리(op 90 + noans 50)로 pool 재현 → 800자 초과 후보를 포함한
      (query, candidate) 쌍 수집 → 게이트 head-800 vs full-text 비교 실험 대상 준비.
"""
import json
import os
import sys
import sqlite3

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
DATA = os.path.join(ROOT, "experiments/operational-golden/data")
LIVE_DB = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes/mnemosyne/data/mnemosyne.db")
os.environ.setdefault("MNEMOSYNE_DB", LIVE_DB)

import gateway.j1_pipeline as j1p
import mnemosyne.core.beam as bm
from mnemosyne.core import embeddings as emb_mod

b = bm.BeamMemory(session_id="cap_eval")

def recall_raw(kind, arg, k_):
    if kind == "fts":
        return bm._fts_search_working(b.conn, arg, k=k_)
    if kind == "vec":
        e = emb_mod.embed([arg])
        if e is None or not len(e):
            return []
        return bm._wm_vec_search(b.conn, e[0], k=k_)
    if kind == "imp":
        return j1p._imp_search(b.conn, k=k_)
    if kind == "graph":
        return j1p._graph_lane_search(b.conn, arg, k=k_)
    if kind == "get":
        from core import j1_engine
        row = j1_engine.hydration_get(b, arg)
        return row if isinstance(row, dict) else None
    return []

def stage1_pool(query, exclude_ids=None, k=40):
    pool = j1p.build_lane_pool(recall_raw, query)
    if exclude_ids:
        pool = [p for p in pool if p.get("id") not in exclude_ids]
    ranked = j1p._filter_and_rank(pool, query) if pool else []
    return ranked[:k]

# 자격: 라이브 DB id
conn = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True)
by_id = set()
for tbl in ["working_memory", "episodic_memory"]:
    for r in conn.execute(f"SELECT id FROM {tbl}"):
        by_id.add(r[0])
conn.close()

# 쿼리 수집: op 90 + noans 50
queries = []
op_all = json.load(open(os.path.join(DATA, "golden_eval_v2.json"), encoding="utf-8"))
for x in op_all:
    if x.get("gold_id") and x.get("cat") != "NO_ANSWER":
        queries.append(("op", x["gold_id"], x["query"]))
noans = json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))
for x in noans:
    queries.append(("noans", x.get("qid"), x["query"]))
print(f"쿼리 {len(queries)}건")

# pool 재현 → 800자 초과 후보 수집
over800_pairs = []
found_queries = set()
for grp, qid, q in queries:
    try:
        pool = stage1_pool(q, k=40)
    except Exception as e:
        print(f"  pool 실패 {qid}: {e}")
        continue
    pool = [p for p in pool if p.get("id") in by_id]
    for c in pool[:40]:
        content = c.get("content") or ""
        if len(content) > 800:
            over800_pairs.append({
                "grp": grp, "qid": qid, "query": q,
                "cand_id": c.get("id"), "cand_len": len(content),
                "content": content,
            })
            found_queries.add(qid)
    print(f"  {qid}: pool {len(pool)}건", end="\r")

print(f"\n800자 초과 후보 포함 (query,cand) 쌍: {len(over800_pairs)}건 (쿼리 {len(found_queries)}개)")

# 길이 분포
lens = sorted(p["cand_len"] for p in over800_pairs)
if lens:
    import statistics
    print(f"길이: min {lens[0]} | p50 {lens[len(lens)//2]} | p90 {lens[9*len(lens)//10]} | max {lens[-1]}")

# 저장 (콜 없이 재현만)
with open(os.path.join(DATA, "exp8b_over800_pairs.json"), "w", encoding="utf-8") as f:
    json.dump(over800_pairs, f, ensure_ascii=False, indent=1)
print(f"저장: {DATA}/exp8b_over800_pairs.json")