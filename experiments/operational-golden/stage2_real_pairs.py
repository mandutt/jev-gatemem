"""Stage-2: build real-usage gold pairs — (session user query, long row from that
session) by lexical overlap. The query is a REAL user utterance from the same
session that produced the long row, so the pair is a genuine recall target.

For each long plain row: find its session_id in mnemosyne.db, map to state.db
messages (session_id = row session id with 'hermes_' prefix stripped), take user
messages, compute token overlap with row body. Keep pairs with overlap>=3 and
also emit row head for eyeballing.
"""
import sqlite3, re, json, os

DB = r"C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
STATE = r"C:/Users/mandu/AppData/Local/hermes/state.db"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT_JSON = os.path.join(OUT_DIR, "stage2_real_gold_pairs.json")

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
    for r in conn.execute(f"SELECT id, content, session_id FROM {t}"):
        c = r["content"]
        if c and len(c) >= 2000 and cls(c) == 'plain':
            long_rows.append((t, r["id"], c, r["session_id"]))
print(f"long plain rows: {len(long_rows)}")

def toks(text):
    t = set(re.findall(r"[가-힣]{2,}", text))
    t |= set(re.findall(r"[A-Za-z][A-Za-z0-9_.-]{2,}", text))
    return t

def body(c):
    m = re.match(r"^(\[[^\]]*\]\s*)?", c)
    return c[m.end():]

# state.db messages by session_id
st = sqlite3.connect(f"file:{STATE}?mode=ro", uri=True)
st.row_factory = sqlite3.Row
sess2msgs = {}
for r in st.execute("SELECT session_id, content, timestamp FROM messages WHERE role='user' AND content IS NOT NULL"):
    sess2msgs.setdefault(r["session_id"], []).append((r["timestamp"], r["content"]))

pairs = []
for t, rid, c, sid in long_rows:
    # state.db session id = row session_id minus 'hermes_' prefix (e.g. hermes_20261003_112034_65dc24)
    key = sid[len("hermes_"):] if sid and sid.startswith("hermes_") else sid
    msgs = sess2msgs.get(key, [])
    if not msgs:
        # try the raw id too (episodic sometimes differ)
        msgs = sess2msgs.get(sid, [])
    if not msgs:
        continue
    bt = toks(body(c))
    for ts, q in msgs:
        q = (q or "").strip()
        if len(q) < 8 or q.startswith("[IMPORTANT:"):
            continue
        qt = toks(q)
        ov = qt & bt
        if len(ov) >= 3:
            pairs.append({"row_id": rid, "row_len": len(c), "table": t, "session": sid,
                          "user_query": q, "q_ts": ts, "overlap": sorted(ov), "ov": len(ov)})

pairs.sort(key=lambda p: -p["ov"])
print(f"gold pairs (overlap>=3): {len(pairs)}")
json.dump(pairs, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("saved:", OUT_JSON)

# preview top 25
for i, p in enumerate(pairs[:25]):
    print(f"\n[{i}] ov={p['ov']} len={p['row_len']} {p['table']} {p['row_id'][:16]}")
    print(f"    Q: {p['user_query'][:100]!r}")
    # row head
    rc = next((cc for (tt, rr, cc, ss) in long_rows if rr == p['row_id']), "")
    print(f"    R: {body(rc)[:100]!r}")
conn.close(); st.close()