"""stale 판정 품질 검증용 HTML 시트 생성 (샘플 20건 + 전체 119건)

판정 기준 (7차 VALID/PLAUS/IRREL 확장 — stale 맥락):
  REAL_STALE  = 지금 이 메모리를 참고하면 틀린 답을 주는 것 (대체/폐기됨, 옛 상태)
  PAST_REPORT = 과거 행위/완료 보고였지만, 지금 참고해도 해롭지 않음 (기록으로만 존재)
  STILL_TRUE  = 여전히 참인 사실 (stale 아님 — 오판)
  모바일: 네이티브 라디오 + label (검증된 방식), JSON export 버튼
"""
import json
import os
import sqlite3

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
RAW = os.path.join(ROOT, "experiments", "operational-golden", "audit_tier2_full_raw.json")
OUT = os.path.join(ROOT, "experiments", "operational-golden", "stale_review.html")

d = json.load(open(RAW, encoding="utf-8"))
stales = [r for r in d["records"] if r["verdict"] == "STALE"]
stales.sort(key=lambda r: r.get("prob_stale", 0), reverse=True)

# DB 원문 전문
db = os.path.expandvars(r"%LOCALAPPDATA%/hermes/mnemosyne/data/mnemosyne.db")
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
ids = [r["id"] for r in stales]
ph = ",".join("?" * len(ids))
rows = con.execute(
    f"SELECT id, content, memory_type, timestamp FROM working_memory WHERE id IN ({ph})", ids
).fetchall()
con.close()
byid = {r[0]: (r[1] or "", r[2], r[3]) for r in rows}

# 샘플 20 + 전체 (펼치기)
SAMPLE_N = 20
sample = stales[:SAMPLE_N]
rest = stales[SAMPLE_N:]

def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def item_html(r, idx):
    content, mtype, ts = byid.get(r["id"], ("(없음)", "?", "?"))
    return f"""
    <div class="item" id="item-{idx}">
      <div class="q">
        <span class="badge">{mtype}</span> prob_stale={r.get('prob_stale', 0):.2f}
        <span class="id">id={r['id'][:8]} ts={ts[:16]}</span>
      </div>
      <pre class="content">{esc(content[:2000])}</pre>
      <div class="opts">
        <label><input type="radio" name="v{idx}" value="REAL_STALE"> REAL_STALE (지금 참고 시 오답)</label>
        <label><input type="radio" name="v{idx}" value="PAST_REPORT"> PAST_REPORT (과거 기록, 무해)</label>
        <label><input type="radio" name="v{idx}" value="STILL_TRUE"> STILL_TRUE (여전히 참 — 오판)</label>
        <label><input type="radio" name="v{idx}" value="SKIP"> SKIP (판정 불가)</label>
      </div>
    </div>"""

sample_html = "".join(item_html(r, i) for i, r in enumerate(sample))
rest_html = "".join(item_html(r, 100 + i) for i, r in enumerate(rest))

html = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>stale 판정 시트 (119건)</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 720px; margin: 0 auto; padding: 12px; }}
  .banner {{ background: #fff3cd; border: 1px solid #ffe08a; padding: 10px; border-radius: 8px; margin-bottom: 12px; }}
  .banner b {{ color: #7a5c00; }}
  .item {{ border: 1px solid #ddd; border-radius: 8px; padding: 10px; margin: 10px 0; background: #fff; }}
  .q {{ font-size: 13px; color: #555; margin-bottom: 6px; }}
  .badge {{ background: #eee; padding: 2px 6px; border-radius: 4px; font-size: 11px; }}
  .id {{ float: right; color: #999; font-size: 11px; }}
  pre.content {{ white-space: pre-wrap; word-break: break-all; background: #f6f6f6; padding: 8px; border-radius: 6px; font-size: 13px; max-height: 240px; overflow-y: auto; }}
  .opts {{ margin-top: 8px; display: flex; flex-wrap: wrap; gap: 8px; }}
  .opts label {{ display: inline-flex; align-items: center; border: 1px solid #ccc; border-radius: 20px; padding: 6px 12px; font-size: 13px; cursor: pointer; }}
  .opts label:has(input:checked) {{ background: #e8f0fe; border-color: #4285f4; }}
  .opts input {{ margin-right: 6px; }}
  button {{ font-size: 15px; padding: 10px 20px; border-radius: 8px; border: none; background: #1a73e8; color: #fff; }}
  details {{ margin-top: 20px; }}
</style></head><body>
<div class="banner">
  <b>판정 기준</b><br>
  <b>REAL_STALE</b>: 지금 이 메모리를 참고하면 틀린 답을 주는 것 (대체·폐기·옛 상태)<br>
  <b>PAST_REPORT</b>: 과거 행위/완료 보고 — 기록일 뿐, 참고해도 해롭지 않음<br>
  <b>STILL_TRUE</b>: 여전히 참인 사실 (시스템 오판)<br>
  <b>SKIP</b>: 판정 불가
</div>
<div><b>샘플 {len(sample)}건</b> (prob 내림차순 상위) — 우선 판정, 이후 전체로 이동</div>
{sample_html}
<details><summary>전체 {len(rest)}건 (샘플 외, 접힘)</summary>
{rest_html}
</details>
<div style="margin-top: 16px;">
  <button onclick="exportJson()">JSON export</button>
  <span id="progress" style="margin-left: 12px; color: #555;"></span>
</div>
<script>
function collect() {{
  var items = document.querySelectorAll('.item');
  var out = {{}};
  var done = 0;
  items.forEach(function(it) {{
    var name = it.id.replace('item-', '');
    var sel = it.querySelector('input:checked');
    if (sel) {{ out[name] = sel.value; done++; }}
  }});
  document.getElementById('progress').textContent = done + '/' + items.length + ' 판정';
  return out;
}}
window.addEventListener('input', collect);
function exportJson() {{
  var data = collect();
  var blob = new Blob([JSON.stringify(data, null, 1)], {{type: 'application/json'}});
  var a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'stale_verdicts.json';
  a.click();
}}
</script>
</body></html>"""

with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)
print(f"생성: {OUT} ({len(stales)}건, 샘플 {len(sample)})")