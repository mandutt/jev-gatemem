"""Phase 3+ importance lane verification — pool/filtered/top5 metrics."""
import json, sys, sqlite3, time
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
from mnemosyne.core.beam import BeamMemory
from mnemosyne.core import beam as beam_mod
from gateway.j1_pipeline import build_lane_pool, _filter_and_rank, POOL_DEFAULT_TOP

SNAP = r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\snapshots\snap-20260927.db"
Q = json.load(open(r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\dataset_curated.json", encoding="utf-8"))
b = BeamMemory(session_id="eval", db_path=SNAP)


def recall_raw(kind, arg, k):
    if kind == "fts":
        return beam_mod._fts_search_working(b.conn, arg, k=k)
    if kind == "vec":
        emb = beam_mod._embeddings.embed([arg])
        if emb is None or not len(emb):
            return []
        return beam_mod._wm_vec_search(b.conn, emb[0], k=k)
    if kind == "imp":
        from gateway.j1_pipeline import _imp_search
        return _imp_search(b.conn, k=k)
    if kind == "get":
        for table in ("working_memory", "episodic_memory"):
            row = b.conn.execute(
                f"SELECT id, content, source, timestamp, session_id,"
                f" importance, metadata_json, veracity, created_at"
                f" FROM {table} WHERE id = ?", (arg,)).fetchone()
            if row:
                return {"id": row[0], "content": row[1], "source": row[2],
                        "timestamp": row[3], "session_id": row[4],
                        "importance": row[5], "metadata": row[6],
                        "veracity": row[7], "created_at": row[8],
                        "memory_store": "working" if table == "working_memory" else "episodic"}
        return None
    return []


t0 = time.perf_counter()
pool_hit = filt_hit = lifted_hit = 0
pool_sizes, filt_sizes = [], []
miss_details = []
for q in Q:
    gold = set(q["gold_ids"])
    pool = build_lane_pool(recall_raw, q["query"])
    pool_sizes.append(len(pool))
    pids = {r["id"] for r in pool}
    inter = pids.intersection(gold)
    if inter:
        pool_hit += 1
    else:
        miss_details.append((q["query"][:40], [g[:12] for g in gold]))
    filt = _filter_and_rank(pool, q["query"])[:POOL_DEFAULT_TOP]
    filt_sizes.append(len(filt))
    fids = {r["id"] for r in filt}
    if fids.intersection(gold):
        filt_hit += 1
    if any(r["id"] in gold for r in filt[:5]):
        lifted_hit += 1
n = len(Q)
dt = time.perf_counter() - t0
print(f"n={n}  elapsed={dt:.1f}s")
print(f"pool inclusion:     {pool_hit}/{n} = {pool_hit/n:.2%}   (size avg {sum(pool_sizes)/n:.0f})")
print(f"filtered inclusion: {filt_hit}/{n} = {filt_hit/n:.2%}   (size avg {sum(filt_sizes)/n:.0f})")
print(f"top-5 contains gold:{lifted_hit}/{n} = {lifted_hit/n:.2%}")
if miss_details:
    print("still missing:")
    for qq, gg in miss_details:
        print(f"  {qq!r} -> {gg}")