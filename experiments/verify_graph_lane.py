"""Phase 3+ graph/fact lane verification — metrics + graph lane contribution."""
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
    if kind == "graph":
        from gateway.j1_pipeline import _graph_lane_search
        return _graph_lane_search(b.conn, arg, k=k)
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


# 1) graph lane 단독 기여 측정: graph lane만으로 gold를 회수하는 쿼리
from gateway.j1_pipeline import _graph_lane_search as _gls
print("=== graph lane 단독 기여 ===")
graph_only_gold = 0
for q in Q:
    gold = set(q["gold_ids"])
    # FTS/vec/imp 없이 graph 만으로 gold 회수?
    g = _gls(b.conn, q["query"], k=10)
    gids = {r["id"] for r in g}
    if gids.intersection(gold):
        graph_only_gold += 1
print(f"graph lane 단독 gold 회수 쿼리: {graph_only_gold}/{len(Q)}")

# 2) 전체 지표 (4-lane)
print("\n=== 4-lane 전체 지표 ===")
t0 = time.perf_counter()
pool_hit = filt_hit = lifted_hit = 0
pool_sizes, filt_sizes = [], []
miss = []
for q in Q:
    gold = set(q["gold_ids"])
    pool = build_lane_pool(recall_raw, q["query"])
    pool_sizes.append(len(pool))
    pids = {r["id"] for r in pool}
    if pids.intersection(gold):
        pool_hit += 1
    else:
        miss.append(q["query"][:40])
    filt = _filter_and_rank(pool, q["query"])[:POOL_DEFAULT_TOP]
    filt_sizes.append(len(filt))
    fids = {r["id"] for r in filt}
    if fids.intersection(gold):
        filt_hit += 1
    if any(r["id"] in gold for r in filt[:5]):
        lifted_hit += 1
n = len(Q)
dt = time.perf_counter() - t0
print(f"n={n} elapsed={dt:.1f}s")
print(f"pool inclusion:     {pool_hit}/{n} = {pool_hit/n:.2%}   (size avg {sum(pool_sizes)/n:.0f})")
print(f"filtered inclusion: {filt_hit}/{n} = {filt_hit/n:.2%}   (size avg {sum(filt_sizes)/n:.0f})")
print(f"top-5 contains gold:{lifted_hit}/{n} = {lifted_hit/n:.2%}")
if miss:
    print("still missing:", miss)

# 3) graph lane이 기존 pool에 추가하는 관련 메모리 (gold 외)
print("\n=== graph lane이 추가하는 관련 메모리 샘플 ===")
shown = 0
for q in Q[:8]:
    g = _gls(b.conn, q["query"], k=10)
    if not g:
        continue
    gold = set(q["gold_ids"])
    extra = [r["id"] for r in g if r["id"] not in gold]
    if extra and shown < 4:
        print(f"query: {q['query'][:40]!r}")
        for mid in extra[:3]:
            row = b.conn.execute("SELECT content FROM working_memory WHERE id=?", (mid,)).fetchone()
            if row:
                print(f"   + {mid[:16]}: {(row[0] or '')[:60]!r}")
        shown += 1