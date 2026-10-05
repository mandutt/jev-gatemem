"""Stage-10: chunk self-search sanity check (b-ai 지적 #3).

If the embedding harness is sound, a verbatim chunk fed as a query must rank
the chunk's own row at/near 1 (cosine ~ 1). b-ai flagged stage1c's median
rank 918 as implausible. Verify:

  A) sanity: for long rows, embed a mid 800-char chunk VERBATIM as query ->
     rank of the parent row (whole-row vec) and of the chunk itself
     (chunk vec). Expect near-1 for chunk-vec rank, and decent for whole.
  B) why did stage1c show median 918? Reproduce with the SAME code path
     (TextEmbedding via mnemosyne beam) and ONE manual numpy cosine ->
     compare. Possible causes: quantized int8 vec0, query vs doc prefix,
     or genuinely weak mid-chunk similarity.

0 JEV calls. Live DB read-only.
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

# full stored vectors (memory_embeddings json)
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

from fastembed import TextEmbedding
emb = TextEmbedding()

def chunks_of(content, size=800):
    paras = re.split(r"\n+", content)
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

def rank_of(qv, target_id):
    qv = qv / (np.linalg.norm(qv) + 1e-9)
    sims = V @ qv
    order = np.argsort(-sims)
    return int(np.where(order == id2i[target_id])[0][0]) + 1, sims[id2i[target_id]]

# sample long plain rows
def cls(c):
    h = c[:400]
    if '@file:' in h or '@url:' in h: return 'attach'
    if 'COMPACTION' in h or 'REFERENCE ONLY' in h: return 'compaction'
    if c.startswith('[opencode') or c.startswith('[codex'): return 'session'
    return 'plain'

long_rows = []
for t in ("working_memory", "episodic_memory"):
    for r in conn.execute(f"SELECT id, content FROM {t}"):
        c = r["content"]
        if c and len(c) >= 2000 and cls(c) == 'plain' and r["id"] in vec:
            long_rows.append((t, r["id"], c))
print(f"long plain rows with vector: {len(long_rows)}")

# A) verbatim chunk self-search on a sample of 20
import random
random.seed(42)
sample = random.sample(long_rows, min(20, len(long_rows)))
print("\n[A] verbatim mid-chunk self-search (sample 20):")
ranks_chunk, ranks_whole, sims_chunk, sims_whole = [], [], [], []
for t, rid, c in sample:
    chs = chunks_of(c)
    mid_ch = chs[len(chs)//2]  # middle chunk
    qv = np.asarray(next(emb.embed([mid_ch])), dtype=np.float32)
    r_chunk, s_chunk = rank_of(qv, rid)
    # also whole-row vec sim for the same query
    wv = vec[rid]; wv = wv / (np.linalg.norm(wv) + 1e-9)
    s_whole = float(V[id2i[rid]] @ qv)
    sims_chunk.append(s_chunk); sims_whole.append(s_whole)
print(f"  chunk-vec rank: median {sorted(ranks_chunk)[len(ranks_chunk)//2] if ranks_chunk else '-'} top-1 {sum(1 for r in ranks_chunk if r==1)}/{len(ranks_chunk)}")
print(f"  whole-vec sim (mid query vs stored row vec): median {sorted(sims_whole)[len(sims_whole)//2]:.3f}, min {min(sims_whole):.3f}")

# B) compare with the stage1c path: embed via mnemosyne beam._embeddings
import mnemosyne.core.beam as beam_mod
beam_emb = beam_mod._embeddings
print("\n[B] beam._embeddings vs fastembed direct (sample 5):")
for t, rid, c in sample[:5]:
    chs = chunks_of(c)
    mid_ch = chs[len(chs)//2]
    qv1 = np.asarray(next(emb.embed([mid_ch])), dtype=np.float32)
    qv2 = np.asarray(beam_emb.embed([mid_ch])[0], dtype=np.float32)
    # cosine between the two embeddings
    cos = float((qv1 @ qv2) / (np.linalg.norm(qv1) * np.linalg.norm(qv2) + 1e-9))
    print(f"  {rid[:14]} fastembed-vs-beam cosine: {cos:.4f}")

print("\nDONE")
conn.close()