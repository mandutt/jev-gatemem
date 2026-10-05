"""Stage-2: build user-adjudication sheet from real query_log + long rows.

For each query (non-mechanical, >=2 tokens) and each long plain row, compute
lexical overlap (query tokens vs row body). Keep top pairs per query, produce a
readable HTML sheet with the query, the row head+mid excerpt, and Y/N/M buttons.
The user marks VALID (row actually answers the query) / PLAUS (topic only) /
IRREL (no relation) — used later as gold for scratch pipeline verification.

Also emits pairs.json (machine-readable).
"""
import sqlite3, re, json, html, os, datetime

CORE = r"C:/Users/mandu/AppData/Local/jev-mem/core_state.db"
DB = r"C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
OUT_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stage2_gold_sheet.html")
OUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stage2_pairs.json")

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

def toks(text):
    t = set(re.findall(r"[가-힣]{2,}", text))
    t |= set(re.findall(r"[A-Za-z][A-Za-z0-9_.-]{2,}", text))
    return t

def body(c):
    m = re.match(r"^(\[[^\]]*\]\s*)?", c)
    return c[m.end():]

qc = sqlite3.connect(CORE)
qc.row_factory = sqlite3.Row
qrows = qc.execute("SELECT query, received_at, pool_n FROM query_log ORDER BY received_at").fetchall()

def is_mech(q):
    return (q or "").startswith("[IMPORTANT:") or (q or "").startswith("[IMPORTANT:")

# per-query best pairs
pairs = []
for qi, qr in enumerate(qrows):
    q = (qr["query"] or "").strip()
    if not q or is_mech(q) or len(toks(q)) < 2:
        continue
    best = []
    for (t, rid, c) in long_rows:
        b = body(c)
        ov = toks(q) & toks(b)
        if len(ov) >= 2:
            best.append((len(ov), t, rid, len(c), ov))
    if not best:
        continue
    best.sort(key=lambda x: -x[0])
    # keep top 3 per query
    for ov, t, rid, ln, ovset in best[:3]:
        pairs.append({"query": q, "q_received": qr["received_at"], "table": t, "row_id": rid,
                      "row_len": ln, "overlap": sorted(ovset), "ov": ov})

json.dump(pairs, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"pairs: {len(pairs)} unique queries with pairs: {len(set(p['query'] for p in pairs))}")

# build HTML (native radio+label — the only touch-verified pattern)
def excerpt(c, n=220):
    b = body(c)
    mid = b[len(b)//2: len(b)//2 + n]
    return html.escape(b[:n]), html.escape(mid)

html_parts = []
html_parts.append("""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>stage2 장문-쿼리 gold 판정</title>
<style>
body{font-family:-apple-system,'Malgun Gothic',sans-serif;max-width:900px;margin:16px auto;padding:0 12px;background:#fff;color:#111}
.banner{background:#fff8e1;border:1px solid #f0c36d;padding:10px 12px;border-radius:8px;margin-bottom:14px;font-size:14px}
.q{background:#eef4ff;padding:8px 12px;border-radius:8px;font-weight:600;margin-top:18px}
.rowbox{border:1px solid #ccc;border-radius:8px;padding:8px 12px;margin:6px 0}
.head{color:#555;font-size:13px}
.mid{color:#333;font-size:13px;background:#f7f7f7;padding:4px 6px;border-radius:4px}
.tag{font-size:12px;color:#888}
label{display:inline-block;margin:4px 8px 0 0;padding:4px 10px;border:1px solid #999;border-radius:16px;cursor:pointer;font-size:14px}
input[type=radio]{margin-right:4px}
.ov{color:#0a7d2c;font-size:12px}
</style></head><body>
<div class="banner"><b>판정 기준</b> — VALID: 이 장문 메모리가 쿼리가 묻는 답/사실을 <b>실제로 포함</b>함 (의역·중간 위치도 OK) /
PLAUS: 주제·키워드는 겹치지만 그 특정 답은 없음 / IRREL: 무관. &nbsp;<b>export</b> 버튼으로 JSON 저장.</div>
""")

for i, p in enumerate(pairs):
    c = next((cc for (tt, rid, cc) in long_rows if (tt == p["table"] and rid == p["row_id"])), "")
    head, mid = excerpt(c)
    html_parts.append(f"""
<div class="q">Q{i+1}. {html.escape(p['query'])} <span class="tag">({p['q_received'][:16]})</span></div>
<div class="rowbox">
  <div class="tag">[{p['table']}] id={p['row_id'][:16]} len={p['row_len']} overlap={p['ov']} <span class="ov">{' '.join(p['overlap'][:8])}</span></div>
  <div class="head"><b>head:</b> {head}</div>
  <div class="mid"><b>mid(50%):</b> {mid}</div>
  <div>
    <label><input type="radio" name="v{i}" value="VALID"> VALID</label>
    <label><input type="radio" name="v{i}" value="PLAUS"> PLAUS</label>
    <label><input type="radio" name="v{i}" value="IRREL"> IRREL</label>
  </div>
</div>""")

html_parts.append("""
<div style="margin:24px 0">
  <button onclick="exportJSON()" style="padding:8px 18px;font-size:15px">export JSON</button>
</div>
<script>
function exportJSON(){
  const out=[]; const n=document.querySelectorAll('.q').length;
  for(let i=0;i<n;i++){
    const sel=document.querySelector('input[name="v'+i+'"]:checked');
    out.push({idx:i, verdict: sel? sel.value : null});
  }
  const blob=new Blob([JSON.stringify(out,null,1)],{type:'application/json'});
  const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
  a.download='stage2_verdicts.json'; a.click();
}
</script>
</body></html>""")

open(OUT_HTML, "w", encoding="utf-8").write("\n".join(html_parts))
print("sheet:", OUT_HTML)
conn.close(); qc.close()