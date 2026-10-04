"""Winner Gate 3분류 수동 판정용 HTML 생성 (2026-10-04)

앞선 gold44_review.html 경험 반영:
- Y/N/M 버튼 → <label><input type=radio> 네이티브 라디오 (안드로이드 터치 호환)
- footer pointer-events:none (클릭 가로채기 방지)
- localStorage try/catch (file:// 차단 대비)
- 라디오 change 이벤트로 상태 저장만 (클릭은 브라우저 네이티브)
- JSON export (결과 수집)
"""
import json
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")
DATA = "experiments/operational-golden/data"

d = json.load(open(os.path.join(DATA, "exp7f_winner_gate_raw.json"), encoding="utf-8"))
recs = d["records"]

# === v2: DB 원문 전문 조회 ===
DB = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes/mnemosyne/data/mnemosyne.db")
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

# noans 6건 top1 excerpt (cand_id 없음 — exp7d에서 가져옴)
nd = json.load(open(os.path.join(DATA, "exp7d_fresh_noans_raw.json"), encoding="utf-8"))["records"]
noans_top1 = {r["qid"]: r.get("top1_excerpt") for r in nd}

# 라디오 name은 전역 고유하게 (qid + idx)
cards = []
full_ok = 0
full_miss = 0
for idx, r in enumerate(recs):
    src = "LGO" if r["src"] == "lgo" else "NOANS"
    q = (r["query"] or "").replace("\n", " ").strip()
    verdict = r.get("verdict", "?")
    cand_id = r.get("cand_id")
    full = fetch_full(cand_id)
    if full:
        c = full
        note = f"전문 {len(full)}자"
        full_ok += 1
    else:
        c = (r.get("cand") or noans_top1.get(r["qid"], "") or "").replace("\n", " ").strip()
        note = f"한정 발췌 {len(c)}자 (원문 미확보)"
        full_miss += 1
    cards.append(
        f'''<div class="card" data-i="{idx}">
  <div class="card-head"><span class="badge {src.lower()}">{src}</span><span class="qid">{r["qid"]}</span><span class="gate">gate:{verdict}</span><span class="note">{note}</span></div>
  <div class="q">🗨️ {q}</div>
  <details open><summary>메모리 원문 (전문)</summary><div class="mem">{c}</div></details>
  <div class="verdict">
    <label class="vbtn v-valid"><input type="radio" name="r{idx}" value="VALID"><span>✓ VALID</span><small>대체 증거 유효</small></label>
    <label class="vbtn v-plaus"><input type="radio" name="r{idx}" value="PLAUS"><span>⚠ PLAUS</span><small>그럴듯하지만 틀림</small></label>
    <label class="vbtn v-irrel"><input type="radio" name="r{idx}" value="IRREL"><span>✗ IRREL</span><small>무관</small></label>
  </div>
</div>'''
    )
conn.close()
print(f"원문 전문 확보: {full_ok}/{len(recs)} (fallback {full_miss})")

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
  .badge{display:inline-block;padding:2px 8px;border-radius:10px;font-weight:700;font-size:10px;color:#fff;}
  .badge.lgo{background:#4a148c;} .badge.noans{background:#004d40;}
  .qid{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
  .gate{font-size:10px;padding:2px 6px;border:1px solid var(--border);border-radius:8px;}
  .note{font-size:9px;color:var(--muted);border:1px dashed var(--border);padding:1px 5px;border-radius:6px;}
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

script = """<script>
const KEY='wgate3_verdicts';let state={};let storageOK=true;
try{state=JSON.parse(localStorage.getItem(KEY)||'{}');}catch(e){storageOK=false;state={};}
try{localStorage.setItem(KEY,JSON.stringify({}));}catch(e){storageOK=false;}
function save(){
  if(storageOK){try{localStorage.setItem(KEY,JSON.stringify(state));}catch(e){storageOK=false;}}
  const vals=Object.values(state).filter(v=>v);
  const done=vals.length;
  document.getElementById('count').textContent=done+'/43';
  document.getElementById('barFill').style.width=(done/43*100)+'%';
  const c={VALID:0,PLAUS:0,IRREL:0};
  vals.forEach(v=>{if(c[v]!=null)c[v]++;});
  document.getElementById('stat').textContent='VALID '+c.VALID+' · PLAUS '+c.PLAUS+' · IRREL '+c.IRREL;
}
function bind(){
  document.querySelectorAll('.card').forEach(card=>{
    const i=card.dataset.i, saved=state[i];
    if(saved){
      const rb=card.querySelector('input[value="'+saved+'"]');
      if(rb){rb.checked=true;card.querySelector('.vbtn').classList.remove('sel-valid','sel-plaus','sel-irrel');
        card.querySelector('.vbtn.v-'+saved.toLowerCase()).classList.add('sel-'+saved.toLowerCase());
        card.classList.add('done-card');}
    }
    card.querySelectorAll('input').forEach(r=>{
      r.addEventListener('change',()=>{
        if(!r.checked)return;
        const v=r.value;
        state[i]=v;
        card.querySelectorAll('.vbtn').forEach(b=>b.classList.remove('sel-valid','sel-plaus','sel-irrel'));
        card.querySelector('.vbtn.v-'+v.toLowerCase()).classList.add('sel-'+v.toLowerCase());
        card.classList.add('done-card');
        save();
      });
    });
  });
}
function exportJSON(){
  const out=[];
  document.querySelectorAll('.card').forEach(card=>{
    const i=card.dataset.i;
    const v=state[i]||null;
    const qid=card.querySelector('.qid').textContent.trim();
    out.push({idx:parseInt(i),qid,v});
  });
  const blob=new Blob([JSON.stringify(out,null,1)],{type:'application/json'});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download='wgate_3class_verdicts.json';
  a.click();
  toast('JSON export');
}
function resetAll(){
  if(!confirm('43건 판정을 모두 초기화할까요?'))return;
  state={};
  if(storageOK){try{localStorage.removeItem(KEY);}catch(e){storageOK=false;}}
  document.querySelectorAll('.card').forEach(c=>{
    c.querySelectorAll('.vbtn').forEach(b=>b.classList.remove('sel-valid','sel-plaus','sel-irrel'));
    c.querySelectorAll('input').forEach(r=>r.checked=false);
    c.classList.remove('done-card');
  });
  save();toast('초기화됨');
}
function toast(m){const t=document.getElementById('toast');t.textContent=m;t.classList.add('done');setTimeout(()=>t.classList.remove('done'),2000);}
bind();save();
</script>"""

html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>Winner Gate 3분류 판정 (43건)</title>
{css}
</head>
<body>
<header>
  <h1>🧠 Winner Gate 3분류 판정 <span id="count">0/43</span></h1>
  <div class="crit"><b>기준</b> — <b>VALID</b>: 메모리에 질문이 묻는 <b>그 사실/값/규칙이 실제로</b> 들어 있음 (의역·중간 위치여도 OK) · <b>PLAUS</b>: 주제·키워드는 비슷하지만 <b>그 특정 답은 없음</b> (배경·관련 얘기만) · <b>IRREL</b>: 주제조차 무관</div>
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

out = os.path.join(DATA, "winner_gate_3class_review.html")
with open(out, "w", encoding="utf-8") as f:
    f.write(html)
print(f"생성: {out} ({os.path.getsize(out):,} 바이트)")