"""Stage-20: sidecar FTS5 chunk lane pilot (b-ai #7).

Design (b-ai): keep rows as-is; build a chunk-only FTS5 index (sidecar) where
each long row's 800-char chunks are searchable. Query -> FTS top chunks ->
collapse to parent ids (1 slot per parent, width 5-10) -> add as 5th RRF lane.

0 JEV calls. Live DB read-only (in-memory FTS built from long rows).

Measures:
  A) gold 19: pool recovery with +chunkFTS lane vs baseline (current state:
     [ASSISTANT] lifted + POOL_BUDGET 60)
  B) op-90 regression (gate pass)
  C) noans spurious
"""
import os, re, sqlite3, json, sys
import numpy as np
sys.path.insert(0, r"C:/Users/mandu/hermes-made/jev-memory-middleware")
os.environ.setdefault("MNEMOSYNE_EMBEDDING_MODEL", "bench/bekko-a8m")

import sqlite_vec
DB = r"C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
conn.enable_load_extension(True)
sqlite_vec.load(conn)

import mnemosyne.core.beam as beam_mod
from gateway.j1_pipeline import build_lane_pool, _filter_and_rank, _imp_search, _graph_lane_search, POOL_BUDGET

def cls(c):
    h = c[:400]
    if '@file:' in h or '@url:' in h: return 'attach'
    if 'COMPACTION' in h or 'REFERENCE ONLY' in h: return 'compaction'
    if c.startswith('[opencode') or c.startswith('[codex'): return 'session'
    return 'plain'

def body(c):
    m = re.match(r"^(\[[^\]]*\]\s*)?", c)
    return c[m.end():]

def chunks_of(content, size=800):
    paras = re.split(r"\n+", content)
    out, acc = [], ""
    for p in paras:
        p = p.strip()
        if not p: continue
        if len(acc)+len(p)+1 > size and acc:
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

# ---- build sidecar chunk FTS in memory -------------------------------------
chunk_rows = []  # (chunk_id, parent_id, chunk_text)
long_rows = {}
for t in ("working_memory", "episodic_memory"):
    for r in conn.execute(f"SELECT id, content FROM {t}"):
        c = r["content"]
        if c and len(c) >= 2000 and cls(c) == 'plain':
            long_rows[r["id"]] = body(c)
for pid, c in long_rows.items():
    for i, ch in enumerate(chunks_of(c)):
        chunk_rows.append((f"{pid}:c{i}", pid, ch))

# in-memory FTS5
import sqlite3 as s3
mem = s3.connect(":memory:")
mem.execute("CREATE VIRTUAL TABLE chunk_fts USING fts5(chunk_id UNINDEXED, parent_id UNINDEXED, content)")
mem.executemany("INSERT INTO chunk_fts (chunk_id, parent_id, content) VALUES (?,?,?)",
                chunk_rows)
print(f"sidecar chunks: {len(chunk_rows)} (from {len(long_rows)} long rows)")

def chunk_lane_fts(query, top_chunks=12, parent_slots=6):
    """FTS query -> top chunks -> collapse to parents (1 slot each)."""
    # use beam's FTS query term builder for CJK-friendly search
    hits = beam_mod._fts_search_working(mem, query, k=top_chunks*4)  # reuse term logic? mem lacks schema — use raw
    return []

# simpler: use LIKE-based fallback for CJK (beam _cjk_like_search on our mem conn)
def chunk_lane_cjk(query, top_chunks=12, parent_slots=6):
    # score chunks by counting query token occurrences (CJK char overlap)
    qt = set(re.findall(r"[\uac00-\ud7af]", query))
    if not qt:
        return []
    scores = []
    for (cid, pid, text) in chunk_rows:
        ct = set(re.findall(r"[\uac00-\ud7af]", text))
        ov = len(qt & ct)
        if ov >= 2:
            scores.append((ov, pid))
    scores.sort(key=lambda x: -x[0])
    # collapse to parents (1 slot), keep top slots
    seen = set(); out = []
    for ov, pid in scores:
        if pid not in seen:
            seen.add(pid)
            out.append({"id": pid, "rank": len(out)+1})
            if len(out) >= parent_slots:
                break
    return out

def chunk_lane(query, top_chunks=12, parent_slots=6):
    return chunk_lane_cjk(query, top_chunks, parent_slots)

# ---- integrated recall_raw with chunk lane ---------------------------------
_CHUNK = {"v": True}

def recall_raw(kind, arg, k):
    if kind == "fts": return beam_mod._fts_search_working(conn, arg, k=k)
    if kind == "vec":
        qemb = beam_mod._embeddings.embed([arg])
        if qemb is None or not len(qemb): return []
        return beam_mod._wm_vec_search(conn, qemb[0], k=k)
    if kind == "imp": return _imp_search(conn, k=k)
    if kind == "graph": return _graph_lane_search(conn, arg, k=k)
    if kind == "chunk":
        if not _CHUNK["v"]:
            return []
        return chunk_lane(arg)
    if kind == "get":
        r = conn.execute("SELECT id, content, source, importance FROM working_memory WHERE id=?", (arg,)).fetchone()
        if not r:
            r = conn.execute("SELECT id, content, source, importance FROM episodic_memory WHERE id=?", (arg,)).fetchone()
        if not r: return None
        return {"id": r[0], "content": r[1], "source": r[2], "importance": r[3]}
    return []

# ---- A) gold 19 ------------------------------------------------------------
gold = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "data", "stage2_final_gold.json"), encoding="utf-8"))
print(f"\n=== A) gold 19 (baseline vs +chunkFTS lane) ===")
resA = []
for g in gold:
    q = g["query"]; target = g["row_id"]
    _CHUNK["v"] = False
    pool0 = build_lane_pool(recall_raw, q)
    f0 = _filter_and_rank(pool0, q)[:POOL_BUDGET]
    h0 = target in [r.get("id") for r in f0]
    _CHUNK["v"] = True
    pool1 = build_lane_pool(recall_raw, q)
    f1 = _filter_and_rank(pool1, q)[:POOL_BUDGET]
    h1 = target in [r.get("id") for r in f1]
    resA.append((target[:14], h0, h1, len(pool0), len(pool1)))
print(f"gate pass: base {sum(r[1] for r in resA)}/19  +chunkFTS {sum(r[2] for r in resA)}/19")
new = [r for r in resA if not r[1] and r[2]]
print(f"NEW: {len(new)} {[r[0] for r in new]}")
lost = [r for r in resA if r[1] and not r[2]]
print(f"LOST: {len(lost)} {[r[0] for r in lost]}")

# ---- B) op-90 ---------------------------------------------------------------
goldset = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "data", "golden_eval_v3.json"), encoding="utf-8"))
gold_qs = [(g["gold"], g["query"]) for g in goldset if g.get("gold")]
print(f"\n=== B) op-90 regression ===")
reg = 0
for target, q in gold_qs:
    _CHUNK["v"] = False
    f0 = _filter_and_rank(build_lane_pool(recall_raw, q), q)[:POOL_BUDGET]
    h0 = target in [r.get("id") for r in f0]
    _CHUNK["v"] = True
    f1 = _filter_and_rank(build_lane_pool(recall_raw, q), q)[:POOL_BUDGET]
    h1 = target in [r.get("id") for r in f1]
    if h0 and not h1:
        reg += 1
print(f"op-90 gate regressions: {reg}/{len(gold_qs)}")

# ---- C) noans ---------------------------------------------------------------
noans_qs = [g for g in goldset if not g.get("gold")]
print(f"\n=== C) noans ===")
sp0 = sp1 = 0
for g in noans_qs:
    q = g["query"]
    _CHUNK["v"] = False
    f0 = _filter_and_rank(build_lane_pool(recall_raw, q), q)[:POOL_BUDGET]
    if f0: sp0 += 1
    _CHUNK["v"] = True
    f1 = _filter_and_rank(build_lane_pool(recall_raw, q), q)[:POOL_BUDGET]
    if f1: sp1 += 1
print(f"noans ANY pass: base {sp0}/10  +chunkFTS {sp1}/10")

conn.close()
print("\nDONE")