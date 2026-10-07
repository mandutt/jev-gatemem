import json, os, sys, sqlite3, math
sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
os.chdir(r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden")

# 데몬 venv sitecustomize가 bench/bekko-a8m 강제 (여기엔 없으니 명시)
os.environ["MNEMOSYNE_EMBEDDING_MODEL"] = "bench/bekko-a8m"

import sqlite_vec
DB = r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
conn.enable_load_extension(True)
sqlite_vec.load(conn)

import mnemosyne.core.beam as beam_mod
from mnemosyne.core import embeddings as emb_mod

def cos(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0

q = "입력 토큰 늘어나면 응답 지연도 늘어?"
gid = "a112c8b5932f"
qemb = emb_mod.embed([q])
print("embed OK, dim:", len(qemb[0]), flush=True)

top = beam_mod._wm_vec_search(conn, qemb[0], k=200)
print("top-200:", len(top) if top else 0, flush=True)
if top:
    print("상위 10:", [(t.get("id")[:10], round(t.get("score", 0), 4)) for t in top[:10]], flush=True)
    found = next((i + 1 for i, t in enumerate(top) if t.get("id") == gid), None)
    print(f"gold rank: {found}", flush=True)

r = conn.execute("SELECT embedding_json FROM memory_embeddings WHERE memory_id=?", (gid,)).fetchone()
if r and r["embedding_json"]:
    gold_emb = json.loads(r["embedding_json"])
    print("gold emb dim:", len(gold_emb), flush=True)
    print(f"query<->gold cosine: {cos(qemb[0], gold_emb):.4f}", flush=True)
conn.close()