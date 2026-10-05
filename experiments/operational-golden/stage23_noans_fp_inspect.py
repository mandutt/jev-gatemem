import json, os, sys, sqlite3
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden")
os.environ["MNEMOSYNE_EMBEDDING_MODEL"] = "bench/bekko-a8m"

import sqlite_vec
DB = r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
conn.enable_load_extension(True)
sqlite_vec.load(conn)

import mnemosyne.core.beam as beam_mod
from mnemosyne.core import embeddings as emb_mod
from gateway.j1_pipeline import build_lane_pool, _filter_and_rank, _imp_search, _graph_lane_search, POOL_BUDGET

def recall_raw(kind, arg, k):
    if kind == "fts": return beam_mod._fts_search_working(conn, arg, k=k)
    if kind == "vec":
        qemb = emb_mod.embed([arg])
        if qemb is None or not len(qemb): return []
        return beam_mod._wm_vec_search(conn, qemb[0], k=k)
    if kind == "imp": return _imp_search(conn, k=k)
    if kind == "graph": return _graph_lane_search(conn, arg, k=k)
    if kind == "get":
        r = conn.execute("SELECT id, content, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
        if not r:
            r = conn.execute("SELECT id, content, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
        if not r: return None
        return {"id": r[0], "content": r[1], "importance": r[2]}
    return []

def query_window(content, query, limit):
    if not content:
        return content or ""
    q_tokens = [t for t in query.replace("?", "").split() if len(t) >= 2]
    best = 0
    if q_tokens:
        low = content.lower()
        for t in q_tokens:
            p = low.find(t.lower())
            if p != -1:
                best = max(0, p - limit // 3)
                break
    return content[best:best + limit]

DATA = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data"
raw = json.load(open(os.path.join(DATA, "stage22_noans_excerpt300.json"), encoding="utf-8"))
recs = raw["records"]
ok = [r for r in recs if "pool_n" in r]
abs1 = [r for r in ok if r.get("head100_abstain") is True]
fp2 = [r for r in abs1 if r.get("win300_abstain") is False and r.get("win300_err") is None]

print(f"오주입 {len(fp2)}건의 선택 메모리 확인\n", flush=True)
for r in fp2:
    q = r["query"]; idx = r["win300_idx"]
    try:
        pool = build_lane_pool(recall_raw, q)
        filtered = _filter_and_rank(pool, q) if pool else []
        if idx < len(filtered):
            picked = filtered[idx]
            c = (picked.get("content") or "")
            print(f"[{r['qid']}] Q: {q[:60]}")
            print(f"  pick idx={idx}: {c[:120].replace(chr(10),' ')}")
            # pick의 헤드 100 vs 윈도우 300 차이
            print(f"  (head100: {c[:100][:60].replace(chr(10),' ')}...)")
            print(f"  (win300 : {query_window(c, q, 300)[:100].replace(chr(10),' ')}...)")
            print()
        else:
            print(f"[{r['qid']}] idx {idx} >= pool {len(filtered)}\n")
    except Exception as e:
        print(f"[{r['qid']}] ERR {str(e)[:80]}\n")
conn.close()