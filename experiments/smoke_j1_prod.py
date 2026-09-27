"""Smoke: J1 pipeline vs curated eval on the snapshot DB (no Jev calls)."""
import sys, json, time
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
from mnemosyne.core.beam import BeamMemory
from mnemosyne.core import beam as beam_mod
from gateway.j1_pipeline import build_lane_pool, _filter_and_rank, POOL_DEFAULT_TOP

SNAP = r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\snapshots\snap-20260927.db"
QUERIES = r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\dataset_curated.json"
Q = json.load(open(QUERIES, encoding="utf-8"))

b = BeamMemory(session_id="eval", db_path=SNAP)

def recall_raw(kind, arg, k):
    if kind == "fts":
        return beam_mod._fts_search_working(b.conn, arg, k=k)
    if kind == "vec":
        emb = beam_mod._embeddings.embed([arg])
        if emb is None or not len(emb):
            return []
        return beam_mod._wm_vec_search(b.conn, emb[0], k=k)
    if kind == "get":
        row = b.get(arg)
        return row if isinstance(row, dict) else None
    return []

t0 = time.perf_counter()
pool_hit = filt_hit = lifted_hit = 0
pool_sizes, filt_sizes = [], []
for q in Q:
    gold = set(q["gold_ids"])
    pool = build_lane_pool(recall_raw, q["query"])
    pool_sizes.append(len(pool))
    pids = {r["id"] for r in pool}
    if pids & gold:
        pool_hit += 1
    filt = _filter_and_rank(pool, q["query"])[:POOL_DEFAULT_TOP]
    filt_sizes.append(len(filt))
    fids = {r["id"] for r in filt}
    if fids & gold:
        filt_hit += 1
    if any(r["id"] in gold for r in filt[:5]):
        lifted_hit += 1
n = len(Q)
dt = time.perf_counter() - t0
print(f"n={n}  elapsed={dt:.1f}s")
print(f"pool inclusion (gold in lane pool):     {pool_hit}/{n} = {pool_hit/n:.2%}   (size avg {sum(pool_sizes)/n:.0f})")
print(f"filtered inclusion (gold in top-40):    {filt_hit}/{n} = {filt_hit/n:.2%}   (size avg {sum(filt_sizes)/n:.0f})")
print(f"top-5 of filtered order contains gold:  {lifted_hit}/{n} = {lifted_hit/n:.2%}")