"""Stage-1b probe: plain long rows (>1350) full census + retrieval exposure.

0 JEV calls, DB read-only.

1) Census of 130 plain rows: length distribution, utterance type (ASSISTANT report /
   USER pasted doc / conversation dump), whether content is structured such that
   excerpt-120/gate-800 can ever answer.
2) Retrieval-exposure estimate: for each plain long row, derive 2 pseudo-queries
   (head-200, mid-200) and rank the row via the same local pipeline primitives:
   FTS (fts_working/fts_episodes) + stored vector cosine. Report what fraction of
   long rows can be recovered from a mid-text query — i.e. the actual blind spot.
   Also measure: does the 120-char excerpt (what prefetch would show) contain
   any distinctive keyword that could match a query?
"""
import sqlite3, json, re, collections, os
import numpy as np

DB = r"C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
cur = conn.cursor()

def cls(c):
    h = c[:400]
    if '@file:' in h or '@url:' in h: return 'attach'
    if 'COMPACTION' in h or 'REFERENCE ONLY' in h: return 'compaction'
    if c.startswith('[opencode') or c.startswith('[codex'): return 'session'
    return 'plain'

rows = []
for t in ('working_memory', 'episodic_memory'):
    for cid, c in cur.execute(f"SELECT id, content FROM {t}"):
        if c and len(c) > 1350 and cls(c) == 'plain':
            rows.append((t, cid, c))
print(f"plain long rows: {len(rows)}", flush=True)

# ---- 1) census -----------------------------------------------------------
lens = sorted(len(c) for _, _, c in rows)
print(f"len: min {lens[0]} p50 {lens[len(lens)//2]} p90 {lens[int(len(lens)*0.9)]} max {lens[-1]}")
buckets = collections.Counter()
for t, cid, c in rows:
    n = len(c)
    b = '1351-2000' if n <= 2000 else '2001-3000' if n <= 3000 else '3001-6000' if n <= 6000 else '6001-10000' if n <= 10000 else '>10000'
    buckets[b] += 1
print("buckets:", dict(buckets))

def utype(c):
    if c.startswith('[ASSISTANT]'): return 'assistant'
    if c.startswith('[USER]'): return 'user'
    if c.startswith('[conversation]'): return 'conversation'
    return 'other'
print("utype:", dict(collections.Counter(utype(c) for _,_,c in rows)))

# ---- 2) FTS + vector availability -----------------------------------------
# does each long row exist in FTS tables?
fts_ok = 0
for t, cid, c in rows:
    ft = 'fts_working' if t == 'working_memory' else 'fts_episodes'
    try:
        n = cur.execute(f"SELECT COUNT(*) FROM {ft} WHERE rowid=(SELECT rowid FROM {t} WHERE id=?)", (cid,)).fetchone()[0]
        if n: fts_ok += 1
    except Exception as e:
        pass
print(f"rows present in FTS: {fts_ok}/{len(rows)}")

# stored vectors
vec = {}
for mid, ej in cur.execute("SELECT memory_id, embedding_json FROM memory_embeddings"):
    if ej:
        try: vec[mid] = np.array(json.loads(ej), dtype=np.float32)
        except Exception: pass
print(f"rows with stored vector: {sum(1 for _,cid,_ in rows if cid in vec)}/{len(rows)}")

# ---- 3) mid-text recall via stored vectors (self-derived queries) ----------
# For each long row with a vector: query = 200 chars from the MIDDLE (55-60% span).
# Rank by cosine among all vectors. Top-1 self match = recovered.
ids = list(vec.keys())
V = np.stack([vec[i] for i in ids])
V = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)
id2i = {i: k for k, i in enumerate(ids)}

from fastembed import TextEmbedding
emb = TextEmbedding()

mid_queries = []
for t, cid, c in rows:
    if cid not in vec or len(c) < 2000:
        continue
    s = int(len(c) * 0.55)
    mid_queries.append((cid, c[s:s+200]))

print(f"\nmid-text query test: {len(mid_queries)} rows (len>=2000 with vector)", flush=True)
res = []
for cid, q in mid_queries:
    qv = np.asarray(next(emb.embed([q])), dtype=np.float32)
    qv = qv / (np.linalg.norm(qv) + 1e-9)
    sims = V @ qv
    order = np.argsort(-sims)
    rank = int(np.where(order == id2i[cid])[0][0]) + 1
    res.append((rank, len(rows and [r for r in rows if r[1]==cid][0][2]), cid))
res.sort()
top = [r for r in res if r[0] <= 30]
print(f"mid-query self rank <=30: {len(top)}/{len(res)}")
print(f"mid-query self rank <=100: {len([r for r in res if r[0]<=100])}/{len(res)}")
med = sorted(r[0] for r in res)[len(res)//2]
print(f"median self rank: {med}")

# ---- 4) head-120 excerpt distinctiveness ------------------------------------
# The excerpt that prefetch/gate would actually see: does it contain a term that
# is distinctive enough to match a query? crude: count unique syllables in head-120
# that appear in >50% of the pool (stopwords-ish) -> distinctive ratio.
print("\nexcerpt-120 distinctiveness (unique token ratio):")
for t, cid, c in sorted(rows, key=lambda r: -len(r[2]))[:10]:
    h = c[:120]
    toks = re.findall(r'[가-힣A-Za-z0-9]{2,}', h)
    print(f"  {len(c):>7,}  tokens={len(toks):>3}  head={c[:100]!r}")

conn.close()
print("\nDONE")