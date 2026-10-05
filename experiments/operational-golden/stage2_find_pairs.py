"""Stage-2 prep: find (real query, long row) candidate pairs from query_log.

For each real user query in query_log (core_state.db) and each plain long row
(len>=2000), compute lexical overlap of query tokens against the row's body
(body = strip meta prefix and first 200 chars; also search whole text).
Outputs candidate pairs with overlap counts for human gold adjudication.
"""
import sqlite3, re, json, os

CORE = r"C:/Users/mandu/AppData/Local/jev-mem/core_state.db"
DB = r"C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

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
        if c and len(c) >= 2000 and cls(c) == 'plain':
            long_rows.append((t, r["id"], c))
print(f"long plain rows: {len(long_rows)}")

def toks(text):
    # 한글 2+ 블록 + 영어 단어
    t = set(re.findall(r"[가-힣]{2,}", text))
    t |= set(re.findall(r"[A-Za-z][A-Za-z0-9_.-]{2,}", text))
    return t

def body(c):
    # strip [ASSISTANT]/[USER]/[conversation] meta prefix
    m = re.match(r"^(\[[^\]]*\]\s*)?", c)
    return c[m.end():]

# query_log
qc = sqlite3.connect(CORE)
qc.row_factory = sqlite3.Row
qrows = qc.execute("SELECT query, received_at, pool_n FROM query_log ORDER BY received_at").fetchall()
print(f"query_log rows: {len(qrows)}")

# skip background-process mechanical messages
def is_mech(q):
    return (q or "").startswith("[IMPORTANT: Background process") or (q or "").startswith("[IMPORTANT:")

cands = []  # (query, qid, table, rowid, overlap, len)
for qi, qr in enumerate(qrows):
    q = (qr["query"] or "").strip()
    if not q or is_mech(q):
        continue
    qt = toks(q)
    if len(qt) < 2:
        continue
    # exclude stopword-ish queries (pure greeting etc.)
    for (t, rid, c) in long_rows:
        b = body(c)
        bt = toks(b)
        ov = qt & bt
        if len(ov) >= 2:
            cands.append((q, qi, t, rid, len(ov), len(c), qr["pool_n"]))

cands.sort(key=lambda x: -x[4])
print(f"\ncandidate pairs (overlap>=2): {len(cands)}")
print("top 45:")
seen = set()
for q, qi, t, rid, ov, ln, pn in cands[:45]:
    print(f"  [{ov}] len={ln:>5} pool={pn} | {q[:60]!r}")
    print(f"        -> {t} {rid[:16]} {long_rows[[r[2] for r in long_rows].index(rid)][2][:90]!r}" if False else f"        -> {t} {rid[:16]}")

# unique queries with >=2 overlaps
uq = {}
for q, qi, t, rid, ov, ln, pn in cands:
    uq.setdefault(q, []).append((t, rid, ov, ln))
print(f"\nunique queries with cands: {len(uq)}")
for q, lst in sorted(uq.items(), key=lambda kv: -max(x[2] for x in kv[1]))[:30]:
    print(f"  max_ov={max(x[2] for x in lst)} n={len(lst):>2} | {q[:70]!r}")

conn.close(); qc.close()