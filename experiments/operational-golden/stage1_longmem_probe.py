"""Stage-1 probe: 0-call analysis of long-memory problem for jev chunking pilot.

1) Full DB distribution: content length of every row in working_memory/episodic_memory,
   classified by meta-prefix ([USER]/[ASSISTANT]/[codex]/[opencode] or plain).
2) op-90 golden: gold memory ids from golden_eval_v3.json -> real DB full content,
   length distribution, and how many exceed gate truncation windows
   (800 fulltext gate / 120 excerpt / 6000 prefetch).
3) Vector-recall simulation (local embedding, 0 JEV calls): does chunking long rows
   recover gold queries that whole-row embedding misses?

Read-only on the live DB. No JEV calls.
"""
import sqlite3, json, collections, re, sys, os

DB = r"C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
GOLD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "golden_eval_v3.json")

META_PREFIX = re.compile(r"^\[(USER|ASSISTANT|codex|opencode|SYSTEM|TOOL)[^\]]*\]")

def row_len_bucket(n):
    if n <= 800: return "<=800"
    if n <= 1350: return "801-1350"
    if n <= 3000: return "1351-3000"
    if n <= 10000: return "3001-10000"
    return ">10000"

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
cur = conn.cursor()

# ---- 1) DB distribution -------------------------------------------------
print("=" * 70)
print("1) DB full distribution (working + episodic)")
print("=" * 70)
total = collections.Counter()
by_prefix = collections.Counter()
lens = []
for t in ("working_memory", "episodic_memory"):
    for (cid, content,) in cur.execute(f"SELECT id, content FROM {t}"):
        if not content:
            continue
        n = len(content)
        lens.append((t, cid, content, n))
        total[row_len_bucket(n)] += 1
        m = META_PREFIX.match(content)
        by_prefix[(m.group(1) if m else "plain")] += 1

print("rows:", len(lens))
print("bucket:", dict(total))
print("prefix:", dict(by_prefix))

# long rows detail (>1350)
long_rows = [r for r in lens if r[3] > 1350]
print(f"\nrows >1350: {len(long_rows)}")
for t, cid, content, n in sorted(long_rows, key=lambda x: -x[3])[:15]:
    m = META_PREFIX.match(content)
    print(f"  [{t}] {n:>7,} chars  prefix={m.group(1) if m else 'plain'}  id={cid[:16]}  head={content[:60]!r}")

# ---- 2) op-90 gold lengths ---------------------------------------------
print("\n" + "=" * 70)
print("2) op-90 golden: gold memory real lengths (DB full content)")
print("=" * 70)
gold = json.load(open(GOLD, encoding="utf-8"))
# filter to gold rows (exclude noans)
gold_ids = [r["gold"] for r in gold if r.get("gold")]
print("gold queries:", len(gold_ids), "unique ids:", len(set(gold_ids)))

id2content = {}
for t in ("working_memory", "episodic_memory"):
    for (cid, content,) in cur.execute(f"SELECT id, content FROM {t}"):
        id2content[cid] = content

missing = [g for g in gold_ids if g not in id2content]
print("gold ids missing from DB:", len(missing), missing[:10])

gold_lens = []
for g in set(gold_ids):
    c = id2content.get(g, "")
    gold_lens.append((g, len(c)))
glen = [n for _, n in gold_lens]
glen_sorted = sorted(glen)
print(f"gold mem len: min {glen_sorted[0]} p50 {glen_sorted[len(glen_sorted)//2]} p90 {glen_sorted[int(len(glen_sorted)*0.9)]} max {glen_sorted[-1]}")
over = [(g, n) for g, n in gold_lens if n > 800]
print(f"gold >800: {len(over)}")
for g, n in sorted(over, key=lambda x: -x[1]):
    c = id2content[g]
    m = META_PREFIX.match(c)
    print(f"  {n:>7,} chars  prefix={m.group(1) if m else 'plain'}  id={g[:16]}  head={c[:70]!r}")
gt1350 = [(g, n) for g, n in gold_lens if n > 1350]
gt10000 = [(g, n) for g, n in gold_lens if n > 10000]
print(f"gold >1350: {len(gt1350)}   gold >10000: {len(gt10000)}")

# ---- 3) missing gold -> check via exp7h raw 'full' as fallback ---------
print("\n" + "=" * 70)
print("3) fallback: exp7h raw full (800 capped) available for those gold?")
print("=" * 70)
h = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "exp7h_op_gate_raw.json"), encoding="utf-8"))
for r in h["records"]:
    if r["qid"] == r["cand_id"]:
        pass  # candidate IS the gold memory itself (gold_rank==1)
print("exp7h records where cand==gold (qid==cand_id):",
      len([r for r in h["records"] if r["qid"] == r["cand_id"]]), "/", len(h["records"]))

conn.close()
print("\nDONE")