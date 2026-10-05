"""Stage-2d: per-row adjudication sheet (48 rows -> 1 best query each).

For every long plain row pick its single best real user query (highest overlap).
Sheet asks TWO questions per item:
  Q-A: does the ROW (anywhere) contain the answer to the query?  VALID/PLAUS/IRREL
  Q-B: is the answer specifically located in the MID zone (middle ~40-60%)?  YES/NO
     (only meaningful if Q-A='VALID'; if answer is only in head/tail -> NO)
This directly tests the mid-answer scenario that stage1b showed collapses.
"""
import sqlite3, re, json, os, html, datetime

OUT_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stage2_row_adjudicate.html")
OUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stage2_row_adjudicate.json")
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stage2_real_gold_pairs_clean.json")

pairs = json.load(open(SRC, encoding="utf-8"))

# best query per ROW
best_per_row = {}
for p in pairs:
    rid = p["row_id"]
    if rid not in best_per_row or (p["ov"], -p["row_len"]) > (best_per_row[rid]["ov"], -best_per_row[rid]["row_len"]):
        best_per_row[rid] = p
sel = sorted(best_per_row.values(), key=lambda p: -p["ov"])
print(f"row-best pairs: {len(sel)}")

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
    m0, m1 = int(n * 0.40), int(n * 0.60)
    mid = b[m0:m1]
    head = b[:200]
    tail = b[-200:]
    items.append({**p, "head": head, "mid": mid, "mid_range": (m0, m1), "n": n,
                  "tail": tail, "v_row": None, "v_mid": None})

json.dump([{k: v for k, v in it.items() if k in ("row_id","row_len","table","session","user_query","ov","overlap","n")} | {"v_row": None, "v_mid": None}
           for it in items], open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"items: {len(items)}")

parts = ["<!DOCTYPE html><html lang='ko'><head><meta charset='utf-8'>",
"<meta name='viewport' content='width=device-width, initial-scale=1'><title>stage2 행 판정</title><style>",
"body{font-family:-apple-system,'Malgun Gothic',sans-serif;max-width:920px;margin:16px auto;padding:0 12px;color:#111}",
".banner{background:#fff8e1;border:1px solid #f0c36d;padding:10px 12px;border-radius:8px;margin-bottom:14px;font-size:14px}",
".q{background:#eef4ff;padding:8px 12px;border-radius:8px;font-weight:600;margin-top:20px}",
".rowbox{border:1px solid #ccc;border-radius:8px;padding:8px 12px;margin:6px 0}",
"pre{font-size:13px;white-space:pre-wrap;word-break:break-all;margin:4px 0}",
".head{color:#666;border-left:3px solid #9cf;padding-left:6px}",
".mid{color:#222;background:#fff8e1;padding:5px 8px;border-radius:4px;border-left:3px solid #f90}",
".tail{color:#777;border-left:3px solid #9c9;padding-left:6px}",
".tag{font-size:11px;color:#888}",
"label{display:inline-block;margin:4px 8px 0 0;padding:4px 12px;border:1px solid #888;border-radius:16px;cursor:pointer;font-size:14px}",
"input[type=radio]{margin-right:3px}",
".sec{font-size:12px;font-weight:700;color:#333;margin-top:8px}",
"</style></head><body>",
"<div class='banner'><b>판정 기준 (항목당 2문항)</b><br>",
"<b>A. 행 전체 기준</b> — VALID: 이 장문 메모리가 쿼리가 묻는 답/사실/결과를 실제로 포함함 (어디든, 의역도 OK) / PLAUS: 주제·키워드만 겹침, 그 답은 없음 / IRREL: 무관<br>",
"<b>B. mid 구역 기준</b> — A가 VALID일 때만 답: <b>YES</b>: 답이 주황(mid 40~60%) 구역 안에 있음 / <b>NO</b>: 답이 head 또는 tail에만 있음<br>",
"<span style='color:#b00'>이 실험의 핵심은 B=YES 항목</span> — mid에만 답이 있는 장문을 시스템이 찾는지가 목표.<br>",
"export JSON으로 저장하세요.</div>"]

import datetime
def fmt_ts(ts):
    try:
        return datetime.datetime.fromtimestamp(float(ts)).strftime("%m-%d %H:%M")
    except Exception:
        return str(ts)[:16]

for i, it in enumerate(items):
    parts.append(f"<div class='q'>Q{i+1}. {html.escape(it['user_query'])} <span class='tag'>({fmt_ts(it['q_ts'])})</span></div>")
    parts.append(f"<div class='rowbox'>")
    parts.append(f"<div class='tag'>[{it['table']}] id={it['row_id'][:16]} len={it['row_len']} ov={it['ov']} mid_range={it['mid_range'][0]}-{it['mid_range'][1]}자</div>")
    parts.append(f"<div class='sec'>HEAD (0-200)</div><pre class='head'>{html.escape(it['head'])}</pre>")
    parts.append(f"<div class='sec'>MID {it['mid_range'][0]}-{it['mid_range'][1]}자</div><pre class='mid'>{html.escape(it['mid'])}</pre>")
    parts.append(f"<div class='sec'>TAIL (-200)</div><pre class='tail'>{html.escape(it['tail'])}</pre>")
    parts.append(f"<div class='sec'>A) 행에 답이 있나?</div><div>"
                 f"<label><input type='radio' name='a{i}' value='VALID'> VALID</label>"
                 f"<label><input type='radio' name='a{i}' value='PLAUS'> PLAUS</label>"
                 f"<label><input type='radio' name='a{i}' value='IRREL'> IRREL</label></div>")
    parts.append(f"<div class='sec'>B) 답이 MID 구역에 있나? (A=VALID일 때만)</div><div>"
                 f"<label><input type='radio' name='b{i}' value='YES'> YES (mid에 답)</label>"
                 f"<label><input type='radio' name='b{i}' value='NO'> NO (head/tail에만)</label></div>")
    parts.append("</div>")

parts.append("""
<div style="margin:26px 0"><button onclick="exportJSON()" style="padding:10px 22px;font-size:16px">export JSON</button></div>
<script>
function exportJSON(){
  const n=document.querySelectorAll('.q').length; const out=[];
  for(let i=0;i<n;i++){
    const a=document.querySelector('input[name="a'+i+'"]:checked');
    const b=document.querySelector('input[name="b'+i+'"]:checked');
    out.push({idx:i, v_row: a?a.value:null, v_mid: b?b.value:null});
  }
  const blob=new Blob([JSON.stringify(out,null,1)],{type:'application/json'});
  const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='stage2_row_verdicts.json'; a.click();
}
</script></body></html>""")
open(OUT_HTML, "w", encoding="utf-8").write("\n".join(parts))
print("sheet:", OUT_HTML)