"""stage35: 2콜 구조 op90+noans50 전체 회귀 (2026-10-06) — 운영 코드 그대로

j1p.jev_rerank (TWO_CALL=True 기본)를 실제 데몬 venv + 실제 API로 op 90 + noans 50 실행.
- op: gold가 top-3에 오는지 (최종 hit@3)
- noans: abstain(빈 컨텍스트) 되는지 (FP)
- 비교: stage32(1콜 hybrid pool30): hit@3 77/90, noans FP 16
- 기대: hit@3 ~79, noans FP ~12 (stage33 실측)
"""
import sys, os, time, json, sqlite3, sqlite_vec
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware")

from gateway import j1_pipeline as j1p
from jev_mem_core.pipeline import _jev_client

conn = sqlite3.connect(r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db")
conn.row_factory = sqlite3.Row
conn.enable_load_extension(True)
sqlite_vec.load(conn)
from mnemosyne.core import beam as beam_mod
from mnemosyne.core import embeddings as emb_mod

def recall_raw(kind, arg, k):
    if kind == "fts": return beam_mod._fts_search_working(conn, arg, k=k)
    if kind == "vec":
        qemb = emb_mod.embed([arg])
        if qemb is None or not len(qemb): return []
        return beam_mod._wm_vec_search(conn, qemb[0], k=k)
    if kind == "imp": return j1p._imp_search(conn, k=k)
    if kind == "graph": return j1p._graph_lane_search(conn, arg, k=k)
    if kind == "get":
        r = conn.execute("SELECT id, content, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
        if not r:
            r = conn.execute("SELECT id, content, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
        if not r: return None
        return {"id": r[0], "content": r[1], "importance": r[2]}
    return []

client = _jev_client()
print("client:", "OK" if client else "NONE", flush=True)

DATA = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data"
raw = json.load(open(os.path.join(DATA, "runR_recall_strength_raw.json"), encoding="utf-8"))
base = {r["query"]: r for r in raw["records"] if r.get("alpha") == 0.0}
op_qs = list(base.keys())
noans_qs = [n["query"] for n in json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))]
print(f"op {len(op_qs)} + noans {len(noans_qs)} = {len(op_qs)+len(noans_qs)}콜", flush=True)

results = []
done = 0
for q in op_qs + noans_qs:
    gid = base.get(q, {}).get("gold_id")
    rec = {"query": q, "gold_id": gid, "grp": "op" if gid else "noans"}
    t0 = time.perf_counter()
    try:
        pool = j1p.build_lane_pool(recall_raw, q)
        filtered = j1p._filter_and_rank(pool, q) if pool else []
        rows = filtered[:j1p.POOL_BUDGET]
        rec["pool_n"] = len(rows)
        ranked, abstained = j1p.jev_rerank(query=q, pool=rows, client=client,
                                           call_jev=True, timeout=10.0)
        rec["abstained"] = abstained
        rec["lat_ms"] = int((time.perf_counter() - t0) * 1000)
        if ranked and not abstained:
            ids = [c.get("id") for c in ranked]
            rec["pick_id"] = ids[0]
            if gid:
                rec["gold_rank"] = (ids.index(gid) + 1) if gid in ids else None
            else:
                rec["gold_rank"] = None
        elif abstained:
            rec["gold_rank"] = None if gid else None
        else:
            rec["gold_rank"] = None
    except Exception as e:
        rec["err"] = f"{type(e).__name__}: {e}"
    results.append(rec)
    done += 1
    if done % 30 == 0:
        print(f"  {done}/{len(op_qs)+len(noans_qs)}", flush=True)

json.dump({"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "cond": "2call-op90-noans50", "records": results},
          open(os.path.join(DATA, "stage35_2call_full_regression.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

op_recs = [r for r in results if r["grp"] == "op"]
noans_recs = [r for r in results if r["grp"] == "noans"]
def hitk(r, k):
    gr = r.get("gold_rank")
    return gr is not None and gr <= k
h1 = sum(1 for r in op_recs if hitk(r, 1))
h3 = sum(1 for r in op_recs if hitk(r, 3))
h5 = sum(1 for r in op_recs if hitk(r, 5))
abs_n = sum(1 for r in op_recs if r.get("abstained"))
fp = sum(1 for r in noans_recs if not r.get("abstained") and not r.get("err"))
errs = sum(1 for r in results if r.get("err"))
print(f"\n[op 2콜] hit@1={h1} hit@3={h3} hit@5={h5} abstain={abs_n} err={sum(1 for r in op_recs if r.get('err'))}")
print(f"[noans 2콜] FP={fp} abstain={sum(1 for r in noans_recs if r.get('abstained'))} err={sum(1 for r in noans_recs if r.get('err'))}")
print(f"총 err={errs}")
lat = [r.get("lat_ms", 0) for r in results if r.get("lat_ms")]
if lat:
    print(f"latency: median={sorted(lat)[len(lat)//2]}ms mean={sum(lat)//len(lat)}ms max={max(lat)}ms")
conn.close()