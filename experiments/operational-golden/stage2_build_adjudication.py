"""Stage-2c: build the final adjudication set for the user.

From clean pairs, keep: for each distinct user_query the single best row
(largest overlap), and rows that appear as best for at least one query.
Target ~25-35 pairs. Emits an HTML sheet (native radio — verified pattern)
with query + row head + row mid + the exact mid-100 overlap snippet so the
user can judge whether the row really contains the answer.

Also emits adjudication seeds JSON (verdict=null) for the next stage.
"""
import sqlite3, re, json, os, html

OUT_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stage2_adjudicate.html")
OUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stage2_adjudicate.json")
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stage2_real_gold_pairs_clean.json")

pairs = json.load(open(SRC, encoding="utf-8"))
# keep best per query (largest ov, shortest row for readability)
best_per_query = {}
for p in pairs:
    q = p["user_query"]
    if q not in best_per_query or (p["ov"], -p["row_len"]) > (best_per_query[q]["ov"], -best_per_query[q]["row_len"]):
        best_per_query[q] = p
sel = sorted(best_per_query.values(), key=lambda p: -p["ov"])
print(f"best-per-query pairs: {len(sel)}")

# also pull exact content for display
DB = r"C:/Users/mandu/AppData/Local/hermes/mnemosyne/data/mnemosyne.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
def get_row(t, rid):
    r = conn.execute(f"SELECT content FROM {t} WHERE id=?", (rid,)).fetchone()
    return r["content"] if r else ""

def body(c):
    m = re.match(r"^(\[[^\]]*\]\s*)?", c)
    return c[m.end():]

items = []
for p in sel:
    c = get_row(p["table"], p["row_id"])
    if not c:
        continue
    b = body(c)
    n = len(b)
    mid_start = n // 2
    mid = b[mid_start:mid_start + 300]
    # exact overlap snippet: find first overlap token in mid zone
    items.append({**p, "head": b[:220], "mid": mid, "mid_start": mid_start, "n": n})

json.dump([{k: v for k, v in it.items() if k in ("row_id","row_len","table","session","user_query","q_ts","ov","overlap")} | {"verdict": None} for it in items],
          open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"adjudication items: {len(items)}")

# ---- HTML ----
parts = ["<!DOCTYPE html><html lang='ko'><head><meta charset='utf-8'>",
"<meta name='viewport' content='width=device-width, initial-scale=1'><title>stage2 판정</title><style>",
"body{font-family:-apple-system,'Malgun Gothic',sans-serif;max-width:920px;margin:16px auto;padding:0 12px;color:#111}",
".banner{background:#fff8e1;border:1px solid #f0c36d;padding:10px 12px;border-radius:8px;margin-bottom:14px;font-size:14px}",
".q{background:#eef4ff;padding:8px 12px;border-radius:8px;font-weight:600;margin-top:20px}",
".rowbox{border:1px solid #ccc;border-radius:8px;padding:8px 12px;margin:6px 0}",
".head,.mid{font-size:13px;white-space:pre-wrap;word-break:break-all}",  
".head{color:#666;border-left:3px solid #9cf;padding-left:6px}",
".mid{color:#222;background:#f7f7f7;padding:5px 8px;border-radius:4px;border-left:3px solid #fc9}",
".tag{font-size:11px;color:#888}",
"label{display:inline-block;margin:4px 8px 0 0;padding:4px 12px;border:1px solid #888;border-radius:16px;cursor:pointer;font-size:14px}",
"input[type=radio]{margin-right:3px}", 
".ct{background:#e8f5e9;padding:4px 8px;border-radius:4px;font-size:12px;color:#1b5e20}",
"</style></head><body>",
"<div class='banner'><b>판정 기준</b><br>",
"<b>VALID</b>: 이 장문 메모리가 쿼리가 묻는 답/사실/결과를 <b>실제로 포함</b>함 (의역·본문 중간도 OK — '답이 어딘가 있다')<br>",
"<b>PLAUS</b>: 주제·키워드는 겹치지만 그 특정 답은 없음 (배경·관련 얘기만)<br>",
"<b>IRREL</b>: 주제조차 무관<br>",
"하고 export JSON 버튼으로 저장하세요. 모든 항목 판정 후 저장해 주세요.</div>"]

import datetime
def fmt_ts(ts):
    try:
        return datetime.datetime.fromtimestamp(float(ts)).strftime("%m-%d %H:%M")
    except Exception:
        return str(ts)[:16]

for i, it in enumerate(items):
    parts.append(f"<div class='q'>Q{i+1}. {html.escape(it['user_query'])} <span class='tag'>({fmt_ts(it['q_ts'])})</span></div>")
    parts.append(f"<div class='rowbox'>")
    parts.append(f"<div class='tag'>[{it['table']}] id={it['row_id'][:16]} len={it['row_len']} ov={it['ov']} tokens: {html.escape(' '.join(it['overlap'][:10]))}</div>")
    parts.append(f"<div class='head'><b>head</b>: {html.escape(it['head'])}</div>")
    parts.append(f"<div class='mid'><b>mid({it['mid_start']}자 지점)</b>: {html.escape(it['mid'])}</div>")
    parts.append(f"<div><label><input type='radio' name='v{i}' value='VALID'> VALID</label>"
                 f"<label><input type='radio' name='v{i}' value='PLAUS'> PLAUS</label>"
                 f"<label><input type='radio' name='v{i}' value='IRREL'> IRREL</label></div>")
    parts.append("</div>")

parts.append("""
<div style="margin:26px 0"><button onclick="exportJSON()" style="padding:10px 22px;font-size:16px">export JSON</button></div>
<script>
function exportJSON(){
  const n=document.querySelectorAll('.q').length; const out=[];
  for(let i=0;i<n;i++){
    const sel=document.querySelector('input[name="v'+i+'"]:checked');
    out.push({idx:i, verdict: sel?sel.value:null});
  }
  const blob=new Blob([JSON.stringify(out,null,1)],{type:'application/json'});
  const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='stage2_verdicts.json'; a.click();
}
</script></body></html>""")
open(OUT_HTML, "w", encoding="utf-8").write("\n".join(parts))
print("sheet:", OUT_HTML)