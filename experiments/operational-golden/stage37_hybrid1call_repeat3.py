"""stage37: 1콜 hybrid(pool30) 3회 반복 재검증 (2026-10-06) — 비결정성 분리

stage32(1콜 hybrid)가 단일 실행이었으므로 3회 반복으로 재현성 확인.
- pool 30으로 제한 + jev_rerank의 hybrid 경로(choice+noul 30) 사용
- 게이트: abstain_p>0.3(soft) + noul_top<0.3(noul)
- op 90 + noans 50 = 140콜 × 3회 = 420콜

채점:
  - run별: hit@1/3/5, abstain, noans FP
  - 3-Run Majority Vote (B AI 프로토콜)
비교 기준 (stage32 단일): hit@3 77/76, noans FP 16/12
"""
import sys, os, time, json, sqlite3, sqlite_vec
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware")

os.environ["JEV_TWO_CALL"] = "0"   # 1콜 hybrid 경로

from gateway import j1_pipeline as j1p
from jev_mem_core.pipeline import _jev_client

RUNS = int(os.environ.get("STAGE37_RUNS", "3"))
DATA = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data"
POOL_CAP = 30  # API 한도 (noul 30 + choice 1 = 31)

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
raw = json.load(open(os.path.join(DATA, "runR_recall_strength_raw.json"), encoding="utf-8"))
base = {r["query"]: r for r in raw["records"] if r.get("alpha") == 0.0}
op_qs = list(base.keys())
noans_qs = [n["query"] for n in json.load(open(os.path.join(DATA, "golden_noanswer_hard_queries.json"), encoding="utf-8"))]
queries = op_qs + noans_qs
print(f"RUNS={RUNS}, pool_cap={POOL_CAP}, 쿼리 {len(queries)}", flush=True)

all_runs = []
for run in range(1, RUNS + 1):
    print(f"\n=== RUN {run}/{RUNS} 시작 ===", flush=True)
    results = []
    for i, q in enumerate(queries, 1):
        gid = base.get(q, {}).get("gold_id")
        rec = {"query": q, "gold_id": gid, "grp": "op" if gid else "noans"}
        t0 = time.perf_counter()
        try:
            pool = j1p.build_lane_pool(recall_raw, q)
            filtered = j1p._filter_and_rank(pool, q) if pool else []
            rows = filtered[:POOL_CAP]
            rec["pool_n"] = len(rows)
            ranked, abstained = j1p.jev_rerank(query=q, pool=rows, client=client,
                                               call_jev=True, timeout=10.0)
            rec["abstained"] = abstained
            rec["lat_ms"] = int((time.perf_counter() - t0) * 1000)
            if ranked and not abstained:
                ids = [c.get("id") for c in ranked]
                rec["pick_id"] = ids[0]
                rec["gold_rank"] = (ids.index(gid) + 1) if gid in ids else None
            else:
                rec["gold_rank"] = None
        except Exception as e:
            rec["err"] = f"{type(e).__name__}: {e}"
        results.append(rec)
        if i % 30 == 0:
            print(f"  {i}/{len(queries)}", flush=True)
    fn = os.path.join(DATA, f"stage37_run{run}.json")
    json.dump({"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "run": run,
               "cond": "hybrid1call-repeat", "records": results},
              open(fn, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    all_runs.append(results)
    print(f"RUN {run} 저장: {fn}", flush=True)

conn.close()

print("\n=== 종합 (run별) ===")
run_stats = []
for run, results in enumerate(all_runs, 1):
    op = [r for r in results if r["grp"] == "op"]
    na = [r for r in results if r["grp"] == "noans"]
    def hitk(r, k):
        gr = r.get("gold_rank")
        return gr is not None and gr <= k
    h1 = sum(1 for r in op if hitk(r, 1)); h3 = sum(1 for r in op if hitk(r, 3))
    h5 = sum(1 for r in op if hitk(r, 5)); ab = sum(1 for r in op if r.get("abstained"))
    fp = sum(1 for r in na if not r.get("abstained") and not r.get("err"))
    err = sum(1 for r in results if r.get("err"))
    run_stats.append({"h1": h1, "h3": h3, "h5": h5, "abstain": ab, "fp": fp, "err": err})
    print(f"  RUN{run}: hit@1={h1} hit@3={h3} hit@5={h5} abstain={ab} noansFP={fp} err={err}")

op_all = [[r for r in results if r["grp"] == "op"] for results in all_runs]
na_all = [[r for r in results if r["grp"] == "noans"] for results in all_runs]
mv_h3 = mv_h1 = 0
for qi, q in enumerate(op_qs):
    hits3 = sum(1 for rs in op_all if (rs[qi].get("gold_rank") is not None and rs[qi]["gold_rank"] <= 3))
    hits1 = sum(1 for rs in op_all if (rs[qi].get("gold_rank") is not None and rs[qi]["gold_rank"] <= 1))
    if hits3 >= 2: mv_h3 += 1
    if hits1 >= 2: mv_h1 += 1
print(f"\nmajority hit@1={mv_h1}/90 ({mv_h1/90*100:.1f}%)")
print(f"majority hit@3={mv_h3}/90 ({mv_h3/90*100:.1f}%)")
mv_fp = 0
for qi in range(len(noans_qs)):
    abs_cnt = sum(1 for rs in na_all if rs[qi].get("abstained"))
    if abs_cnt < 2:
        mv_fp += 1
print(f"majority FP={mv_fp}/50 ({mv_fp/50*100:.1f}%)")

print("\n=== 비교 ===")
print(f"  현행 pool60 win-300:        hit@3 77, noansFP 16")
print(f"  stage32 1콜 hybrid(단일):   hit@3 77/76, noansFP 16/12")
print(f"  stage36 2콜 majority:       hit@3 75, noansFP 18 (기각)")
print(f"  1콜 hybrid majority:        hit@3 {mv_h3}, noansFP {mv_fp}")