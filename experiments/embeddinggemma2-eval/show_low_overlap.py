"""저오버랩(의역) 쿼리 18건 상세 출력."""
import os, json, re, sqlite3

B = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20261006-embedgemma2")
B93 = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20260930")
REPO = r"C:/Users/mandu/hermes-made/jev-memory-middleware/experiments/operational-golden"

conn = sqlite3.connect(f"file:{os.path.join(B93, 'data', 'mnemosyne.db')}?mode=ro", uri=True)
rows = conn.execute(
    "SELECT id, content FROM working_memory WHERE content IS NOT NULL AND length(content) > 0 ORDER BY id"
).fetchall()
conn.close()
id_text = {r[0]: r[1] for r in rows}

raw = json.load(open(os.path.join(REPO, "data", "stage54_op90_regress.json"), encoding="utf-8"))
items = [(r["q"], r["gold"]) for r in raw["base"] if r["gold"] in id_text]
per90 = json.load(open(os.path.join(B, "op90_result.json"), encoding="utf-8"))["per_query"]
q8res = json.load(open(os.path.join(B, "q8_bench_result.json"), encoding="utf-8"))["per_query"]

def bigrams(s):
    s = re.sub(r"\s+", "", s.lower())
    return set(s[i:i+2] for i in range(len(s)-1))

low = []
for i, (q, gid) in enumerate(items):
    gb = bigrams(id_text[gid]); qb = bigrams(q)
    ratio = len(qb & gb) / len(qb) if qb else 0
    if ratio < 0.3:
        low.append((ratio, q, per90[str(i)]["bekko"], q8res[i]["q8"], per90[str(i)]["gemma2"]))

low.sort(key=lambda x: x[0])
print(f"저오버랩 {len(low)}건:")
for ratio, q, rb, r8, r4 in low:
    win = "bekko" if rb <= 1 else ("q8" if r8 <= 1 else "못 찾음")
    print(f"  r={ratio:.2f} bekko={rb:>3} q8={r8:>3} q4={r4:>3} {win:8s} | {q[:50]}")