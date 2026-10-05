"""Stage-2b: real-usage gold pairs — CLEANED. Only genuine user questions.

Filter rules for the 'user query' side:
- exclude messages that are file/url attachments or document drops:
  '@file:', '@url:', '[The user sent', 'Attached Context', '---'
- exclude system/mechanical: '[ASYNC', '[IMPORTANT', 'Background process'
- exclude very long evidence dumps (assistant transcript re-posts)
- keep only queries with >=2 tokens where the query is a plausible recall request

Then (query, long row) pair requires overlap>=2, and we ALSO require the row
came from a session whose transcript contains the query (real provenance).
"""
import sqlite3, re, json, os

DB = r"C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
STATE = r"C:/Users/mandu/AppData/Local/hermes/state.db"
OUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stage2_real_gold_pairs_clean.json")

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

def is_clean_query(q):
    if len(q) < 8 or len(q) > 1200:
        return False
    bl = ["@file:", "@url:", "[The user sent", "Attached Context", "[ASYNC",
          "[IMPORTANT", "Background process", "---", "# ", "```"]
    if any(b in q for b in bl):
        return False
    t = toks(q)
    if len(t) < 2:
        return False
    return True

st = sqlite3.connect(f"file:{STATE}?mode=ro", uri=True)
st.row_factory = sqlite3.Row
sess2msgs = {}
for r in st.execute("SELECT session_id, content, timestamp FROM messages WHERE role='user' AND content IS NOT NULL"):
    sess2msgs.setdefault(r["session_id"], []).append((r["timestamp"], r["content"]))

pairs = []
for t, rid, c, sid in long_rows:
    key = sid[len("hermes_"):] if sid and sid.startswith("hermes_") else sid
    msgs = sess2msgs.get(key, []) or sess2msgs.get(sid, [])
    if not msgs:
        continue
    bt = toks(body(c))
    for ts, q in msgs:
        q = (q or "").strip()
        if not is_clean_query(q):
            continue
        qt = toks(q)
        ov = qt & bt
        if len(ov) >= 2:
            pairs.append({"row_id": rid, "row_len": len(c), "table": t, "session": sid,
                          "user_query": q, "q_ts": ts, "overlap": sorted(ov)[:12], "ov": len(ov)})

# dedupe: keep best (query,row) once
seen = set(); uniq = []
for p in sorted(pairs, key=lambda p: -p["ov"]):
    k = (p["user_query"], p["row_id"])
    if k not in seen:
        seen.add(k); uniq.append(p)
pairs = uniq
pairs.sort(key=lambda p: -p["ov"])
print(f"clean pairs: {len(pairs)}")
json.dump(pairs, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("saved:", OUT_JSON)
for i, p in enumerate(pairs[:30]):
    print(f"\n[{i}] ov={p['ov']} len={p['row_len']} {p['table']} {p['row_id'][:16]}")
    print(f"    Q: {p['user_query'][:110]!r}")