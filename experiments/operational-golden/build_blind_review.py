"""③ 맹검 재판정 HTML 생성 — 게이트/이전 판정 숨김 (2026-10-04)

b AI 프로토콜: 불일치 18건 + PLAUS 6건 = 24건을 조건 가린 채 재판정
- 카드: 질문 + 메모리 원문(full-text)만 표시 (게이트 YES/NO, 이전 사람 판정 숨김)
- 순서 셔플 (선입견 방지)
- 판정: VALID / PLAUS / IRREL (기준 배너 포함)
- 결과: JSON export → 이전 판정과 일치도(Cohen's kappa 등) 산출
"""
import json
import os
import random
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "experiments/operational-golden/data")
DB = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes/mnemosyne/data/mnemosyne.db")

# 맹검 대상 24건 (exp7g 기준 + 사람 판정)
vp = os.path.expandvars(r"%USERPROFILE%\Downloads\wgate_3class_verdicts.json")
v = json.load(open(vp, encoding="utf-8"))
g = json.load(open(os.path.join(DATA, "exp7g_gate_fulltext_raw.json"), encoding="utf-8"))
recs = g["records"]
for i, r in enumerate(recs):
    r["human"] = v[i]["v"]
targets = [r for r in recs
           if (r.get("new_verdict") == "NO" and r["human"] == "VALID") or r["human"] == "PLAUS"]

# DB 원문 가져오기
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

def fetch_full(rid):
    if not rid:
        return None
    cur = conn.execute("SELECT content FROM working_memory WHERE id=?", (rid,))
    r = cur.fetchone()
    if r:
        return r["content"]
    cur = conn.execute("SELECT content FROM episodic_memory WHERE id=?", (rid,))
    r = cur.fetchone()
    if r:
        return r["content"]
    return None

# 셔플 (고정 시드 — 재현 가능)
rng = random.Random(20261005)
order = list(range(len(targets)))
rng.shuffle(order)

cards = []
for new_i, old_i in enumerate(order):
    r = targets[old_i]
    q = (r["query"] or "").replace("\n", " ").strip()
    cand_id = r.get("cand_id")
    full = fetch_full(cand_id) or r.get("full") or r.get("cand") or ""
    cards.append(
        f'''<div class="card" data-i="{new_i}" data-old="{old_i}">
  <div class="card-head"><span class="num">#{new_i + 1}</span></div>
  <div class="q">🗨️ {q}</div>
  <details open><summary>메모리 원문 (전문 {len(full)}자)</summary><div class="mem">{full}</div></details>
  <div class="verdict">
    <label class="vbtn v-valid"><input type="radio" name="r{new_i}" value="VALID"><span>✓ VALID</span><small>대체 증거 유효</small></label>
    <label class="vbtn v-plaus"><input type="radio" name="r{new_i}" value="PLAUS"><span>⚠ PLAUS</span><small>그럴듯하지만 틀림</small></label>
    <label class="vbtn v-irrel"><input type="radio" name="r{new_i}" value="IRREL"><span>✗ IRREL</span><small>무관</small></label>
  </div>
</div>'''
    )

conn.close()
n = len(targets)
css = """<style>
  :root{--bg:#0f1115;--card:#16191f;--border:#2a2f3a;--txt:#e8eaed;--muted:#9aa0a6;
        --valid:#2e7d32;--plaus:#c62828;--irrel:#555;--accent:#4fc3f7;}
  *{box-sizing:border-box;-webkit-tap-highlight-color:transparent;}
  body{margin:0;background:var(--bg);color:var(--txt);font-family:-apple-system,Roboto,'Noto Sans KR',sans-serif;padding-bottom:120px;}
  header{position:sticky;top:0;z-index:10;background:var(--bg);padding:12px 14px 8px;border-bottom:1px solid var(--border);}
  header h1{margin:0 0 6px;font-size:16px;}
  .crit{font-size:10px;color:var(--muted);line-height:1.6;margin:6px 0 4px;padding:6px 8px;background:#12151b;border:1px solid var(--border);border-radius:8px;}
  .crit b{color:var(--txt);}
  .prog{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--muted);}
  .bar{flex:1;height:6px;background:var(--border);border-radius:3px;overflow:hidden;}
  #barFill{height:100%;width:0;background:var(--accent);transition:width .2s;}
  .card{background:var(--card);border:1px solid var(--border);border-radius:12px;margin:10px 12px;padding:12px;}
  .card-head{display:flex;align-items:center;gap:8px;margin-bottom:8px;font-size:11px;color:var(--muted);}
  .num{display:inline-block;padding:2px 8px;border-radius:10px;font-weight:700;font-size:10px;background:var(--accent);color:#111;}
  .q{font-size:14px;font-weight:600;line-height:1.5;margin-bottom:8px;}
  details{margin-bottom:10px;}
  summary{font-size:12px;color:var(--accent);cursor:pointer;}
  .mem{font-size:12px;color:var(--muted);line-height:1.6;background:#0d0f13;border-radius:8px;padding:10px;margin-top:6px;white-space:pre-wrap;word-break:break-word;}
  .verdict{display:flex;gap:8px;}
  .vbtn{flex:1;position:relative;display:flex;flex-direction:column;align-items:center;gap:3px;padding:10px 4px;
        font-size:12px;font-weight:700;border:2px solid var(--border);border-radius:10px;background:#1a1d24;color:var(--txt);cursor:pointer;user-select:none;-webkit-user-select:none;}
  .vbtn small{font-weight:400;font-size:9px;color:var(--muted);}
  .vbtn input{position:absolute;opacity:0;width:0;height:0;}
  .vbtn.sel-valid{background:var(--valid);border-color:var(--valid);color:#fff;}
  .vbtn.sel-plaus{background:var(--plaus);border-color:var(--plaus);color:#fff;}
  .vbtn.sel-irrel{background:var(--irrel);border-color:var(--irrel);color:#fff;}
  .vbtn.sel-valid small,.vbtn.sel-plaus small{color:rgba(255,255,255,.85);}
  .vbtn:active{transform:scale(0.97);}
  footer{position:fixed;bottom:0;left:0;right:0;background:var(--bg);border-top:1px solid var(--border);padding:10px 14px;display:flex;gap:8px;pointer-events:none;}
  footer button{flex:1;padding:12px;border-radius:10px;border:none;font-size:13px;font-weight:700;cursor:pointer;pointer-events:auto;}
  #exportBtn{background:var(--accent);color:#111;}
  #resetBtn{background:#333;color:var(--txt);}
  .toast{position:fixed;top:12px;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:8px 16px;border-radius:20px;font-size:12px;opacity:0;transition:opacity .3s;z-index:99;pointer-events:none;}
  .toast.done{opacity:1;}
  .done-card{border-color:var(--accent);}
</style>"""

script = f"""<script>
const KEY='wgate3_blind';let state={{}};let storageOK=true;
try{{state=JSON.parse(localStorage.getItem(KEY)||'{{}}');}}catch(e){{storageOK=false;state={{}};}}
try{{localStorage.setItem(KEY,JSON.stringify({{}}));}}catch(e){{storageOK=false;}}
function save(){{
  if(storageOK){{try{{localStorage.setItem(KEY,JSON.stringify(state));}}catch(e){{storageOK=false;}}}}
  const vals=Object.values(state).filter(v=>v);
  document.getElementById('count').textContent=vals.length+'/{n}';
  document.getElementById('barFill').style.width=(vals.length/{n}*100)+'%';
  const c={{VALID:0,PLAUS:0,IRREL:0}};
  vals.forEach(v=>{{if(c[v]!=null)c[v]++;}});
  document.getElementById('stat').textContent='VALID '+c.VALID+' · PLAUS '+c.PLAUS+' · IRREL '+c.IRREL;
}}
function bind(){{
  document.querySelectorAll('.card').forEach(card=>{{
    const i=card.dataset.i, saved=state[i];
    if(saved){{
      const rb=card.querySelector('input[value="'+saved+'"]');
      if(rb){{rb.checked=true;card.querySelector('.vbtn.v-'+saved.toLowerCase()).classList.add('sel-'+saved.toLowerCase());
        card.classList.add('done-card');}}
    }}
    card.querySelectorAll('input').forEach(r=>{{
      r.addEventListener('change',()=>{{
        if(!r.checked)return;
        const v=r.value; state[i]=v;
        card.querySelectorAll('.vbtn').forEach(b=>b.classList.remove('sel-valid','sel-plaus','sel-irrel'));
        card.querySelector('.vbtn.v-'+v.toLowerCase()).classList.add('sel-'+v.toLowerCase());
        card.classList.add('done-card');
        save();
      }});
    }});
  }});
}}
function exportJSON(){{
  const out=[];
  document.querySelectorAll('.card').forEach(card=>{{
    out.push({{idx:parseInt(card.dataset.i), old_idx:parseInt(card.dataset.old), v:state[card.dataset.i]||null}});
  }});
  const blob=new Blob([JSON.stringify(out,null,1)],{{type:'application/json'}});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download='wgate3_blind_verdicts.json';
  a.click();
  toast('JSON export');
}}
function resetAll(){{
  if(!confirm('전체 초기화?'))return;
  state={{}};
  if(storageOK){{try{{localStorage.removeItem(KEY);}}catch(e){{storageOK=false;}}}}
  document.querySelectorAll('.card').forEach(c=>{{
    c.querySelectorAll('.vbtn').forEach(b=>b.classList.remove('sel-valid','sel-plaus','sel-irrel'));
    c.querySelectorAll('input').forEach(r=>r.checked=false);
    c.classList.remove('done-card');
  }});
  save();toast('초기화됨');
}}
function toast(m){{const t=document.getElementById('toast');t.textContent=m;t.classList.add('done');setTimeout(()=>t.classList.remove('done'),2000);}}
bind();save();
</script>"""

html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>맹검 재판정 (24건)</title>
{css}
</head>
<body>
<header>
  <h1>🔍 맹검 재판정 <span id="count">0/{n}</span></h1>
  <div class="crit"><b>기준</b> — <b>VALID</b>: 메모리에 질문이 묻는 <b>그 사실/값/규칙이 실제로</b> 있음 (의역·중간 위치 OK) · <b>PLAUS</b>: 주제·키워드는 비슷하지만 <b>그 특정 답은 없음</b> · <b>IRREL</b>: 무관</div>
  <div class="prog"><span id="stat">VALID 0 · PLAUS 0 · IRREL 0</span></div>
  <div class="prog"><div class="bar"><div id="barFill"></div></div></div>
</header>
{''.join(cards)}
<footer>
  <button id="exportBtn" onclick="exportJSON()">⬇ JSON 내보내기</button>
  <button id="resetBtn" onclick="resetAll()">↺ 초기화</button>
</footer>
<div class="toast" id="toast"></div>
{script}
</body>
</html>"""

out_path = os.path.join(DATA, "wgate3_blind_review.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)
print(f"생성: {out_path} ({os.path.getsize(out_path):,} 바이트, {n}건)")
print("참고: 판정 순서는 셔플됨 — 이전 판정/게이트 결과 숨김")