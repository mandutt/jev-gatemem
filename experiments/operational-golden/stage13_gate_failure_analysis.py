"""Stage-13: analyze the 7 gate-failure cases (pool 15/19 -> gate 8/19).

For each gold 19: pool hit? gate hit? If pool-hit but gate-miss: WHY does
_filter_and_rank drop it? Possible causes:
  a) [USER]/[ASSISTANT] prefix exclusion (should be lifted now — verify)
  b) min_distinctive (overlap < 2)
  c) min_coverage (overlap/query_tokens < 0.30)
  d) quality multiplier drops it below top-40 (gate passes but rank cut)
Measure for each: pool_rank of gold row, overlap, coverage, whether it passed
the lexical checks, and its _adjusted rank vs top-40 cut.

0 JEV calls, live DB read-only.
"""
import os, re, sqlite3, json, sys
import numpy as np
sys.path.insert(0, r"C:/Users/mandu/hermes-made/jev-memory-middleware")
os.environ.setdefault("MNEMOSYNE_EMBEDDING_MODEL", "bench/bekko-a8m")

import sqlite_vec
DB = r"C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
conn.enable_load_extension(True)
sqlite_vec.load(conn)

import mnemosyne.core.beam as beam_mod
from gateway.j1_pipeline import build_lane_pool, _filter_and_rank, _imp_search, _graph_lane_search, _tokenize, _STOPWORDS, _PREFETCH_EXCLUDED_PREFIXES

print("exclusion prefixes now:", _PREFETCH_EXCLUDED_PREFIXES)

def body(c):
    m = re.match(r"^(\[[^\]]*\]\s*)?", c)
    return c[m.end():]

gold = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "data", "stage2_final_gold.json"), encoding="utf-8"))

def recall_raw(kind, arg, k):
    if kind == "fts": return beam_mod._fts_search_working(conn, arg, k=k)
    if kind == "vec":
        qemb = beam_mod._embeddings.embed([arg])
        if qemb is None or not len(qemb): return []
        return beam_mod._wm_vec_search(conn, qemb[0], k=k)
    if kind == "imp": return _imp_search(conn, k=k)
    if kind == "graph": return _graph_lane_search(conn, arg, k=k)
    if kind == "get":
        r = conn.execute("SELECT id, content, source, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
        if not r:
            r = conn.execute("SELECT id, content, source, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
        if not r: return None
        return {"id": r[0], "content": r[1], "source": r[2], "importance": r[3]}
    return []

print(f"\n=== gold 19 gate-failure analysis ===")
for g in gold:
    q = g["query"]
    target = g["row_id"]
    pool = build_lane_pool(recall_raw, q)
    pids = [r["id"] for r in pool]
    pool_rank = (pids.index(target) + 1) if target in pids else None
    f_all = _filter_and_rank(pool, q)
    fids = [r.get("id") for r in f_all]
    gate_rank_all = (fids.index(target) + 1) if target in fids else None
    gate40 = gate_rank_all is not None and gate_rank_all <= 40
    # lexical checks
    row = next((r for r in pool if r["id"] == target), None)
    reason = []
    if row is None:
        reason.append("not-in-pool")
    else:
        content = row.get("content") or ""
        qt = _tokenize(q) - _STOPWORDS
        ct = _tokenize(content)
        ov = qt & ct
        cov = len(ov) / len(qt) if qt else 0
        lane = row.get("_lane_ranks") or {}
        vr = lane.get("vec_rank")
        exempt = vr is not None and vr <= 2 and len(ov) >= 1
        if len(ov) < 2 and not exempt: reason.append(f"distinctive<2 (ov={len(ov)}, vr={vr})")
        if cov < 0.30 and not exempt: reason.append(f"coverage<0.30 (cov={cov:.2f}, vr={vr})")
        if content.upper().startswith(_PREFETCH_EXCLUDED_PREFIXES): reason.append("excluded-prefix")
    status = "OK" if gate40 else ("GATE-MISS" if pool_rank else "POOL-MISS")
    print(f"  [{status}] {target[:14]} pool_rank={pool_rank} gate_rank={gate_rank_all} {'; '.join(reason) if reason else ''}")
    if pool_rank and not gate40:
        # also show what _adjusted rank would be
        pass

print("\nDONE")
conn.close()