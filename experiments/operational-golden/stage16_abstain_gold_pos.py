import json, os, sys, sqlite3
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
os.environ.setdefault("MNEMOSYNE_EMBEDDING_MODEL", "bench/bekko-a8m")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden")

import sqlite_vec
DB = r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
conn.enable_load_extension(True)
sqlite_vec.load(conn)

import mnemosyne.core.beam as beam_mod
from gateway.j1_pipeline import build_lane_pool, _filter_and_rank, _imp_search, _graph_lane_search

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

DATA = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data"
raw = json.load(open(os.path.join(DATA, "runR_recall_strength_raw.json"), encoding="utf-8"))
base = {r["query"]: r for r in raw["records"] if r.get("alpha") == 0.0}
abs_qs = [base[q] for q in base if base[q].get("choice_abstain")]
print(f"abstain 쿼리 {len(abs_qs)}건 0콜 스캔 시작", flush=True)

out = []
for i, r in enumerate(abs_qs):
    q = r["query"]; gid = r["gold_id"]
    try:
        pool = build_lane_pool(recall_raw, q)
        ranked = _filter_and_rank(pool, q)
        ids = [x.get("id") for x in ranked]
        if gid in ids:
            pos = ids.index(gid) + 1
            out.append({"query": q, "cat": r["cat"], "gold_rank_full": pos,
                        "in40": pos <= 40, "in60": pos <= 60, "in100": pos <= 100, "total": len(ids)})
        else:
            out.append({"query": q, "cat": r["cat"], "gold_rank_full": None,
                        "in40": False, "in60": False, "in100": False, "total": len(ids)})
    except Exception as e:
        out.append({"query": q, "cat": r["cat"], "err": str(e)[:100]})
    if (i + 1) % 9 == 0:
        print(f"  {i+1}/{len(abs_qs)}", flush=True)

with open(os.path.join(DATA, "stage16_abstain_gold_pos.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("저장 완료", flush=True)
for o in out:
    gp = o.get("gold_rank_full")
    print(f"  [{o['cat']:22}] rank={gp} in40={o.get('in40')} in60={o.get('in60')} in100={o.get('in100')} | {o['query'][:45]}")