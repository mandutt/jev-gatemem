"""Stage-10b: chunk self-search sanity — RE-RUN with the CORRECT model.

Root cause of stage10 FAIL: direct `TextEmbedding()` loads BAAI/bge-small-en-v1.5
(fastembed default), NOT bench/bekko-a8m which sitecustomize pins for the beam
path. So any experiment using raw TextEmbedding() (stage1b/1c/3 vector parts)
measured the wrong model.

Fix: use `mnemosyne.core.embeddings` (beam's module — sitecustomize-pinned) for
embedding queries AND chunks, and compare against stored vectors (bekko-a8m).

Checks:
  A) verbatim mid-chunk self-search: chunk-vec rank (chunk embedded with beam
     embedder) vs parent row rank. Expect near-1.
  B) re-run the stage1c question: whole-row-vec rank vs chunk-max-vec rank for
     the real-usage gold 19 (mid queries) with the CORRECT model.
"""
import os, re, sqlite3, json, sys
import numpy as np
sys.path.insert(0, r"C:/Users/mandu/hermes-made/jev-memory-middleware")
os.environ.setdefault("MNEMOSYNE_EMBEDDING_MODEL", "bench/bekko-a8m")

import mnemosyne.core.beam as beam_mod
emb = beam_mod._embeddings  # sitecustomize-pinned to bekko-a8m
# sanity: confirm the model
import mnemosyne.core.embeddings as embmod
print("beam embedder module:", embmod.__file__)
print("default model:", getattr(embmod, "_DEFAULT_MODEL", "?"))

import sqlite_vec
DB = r"C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
conn.enable_load_extension(True)
sqlite_vec.load(conn)

vec = {}
for mid, ej in conn.execute("SELECT memory_id, embedding_json FROM memory_embeddings"):
    if ej:
        try:
            v = np.array(json.loads(ej), dtype=np.float32)
            if v.shape[0]: vec[mid] = v
        except Exception:
            pass
ids = list(vec.keys())
V = np.stack([vec[i] for i in ids])
V = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)
id2i = {i: k for k, i in enumerate(ids)}
print(f"stored vectors: {len(ids)}  dim {V.shape[1]}")

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

def body(c):
    m = re.match(r"^(\[[^\]]*\]\s*)?", c)
    return c[m.end():]

def rank_of(qv, target_id):
    qv = qv / (np.linalg.norm(qv) + 1e-9)
    sims = V @ qv
    order = np.argsort(-sims)
    return int(np.where(order == id2i[target_id])[0][0]) + 1, float(sims[id2i[target_id]])

def cls(c):
    h = c[:400]
    if '@file:' in h or '@url:' in h: return 'attach'
    if 'COMPACTION' in h or 'REFERENCE ONLY' in h: return 'compaction'
    if c.startswith('[opencode') or c.startswith('[codex'): return 'session'
    return 'plain'

# ---- A) verbatim mid-chunk self-search (correct model) ----------------------
long_rows = []
for t in ("working_memory", "episodic_memory"):
    for r in conn.execute(f"SELECT id, content FROM {t}"):
        c = r["content"]
        if c and len(c) >= 2000 and cls(c) == 'plain' and r["id"] in vec:
            long_rows.append((t, r["id"], c))
print(f"long plain rows with vector: {len(long_rows)}")

import random
random.seed(42)
sample = random.sample(long_rows, min(20, len(long_rows)))
print("\n[A] verbatim mid-chunk self-search (must be near 1):")
sims = []
for t, rid, c in sample:
    chs = chunks_of(body(c))
    mid_ch = chs[len(chs)//2]
    qv = np.asarray(emb.embed([mid_ch])[0], dtype=np.float32)
    r_chunk, s_parent = rank_of(qv, rid)
    sims.append(s_parent)
print(f"  parent-row sim (verbatim mid chunk): median {sorted(sims)[len(sims)//2]:.3f}  min {min(sims):.3f}  max {max(sims):.3f}")
print(f"  top-1 count: {sum(1 for s in sims if s > max(sims)-0.05)}/~{len(sims)}")

# ---- B) gold 19: whole vs chunk-max rank with CORRECT model ------------------
gold = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "data", "stage2_final_gold.json"), encoding="utf-8"))
print(f"\n[B] gold 19: whole-vec rank vs chunk-max rank (correct model)")
rowsB = []
for g in gold:
    rid = g["row_id"]
    if rid not in vec:
        continue
    r = conn.execute("SELECT content FROM working_memory WHERE id=?", (rid,)).fetchone()
    if not r:
        continue
    c = body(r["content"])
    qv = np.asarray(emb.embed([g["query"]])[0], dtype=np.float32)
    wr, _ = rank_of(qv, rid)
    chs = chunks_of(c)
    csims = []
    for ch in chs:
        cv = np.asarray(emb.embed([ch])[0], dtype=np.float32)
        _, s = rank_of(cv, rid)
        csims.append(s)
    # chunk-max: max parent sim over chunks = the chunk most similar to the stored row
    # but what we want: chunk that best matches the QUERY -> rank parent by max chunk sim to query
    maxc = max(csims)
    # chunk rank: query vs each chunk, parent rank via max chunk sim
    qchunks = []
    for ch in chs:
        cv = np.asarray(emb.embed([ch])[0], dtype=np.float32)
        qchunks.append(cv)
    C = np.stack([q / (np.linalg.norm(q)+1e-9) for q in qchunks])
    sims_qc = C @ (qv / (np.linalg.norm(qv)+1e-9))
    best = sims_qc.max()
    # rank of parent if we used chunk-max-sim to query? -> approximate: best chunk sim vs all stored
    best_chunk = qchunks[int(sims_qc.argmax())]
    cr, _ = rank_of(best_chunk, rid)
    rowsB.append((rid[:14], len(c), wr, cr, best))
rowsB.sort(key=lambda x: x[2])
print(f"  n={len(rowsB)}")
print(f"  whole rank median: {sorted(r[2] for r in rowsB)[len(rowsB)//2]}  chunk rank median: {sorted(r[3] for r in rowsB)[len(rowsB)//2]}")
print(f"  whole rank<=2: {sum(1 for r in rowsB if r[2]<=2)}  chunk rank<=2: {sum(1 for r in rowsB if r[3]<=2)}")
print(f"  best chunk-parent sim vs query: median {sorted(r[4] for r in rowsB)[len(rowsB)//2]:.3f}")
for rid, ln, wr, cr, best in rowsB[:20]:
    print(f"  {rid} len={ln:>5} whole={wr:>4} chunk={cr:>4} bsim={best:.3f}")

conn.close()
print("\nDONE")