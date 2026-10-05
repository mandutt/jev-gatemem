import json, os, sys, sqlite3, time
import numpy as np
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden")
os.environ["MNEMOSYNE_EMBEDDING_MODEL"] = "bench/bekko-a8m"

import sqlite_vec
DB = r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
conn.enable_load_extension(True)
sqlite_vec.load(conn)
from mnemosyne.core import embeddings as emb_mod

DATA = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data"
rows = json.load(open(os.path.join(DATA, "stage16_poolout_23_gold_content.json"), encoding="utf-8"))

def get_gold_vec(gid):
    r = conn.execute("SELECT embedding_json FROM memory_embeddings WHERE memory_id=?", (gid,)).fetchone()
    if not r or not r["embedding_json"]:
        return None
    return np.array(json.loads(r["embedding_json"]), dtype=np.float32)

def vec_rank(query, gid, k=400):
    """원래 쿼리로 vec 검색 → gold의 rank (없으면 None). 데몬 venv, 16자 id."""
    qemb = emb_mod.embed([query])[0]
    emb_arr = qemb / np.linalg.norm(qemb)
    emb_json = json.dumps(emb_arr.tolist())
    top = conn.execute("""
        SELECT wm.id, vw.distance FROM vec_working vw
        JOIN working_memory wm ON wm.rowid = vw.rowid
        WHERE wm.superseded_by IS NULL AND (wm.valid_until IS NULL OR wm.valid_until > ?)
          AND vw.embedding MATCH vec_quantize_int8(?, "unit")
          AND k=? ORDER BY vw.distance
    """, (time.strftime("%Y-%m-%dT%H:%M:%S"), emb_json, k)).fetchall()
    for j, x in enumerate(top, 1):
        if x["id"] == gid:
            return j
    return None

out = []
for r in rows:
    gid = r["gold_id"]  # 16자
    rk = vec_rank(r["query"], gid)
    out.append({"query": r["query"], "gold_id": gid, "cat": r["cat"], "vec_rank": rk})
    print(f"[{r['cat']:22}] vec_rank={rk} | {r['query'][:40]}", flush=True)

json.dump(out, open(os.path.join(DATA, "stage19_gold_vec_rank.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n저장 완료", flush=True)

# 요약
ranks = [o["vec_rank"] for o in out if o["vec_rank"] is not None]
none = [o for o in out if o["vec_rank"] is None]
print(f"\nvec rank 있음: {len(ranks)}/23")
for cut in [40, 60, 100, 200, 300]:
    n = sum(1 for rk in ranks if rk <= cut)
    print(f"  rank <= {cut}: {n}")
print(f"rank 밖(>400 또는 None): {len(none)}")
conn.close()