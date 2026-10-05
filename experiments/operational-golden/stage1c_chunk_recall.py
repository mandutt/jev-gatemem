"""Stage-1c probe: rule-based 800-char chunking — vector recall recovery test.

0 JEV calls, DB read-only. Local bekko-a8m embedding.

Question: if long plain rows were stored as 800-char chunks (each with its own
vector) instead of one whole-row vector, would mid-text queries recover them?

Test on the same 41 rows (len>=2000, vector present) and the same mid-query
(200 chars from 55% span) as stage1b:
  whole-rank: stored whole-row vector cosine rank (baseline, already measured)
  chunk-rank: 800-char rule chunks, max cosine over chunks, rank among full pool
  gate-sim:   does the mid-query pass the lexical gate (overlap>=2, coverage>=0.30)
              against the chunk containing the answer? (proxy for vec<=2 exemption
              relevance — but here we measure pool-entry, not gate)

Also: chunk-level excerpt — what would the prefetch/gate see per chunk vs whole.
"""
import sqlite3, json, re, collections
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
        if c and len(c) >= 2000 and cls(c) == 'plain':
            rows.append((t, cid, c))
print(f"plain long rows len>=2000: {len(rows)}", flush=True)

# stored vectors
vec = {}
for mid, ej in cur.execute("SELECT memory_id, embedding_json FROM memory_embeddings"):
    if ej:
        try: vec[mid] = np.array(json.loads(ej), dtype=np.float32)
        except Exception: pass
ids = [cid for _, cid, _ in rows if cid in vec]
V_all = np.stack([vec[i] for i in ids if vec.get(i) is not None])  # pool = these long rows only? no — pool must be full DB
# full pool: all vectors
all_ids = list(vec.keys())
V = np.stack([vec[i] for i in all_ids])
V = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)
id2i = {i: k for k, i in enumerate(all_ids)}

from fastembed import TextEmbedding
emb = TextEmbedding()

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

# tokenize for lexical gate (syllable-level, mimicking _tokenize)
def toks(text):
    return re.findall(r'[가-힣A-Za-z0-9]+', text)

results = []
for t, cid, c in rows:
    if cid not in vec: continue
    q = c[int(len(c)*0.55): int(len(c)*0.55)+200]
    qv = np.asarray(next(emb.embed([q])), dtype=np.float32)
    qv = qv / (np.linalg.norm(qv) + 1e-9)
    # whole-rank
    sims = V @ qv
    order = np.argsort(-sims)
    wr = int(np.where(order == id2i[cid])[0][0]) + 1
    # chunk-rank
    chs = chunks_of(c)
    cvs = []
    for ch in chs:
        cv = np.asarray(next(emb.embed([ch])), dtype=np.float32)
        cvs.append(cv / (np.linalg.norm(cv) + 1e-9))
    C = np.stack(cvs)
    cs = C @ V.T
    chunk_scores = cs.max(axis=0)
    order2 = np.argsort(-chunk_scores)
    cr = int(np.where(order2 == id2i[cid])[0][0]) + 1
    # lexical gate check: query tokens vs the BEST chunk (the one with max sim)
    best_chunk = chs[int(cs.max(axis=1).argmax())]
    qt = set(toks(q))
    bt = set(toks(best_chunk))
    overlap = len(qt & bt)
    coverage = overlap / len(qt) if qt else 0
    gate_pass = overlap >= 2 and coverage >= 0.30
    results.append((wr, cr, gate_pass, len(c), len(chs), cid))

results.sort(key=lambda r: r[0])
print(f"\ntested: {len(results)} rows")
for N in (10, 30, 100, 500):
    print(f"  top-{N}: whole {sum(1 for r in results if r[0]<=N)/len(results):.3f}   chunk {sum(1 for r in results if r[1]<=N)/len(results):.3f}")
med_w = sorted(r[0] for r in results)[len(results)//2]
med_c = sorted(r[1] for r in results)[len(results)//2]
print(f"  median: whole {med_w}  chunk {med_c}")
lifted = [(w,c) for w,c,gp,n,ch,cid in results if c < w]
hurt = [(w,c) for w,c,gp,n,ch,cid in results if c > w and w <= 100]
print(f"  lifted: {len(lifted)}  hurt (was<=100, pushed out): {len(hurt)}")
print(f"  gate_pass (query vs best chunk, overlap>=2 & cov>=0.30): {sum(1 for r in results if r[2])}/{len(results)}")
print("\ntop movers:")
for w, c, gp, n, ch, cid in results[:15]:
    arrow = 'UP' if c < w else ('dn' if c > w else '--')
    print(f"  {arrow} whole {w:>5} -> chunk {c:>5}  gate={int(gp)}  len={n:>5} chunks={ch}  {cid[:14]}")
conn.close()
print("\nDONE")