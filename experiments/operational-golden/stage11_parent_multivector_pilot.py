"""Stage-11: parent-level multi-vector / late chunk retrieval pilot.

Question (c-ai #8 + stage10b finding): if long rows keep a SINGLE memory row
but we ALSO index their 800-char chunks as sub-vectors (sidecar), does the
real-usage gold 19 recall improve — WITHOUT the pool loss of independent chunk
rows?

Design (0 JEV, scratch, correct model via beam embedder):
1. For each of the 19 gold parents: build 800-char chunks (same splitter).
2. Simulate a sidecar chunk-vector index: query embedding vs ALL chunk embeddings
   (of the 48 long plain rows) -> top-k chunks -> map to parent ids (collapse).
3. Measure:
   A) parent recovery: how many of 19 gold parents are found in top-N parents
      via chunk-vector lane ALONE (compare: whole-row vec lane top-N).
   B) integrated pool: current pipeline pool (FTS+vec+imp+graph) + chunk-lane
      candidates, deduped — does gold parent enter pool when it wasn't before?
   C) the "best-chunk span" localization: for gold parents found by chunk lane,
      does the best chunk cover the answer span (mid 40-60%)?

Correct model = mnemosyne.core.embeddings (sitecustomize pins bekko-a8m).
"""
import os, re, sqlite3, json, sys
import numpy as np
sys.path.insert(0, r"C:/Users/mandu/hermes-made/jev-memory-middleware")
os.environ.setdefault("MNEMOSYNE_EMBEDDING_MODEL", "bench/bekko-a8m")

import mnemosyne.core.beam as beam_mod
emb = beam_mod._embeddings

import sqlite_vec
DB = r"C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
conn.enable_load_extension(True)
sqlite_vec.load(conn)

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

# ---- long plain rows -------------------------------------------------------
long_rows = {}
for t in ("working_memory", "episodic_memory"):
    for r in conn.execute(f"SELECT id, content FROM {t}"):
        c = r["content"]
        if c and len(c) >= 2000 and cls(c) == 'plain':
            long_rows[r["id"]] = body(c)
print(f"long plain rows: {len(long_rows)}")

# chunk index (sidecar simulation): all chunks of all long rows
chunk_index = []   # (parent_id, chunk_idx, text, mid_start, mid_end)
for pid, c in long_rows.items():
    chs = chunks_of(c)
    # track span of each chunk in the body
    pos = 0
    for i, ch in enumerate(chs):
        start = pos
        pos += len(ch)
        chunk_index.append((pid, i, ch, start, pos))
print(f"total chunks (sidecar): {len(chunk_index)}")

# embed all chunks + queries
chunk_texts = [ci[2] for ci in chunk_index]
CH = []
B = 32
for i in range(0, len(chunk_texts), B):
    batch = chunk_texts[i:i+B]
    CH.extend(np.asarray(v, dtype=np.float32) for v in emb.embed(batch))
CH = np.stack(CH)
CH = CH / (np.linalg.norm(CH, axis=1, keepdims=True) + 1e-9)
print(f"chunk embeddings: {CH.shape}")

# ---- gold 19 ---------------------------------------------------------------
gold = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "data", "stage2_final_gold.json"), encoding="utf-8"))
print(f"gold: {len(gold)}")

def query_emb(q):
    return np.asarray(emb.embed([q])[0], dtype=np.float32)

# A) chunk-lane parent recovery (top-N parents via max chunk sim)
print("\n[A] chunk-lane ALONE parent recovery (top-N parents):")
results = []
for g in gold:
    qv = query_emb(g["query"])
    qv = qv / (np.linalg.norm(qv) + 1e-9)
    sims = CH @ qv  # (nchunks,)
    # collapse to parent: max sim per parent
    parent_sim = {}
    for si, s in enumerate(sims):
        pid = chunk_index[si][0]
        parent_sim[pid] = max(parent_sim.get(pid, -1), float(s))
    order = sorted(parent_sim.items(), key=lambda x: -x[1])
    rank = next((i+1 for i, (pid, _) in enumerate(order) if pid == g["row_id"]), None)
    best_chunk = chunk_index[int(sims.argmax())]
    # best chunk span vs mid
    n = len(long_rows[g["row_id"]])
    m0, m1 = int(n*0.4), int(n*0.6)
    ch_start, ch_end = best_chunk[3], best_chunk[4]
    overlaps_mid = ch_start < m1 and ch_end > m0
    results.append((rank, g["row_id"][:14], n, ch_start, ch_end, m0, m1, overlaps_mid))

for N in (5, 10, 15, 19):
    print(f"  top-{N}: {sum(1 for r in results if r[0] is not None and r[0] <= N)}/{len(results)}")
print("  per-row (rank, best-chunk span vs mid 40-60%):")
for r in results:
    mark = "MID-OK" if r[7] else ("IN-MID?" if r[0] and r[0] <= 10 else "")
    print(f"  rank={r[0]} {r[1]} len={r[2]} chunk[{r[3]}-{r[4]}] mid[{r[5]}-{r[6]}] {mark}")

# B) whole-row vec lane top-N (baseline comparison)
print("\n[B] whole-row vec lane ALONE (baseline):")
# stored whole vectors
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
whole_ranks = []
for g in gold:
    if g["row_id"] not in vec:
        whole_ranks.append(None); continue
    qv = query_emb(g["query"]); qv = qv / (np.linalg.norm(qv)+1e-9)
    sims = V @ qv
    order = np.argsort(-sims)
    wr = int(np.where(order == id2i[g["row_id"]])[0][0]) + 1
    whole_ranks.append(wr)
print(f"  whole top-5: {sum(1 for r in whole_ranks if r and r<=5)}/19  top-10: {sum(1 for r in whole_ranks if r and r<=10)}/19  top-20: {sum(1 for r in whole_ranks if r and r<=20)}/19")

conn.close()
print("\nDONE")