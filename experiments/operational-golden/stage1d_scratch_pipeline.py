"""Stage-1d scratch verification: would chunk-stored rows recover mid-text queries
through the ACTUAL production lane-pool + gate pipeline?

0 JEV calls. Live DB read-only. A scratch COPY of the live DB is built in the
scratch dir with the 41 long rows (len>=2000) REPLACED by their rule-based
800-char chunks (each chunk its own row with its own embedding). Then the real
pipeline primitives (mnemosyne.core.beam._fts_search_working / _wm_vec_search /
gateway.j1_pipeline.build_lane_pool / _filter_and_rank) run the same mid-queries.

This answers: "if we stored chunks at write time, does the ACTUAL retrieval path
find the answer?" — without touching the live DB or any production code.
"""
import os, re, sqlite3, json, shutil, sys, tempfile, time
import numpy as np

REPO = r"C:/Users/mandu/hermes-made/jev-memory-middleware"
sys.path.insert(0, REPO)
os.environ.setdefault("MNEMOSYNE_EMBEDDING_MODEL", "bench/bekko-a8m")

DB = r"C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
SCRATCH = os.path.join(os.environ.get("TMPDIR", tempfile.gettempdir()), "jev_scratch_chunk")
os.makedirs(SCRATCH, exist_ok=True)
SCRATCH_DB = os.path.join(SCRATCH, "mnemosyne_scratch.db")

# sqlite-vec extension must be loaded on every connection used for vec search
import sqlite_vec

def connect_db(path: str) -> sqlite3.Connection:
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    try:
        c.enable_load_extension(True)
        sqlite_vec.load(c)
    except Exception as e:
        print(f"  sqlite_vec load failed on {path}: {e}", flush=True)
    return c

def cls(c):
    h = c[:400]
    if '@file:' in h or '@url:' in h: return 'attach'
    if 'COMPACTION' in h or 'REFERENCE ONLY' in h: return 'compaction'
    if c.startswith('[opencode') or c.startswith('[codex'): return 'session'
    return 'plain'

# ---- 1) copy live DB ------------------------------------------------------
print("copying live DB -> scratch...", flush=True)
t0 = time.time()
# fresh scratch DBs every run (stale artifacts from prior runs invalidate results)
for stale in (SCRATCH_DB, os.path.join(SCRATCH, "mnemosyne_base.db")):
    if os.path.exists(stale):
        os.remove(stale)
# VACUUM INTO gives a clean consistent copy without -wal/-shm
src = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
dst = connect_db(SCRATCH_DB)
src.backup(dst)
src.close()
dst.close()
print(f"  copied in {time.time()-t0:.1f}s", flush=True)

conn = connect_db(SCRATCH_DB)
cur = conn.cursor()
# FTS tables must expose freshly inserted chunk rows; drop & rebuild after inserts
FTS_TABLES = {"working_memory": "fts_working", "episodic_memory": "fts_episodes"}

# ---- 2) identify long plain rows and their mid-queries ---------------------
long_rows = []
for t in ("working_memory", "episodic_memory"):
    for cid, c in cur.execute(f"SELECT id, content FROM {t}"):
        if c and len(c) >= 2000 and cls(c) == 'plain':
            long_rows.append((t, cid, c))
queries = []
for t, cid, c in long_rows:
    s = int(len(c) * 0.55)
    queries.append((t, cid, c[s:s+200], c))
print(f"long plain rows: {len(long_rows)}", flush=True)

# ---- 3) chunk them (same rule as stage1c), store as rows -------------------
META_P = re.compile(r"^(\[[^\]]*\]\s*)?")
def strip_meta(c):
    m = META_P.match(c)
    return m.group(0) or ""

def chunks_of(c, size=800):
    paras = re.split(r"\n+", c)
    out, acc = [], ""
    for p in paras:
        p = p.strip()
        if not p: continue
        if len(acc) + len(p) + 1 > size and acc:
            out.append(acc); acc = p
        else:
            acc = acc + "\n" + p if acc else p
    if acc: out.append(acc)
    res = []
    for ch in out:
        while len(ch) > 1100:
            res.append(ch[:1100]); ch = ch[1100:]
        res.append(ch)
    return res

# build chunk rows: keep original id for parent, chunk rows get id = parent + ":c<i>"
chunk_rows = []  # (table, new_id, content, parent_id, chunk_idx)
replace_ids = set()
for t, cid, c in long_rows:
    chs = chunks_of(c)
    if len(chs) < 2:
        continue
    replace_ids.add(cid)
    for i, ch in enumerate(chs):
        chunk_rows.append((t, f"{cid}:c{i}", ch, cid, i))

print(f"rows to replace: {len(replace_ids)}, chunk rows to insert: {len(chunk_rows)}", flush=True)

# ---- 4) apply to scratch DB ------------------------------------------------
# take a full snapshot of the long rows BEFORE deleting them (chunk rows copy
# parent columns — the parent must still be queryable at insert time)
import datetime
now_iso = datetime.datetime.now().isoformat()
parent_snap = {}
for t, cid, c in long_rows:
    prow = cur.execute(f"SELECT * FROM {t} WHERE id=?", (cid,)).fetchone()
    if prow:
        cols = [d[1] for d in cur.execute(f"PRAGMA table_info({t})").fetchall()]
        parent_snap[(t, cid)] = (cols, dict(zip(cols, prow)))

# delete originals
for t, cid, c in long_rows:
    cur.execute(f"DELETE FROM {t} WHERE id=?", (cid,))
    cur.execute("DELETE FROM memory_embeddings WHERE memory_id=?", (cid,))
    for vt in ("vec_working", "vec_episodes"):
        try: cur.execute(f"DELETE FROM {vt} WHERE memory_id=?", (cid,))
        except Exception: pass

# insert chunk rows with sensible defaults (parent snapshot)
idmap = {}
inserted = 0
for t, new_id, ch, parent, idx in chunk_rows:
    snap = parent_snap.get((t, parent))
    if not snap:
        continue
    cols, prowd = snap
    prowd = dict(prowd)
    prowd["id"] = new_id
    prowd["content"] = ch
    # keep metadata but add chunk marker (without overriding parent ref)
    meta = json.loads(prowd.get("metadata_json") or "{}")
    meta["chunk_of"] = parent
    meta["chunk_idx"] = idx
    prowd["metadata_json"] = json.dumps(meta, ensure_ascii=False)
    placeholders = ",".join("?" * len(cols))
    cur.execute(f"INSERT OR REPLACE INTO {t} ({','.join(cols)}) VALUES ({placeholders})", [prowd[c] for c in cols])
    inserted += 1
conn.commit()
print(f"chunk rows inserted: {inserted}", flush=True)

# ---- 4b) rebuild FTS so chunk rows are searchable ---------------------------
for src_tbl, fts_tbl in FTS_TABLES.items():
    cur.execute(f"DROP TABLE IF EXISTS {fts_tbl}")
    cur.execute(f"CREATE VIRTUAL TABLE {fts_tbl} USING fts5(id UNINDEXED, content)")
    rows = cur.execute(f"SELECT id, content FROM {src_tbl}").fetchall()
    cur.executemany(f"INSERT INTO {fts_tbl} (id, content) VALUES (?,?)", [(r["id"], r["content"]) for r in rows])
conn.commit()
print("FTS rebuilt", flush=True)

# ---- 4c) rebuild vec0 virtual tables (rowid-aligned with main tables) --------
# try to use the same schema as the live DB
for src_tbl, vec_tbl in (("working_memory", "vec_working"), ("episodic_memory", "vec_episodes")):
    try:
        schema = cur.execute(f"SELECT sql FROM sqlite_master WHERE name=?", (vec_tbl,)).fetchone()
        if schema:
            cur.execute(f"DROP TABLE IF EXISTS {vec_tbl}")
            cur.execute(schema[0])
    except Exception as e:
        print(f"  vec0 rebuild note {vec_tbl}: {e}", flush=True)
conn.commit()
print("vec0 tables reset", flush=True)

# ---- 5) produce embeddings for CHUNK rows + insert into memory_embeddings ----
chunk_ids = [r[1] for r in chunk_rows]
chunk_contents = [r[2] for r in chunk_rows]
from fastembed import TextEmbedding
emb = TextEmbedding()
vecs = [np.asarray(v, dtype=np.float32) for v in emb.embed(chunk_contents)]
model = "bench/bekko-a8m"
for mid, v in zip(chunk_ids, vecs):
    cur.execute(
        "INSERT OR REPLACE INTO memory_embeddings (memory_id, embedding_json, model, created_at) VALUES (?,?,?,?)",
        (mid, json.dumps(v.tolist()), model, now_iso),
    )
# original long rows were deleted; their vectors remain only if we remove them —
# already removed. BUT the vec0 tables were truncated — re-populate from
# memory_embeddings for ALL rows so vec lane works in scratch.
# (vec_working is rowid-aligned with working_memory; insert by rowid)
mem_rows = cur.execute("SELECT memory_id, embedding_json FROM memory_embeddings").fetchall()
for vt, src_tbl in (("vec_working", "working_memory"), ("vec_episodes", "episodic_memory")):
    cur.execute(f"DELETE FROM {vt}")
    for mid, ej in mem_rows:
        r = cur.execute(f"SELECT rowid FROM {src_tbl} WHERE id=?", (mid,)).fetchone()
        if not r:
            continue
        v = json.loads(ej)
        # vec0 int8 storage: live DB uses vec_quantize_int8('unit'); quantize on insert
        cur.execute(f"INSERT INTO {vt} (rowid, embedding) VALUES (?, vec_quantize_int8(?, 'unit'))", (r["rowid"], json.dumps(v)))
conn.commit()
print(f"embedded {len(chunk_ids)} chunk rows; vec0 repopulated", flush=True)

# ---- 6) run the ACTUAL pipeline --------------------------------------------
import mnemosyne.core.beam as beam_mod
from gateway.j1_pipeline import build_lane_pool, _filter_and_rank

# build a second scratch DB (baseline) from the live DB WITHOUT chunking
BASE_DB = os.path.join(SCRATCH, "mnemosyne_base.db")
if not os.path.exists(BASE_DB):
    src = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    dst = connect_db(BASE_DB)
    src.backup(dst)
    src.close(); dst.close()
    print("baseline DB built", flush=True)
conn_base = connect_db(BASE_DB)

# beam._fts_search_working requires sqlite3.Row row_factory (r["id"] indexing)
conn.row_factory = sqlite3.Row
conn_base.row_factory = sqlite3.Row

print("\nshape check:", beam_mod._fts_search_working(conn, "Jev-Mem 논문", k=3)[:1], flush=True)

def j1_imp(cx, k=50):
    from gateway.j1_pipeline import _imp_search
    return _imp_search(cx, k=k)
def j1_graph(cx, q, k=50):
    from gateway.j1_pipeline import _graph_lane_search
    return _graph_lane_search(cx, q, k=k)

def run(cx, q, target_cid):
    def recall_raw(kind, arg, k):
        if kind == "fts": return beam_mod._fts_search_working(cx, arg, k=k)
        if kind == "vec":
            qemb = beam_mod._embeddings.embed([arg])
            if qemb is None or not len(qemb): return []
            return beam_mod._wm_vec_search(cx, qemb[0], k=k)
        if kind == "imp": return j1_imp(cx, k=k)
        if kind == "graph": return j1_graph(cx, arg, k=k)
        if kind == "get":
            r = cx.execute("SELECT id, content, source, importance, metadata_json FROM working_memory WHERE id=?", (arg,)).fetchone()
            if not r:
                r = cx.execute("SELECT id, content, source, importance, metadata_json FROM episodic_memory WHERE id=?", (arg,)).fetchone()
            if not r: return None
            return {"id": r[0], "content": r[1], "source": r[2], "importance": r[3], "metadata_json": r[4]}
        return []
    pool = build_lane_pool(recall_raw, q)
    pool_ids = [r["id"] for r in pool]
    hit_pool = target_cid in pool_ids or any(
        (pid == target_cid) or (isinstance(pid, str) and pid.startswith(target_cid + ":"))
        for pid in pool_ids
    )
    # also hydrate pool rows for the gate (build_lane_pool hydrates via 'get')
    filtered = _filter_and_rank(pool, q)[:40]
    fids = [r.get("id") for r in filtered]
    hit_gate = target_cid in fids or any(
        (f == target_cid) or (isinstance(f, str) and f.startswith(target_cid + ":"))
        for f in fids
    )
    return hit_pool, hit_gate

res = []
if os.environ.get("STAGE2_GOLD") == "1":
    # ---- real-usage gold mode ----
    gold = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "data", "stage2_final_gold.json"), encoding="utf-8"))
    print(f"\nreal-usage gold mode: {len(gold)} queries")
    for g in gold:
        q, target = g["query"], g["row_id"]
        hp_b, hg_b = run(conn_base, q, target)
        hp_c, hg_c = run(conn, q, target)
        res.append((target, hp_b, hg_b, hp_c, hg_c, g["row_len"]))
else:
    for t, cid, q, c in queries:
        hp_b, hg_b = run(conn_base, q, cid)
        hp_c, hg_c = run(conn, q, cid)
        res.append((cid, hp_b, hg_b, hp_c, hg_c, len(c)))
print("\n" + "=" * 70)
print(f"pipeline comparison on {len(res)} mid-queries (baseline vs chunked)")
print("=" * 70)
print(f"pool hit:  baseline {sum(1 for r in res if r[1])}/{len(res)}   chunked {sum(1 for r in res if r[3])}/{len(res)}")
print(f"gate hit:  baseline {sum(1 for r in res if r[2])}/{len(res)}   chunked {sum(1 for r in res if r[4])}/{len(res)}")
print("\nper-row:")
for cid, hpb, hgb, hpc, hgc, n in res:
    mark_p = "OK " if hpc and not hpb else ("NEW" if hpc and not hpb else ("LOST" if hpb and not hpc else "  -"))
    mark_g = "OK " if hgc and not hgb else ("NEW" if hgc and not hgb else ("LOST" if hgb and not hgc else "  -"))
    print(f"  {cid[:14]} len={n:>5}  pool {int(hpb)}->{int(hpc)} {mark_p}   gate {int(hgb)}->{int(hgc)} {mark_g}")
conn.close(); conn_base.close()
print("\nDONE")