"""Stage-1 probe (part 2): vector-dilution simulation — 0 JEV calls, local embedding only.

Hypothesis: long rows (>1350 chars) are embedded with a 512-token clamp (bekko-a8m
tokenizer clamp in sitecustomize), so mid/tail information is structurally absent
from the stored vector. Chunk-level embedding should recover them.

Design:
- Load real stored vectors from memory_embeddings (the exact vectors the live
  pipeline uses).
- For each long row (>1350 chars, sample), take 2 pseudo-queries derived from the
  row itself: head-300 chars and middle-300 chars (40-55% span).
- whole-rank: cosine(query, stored row vector) rank among all 1738 rows.
- chunk-rank: split row into paragraph/sentence chunks, embed each (fresh, clamp ok),
  take max cosine rank.
- Report how often chunking lifts a mid/head snippet from outside top-N into top-N.

DB is read-only. Uses the jev-mem venv python (fastembed + sitecustomize pin).
"""
import sqlite3, json, re, sys, os, time
import numpy as np

DB = r"C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
cur = conn.cursor()

# 1) load stored vectors (memory_embeddings)
vec_rows = cur.execute(
    "SELECT memory_id, embedding_json, model FROM memory_embeddings"
).fetchall()
vecs, ids = [], []
for mid, ej, model in vec_rows:
    if not ej:
        continue
    v = np.array(json.loads(ej), dtype=np.float32)
    if v.shape[0] == 0:
        continue
    vecs.append(v)
    ids.append(mid)
V = np.stack(vecs)  # (N, dim)
V = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)
id2idx = {m: i for i, m in enumerate(ids)}
print(f"stored vectors: {len(ids)}, dim {V.shape[1]}, models: {set(m for _,_,m in vec_rows)}", flush=True)

# 2) long rows
content = {}
for t in ("working_memory", "episodic_memory"):
    for cid, c in cur.execute(f"SELECT id, content FROM {t}"):
        if c:
            content[cid] = c
conn.close()

long_rows = [(cid, c) for cid, c in content.items() if len(c) > 1350]
long_rows.sort(key=lambda x: -len(x[1]))
print(f"long rows >1350: {len(long_rows)}", flush=True)

# sample: all >3000 (75) + every 3rd of 1350-3000 (~40) -> ~115
sample = [r for r in long_rows if len(r[1]) > 3000]
sample += [r for r in long_rows if 1350 < len(r[1]) <= 3000][::3]
print(f"sampled: {len(sample)}", flush=True)

def head300(c): return c[:300]
def mid300(c):
    n = len(c)
    s = int(n * 0.42)
    return c[s:s+300]

def chunks_of(c, size=800):
    """split by para first, then hard-split oversized paras"""
    paras = re.split(r"\n+", c)
    out, cur_acc = [], ""
    for p in paras:
        p = p.strip()
        if not p:
            continue
        if len(cur_acc) + len(p) + 1 > size and cur_acc:
            out.append(cur_acc)
            cur_acc = p
        else:
            cur_acc = cur_acc + "\n" + p if cur_acc else p
    if cur_acc:
        out.append(cur_acc)
    # hard split still-oversized
    res = []
    for ch in out:
        while len(ch) > 1100:
            res.append(ch[:1100])
            ch = ch[1100:]
        res.append(ch)
    return res

# 3) embed queries + chunks via fastembed (jev-mem venv, sitecustomize pins model)
from fastembed import TextEmbedding
t0 = time.time()
emb = TextEmbedding()
print(f"embedder ready in {time.time()-t0:.1f}s", flush=True)

def embed_texts(texts):
    out = []
    for v in emb.embed(texts):
        out.append(np.asarray(v, dtype=np.float32))
    return np.stack(out)

queries = []  # (cid, part, text)
for cid, c in sample:
    queries.append((cid, "head", head300(c)))
    queries.append((cid, "mid", mid300(c)))
qtexts = [q[2] for q in queries]
Q = embed_texts(qtexts)
Q = Q / (np.linalg.norm(Q, axis=1, keepdims=True) + 1e-9)
print(f"query embeds: {len(qtexts)} in {time.time()-t0:.1f}s total", flush=True)

# stored-vector ranks (whole)
sims = Q @ V.T  # (nq, N)
whole_ranks = []
for i, (cid, part, txt) in enumerate(queries):
    if cid not in id2idx:
        whole_ranks.append(None)
        continue
    sj = sims[i]
    order = np.argsort(-sj)
    rank = int(np.where(order == id2idx[cid])[0][0]) + 1
    whole_ranks.append(rank)

# chunk ranks
chunk_ranks = []
chunk_cache = {}
for i, (cid, part, txt) in enumerate(queries):
    if cid not in id2idx:
        chunk_ranks.append(None)
        continue
    if cid not in chunk_cache:
        chs = chunks_of(content[cid])
        if not chs:
            chunk_ranks.append(None)
            continue
        CV = embed_texts(chs)
        CV = CV / (np.linalg.norm(CV, axis=1, keepdims=True) + 1e-9)
        # max sim per chunk over full pool
        cs = CV @ V.T
        chunk_scores = cs.max(axis=0)
        chunk_cache[cid] = chunk_scores
    else:
        chunk_scores = chunk_cache[cid]
    order = np.argsort(-chunk_scores)
    rank = int(np.where(order == id2idx[cid])[0][0]) + 1
    chunk_ranks.append(rank)

# 4) report
print("\n" + "=" * 70)
print("whole-rank vs chunk-rank (rank of the true row among 1738)")
print("=" * 70)
hl = []
for i, (cid, part, txt) in enumerate(queries):
    wr, cr = whole_ranks[i], chunk_ranks[i]
    if wr is None or cr is None:
        continue
    hl.append((wr, cr, part, len(content[cid]), cid))
hl.sort(key=lambda x: x[0])

def pct(lst): return sum(lst) / len(lst) if lst else 0

wr_vals = [h[0] for h in hl]
cr_vals = [h[1] for h in hl]
print(f"pairs: {len(hl)}")
for N in (10, 30, 100):
    print(f"  whole top-{N}: {pct([w<=N for w in wr_vals]):.3f}   chunk top-{N}: {pct([c<=N for c in cr_vals]):.3f}")
print(f"  whole median rank: {sorted(wr_vals)[len(wr_vals)//2]}   chunk median rank: {sorted(cr_vals)[len(cr_vals)//2]}")
lifted = [(w, c, part, n, cid) for w, c, part, n, cid in hl if c < w and c <= 100]
hurt = [(w, c, part, n, cid) for w, c, part, n, cid in hl if c > w and w <= 100]
print(f"\n  lifted into top-100 by chunking: {len(lifted)}")
for w, c, part, n, cid in lifted[:12]:
    print(f"    {part:4s} len={n:>6,}  whole rank {w:>5,} -> chunk rank {c:>5,}  {cid[:16]}")
print(f"  hurt (was <=100, chunk pushed out): {len(hurt)}")
for w, c, part, n, cid in hurt[:8]:
    print(f"    {part:4s} len={n:>6,}  whole rank {w:>5,} -> chunk rank {c:>5,}  {cid[:16]}")

print("\nDONE")