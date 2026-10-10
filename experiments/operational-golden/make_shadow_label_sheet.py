#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""shadow NO 50건 라벨링 시트 생성 — 판정 기준: '이 쿼리에 메모리 검색이 필요했는가'"""
import json, html, os

BASE = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden"
sample = json.load(open(os.path.join(BASE, "data", "shadow_no_label_sample50.json"), encoding="utf-8"))
OUT = os.path.join(BASE, "data", "shadow_no_label_sample50.html")

cards = []
for i, (b, q, t) in enumerate(sample):
    qe = html.escape(q)
    cards.append(f"""
    <div class="card" id="c{i}" data-i="{i}">
      <div class="qid">#{i+1} <span class="badge {b}">{b}</span> <span class="ts">{t}</span></div>
      <div class="q">{qe}</div>
      <div class="btns">
        <label class="lbl"><input type="radio" name="v{i}" value="work" onclick="setV({i},'work')"> 작업지시</label>
        <label class="lbl"><input type="radio" name="v{i}" value="need" onclick="setV({i},'need')"> 메모리 필요</label>
        <label class="lbl"><input type="radio" name="v{i}" value="noopen" onclick="setV({i},'noopen')"> 무답/기타</label>
      </div>
      <textarea id="r{i}" rows="1" placeholder="비고(선택)" oninput="saveNote({i})"></textarea>
    </div>""")

js = """
const PREF = 'shadow50_';
let state = {};
function loadState(){ try { const s = localStorage.getItem(PREF+'state'); if(s) state = JSON.parse(s); } catch(e){} }
function saveState(){ try { localStorage.setItem(PREF+'state', JSON.stringify(state)); } catch(e){} }
function setV(i, v){
  state[i] = {v: v, r: (state[i]&&state[i].r)||''};
  saveState();
  const card = document.getElementById('c'+i);
  card.style.borderLeft = v==='work' ? '4px solid #4ade80' : v==='need' ? '4px solid #facc15' : '4px solid #94a3b8';
  card.style.background = v==='work' ? '#f0fdf4' : v==='need' ? '#fefce8' : '#f8fafc';
  updateCount();
}
function saveNote(i){ state[i] = {v:(state[i]&&state[i].v)||'', r: document.getElementById('r'+i).value}; saveState(); }
function updateCount(){
  const done = Object.values(state).filter(s=>s&&s.v).length;
  document.getElementById('cnt').textContent = done + ' / 50';
}
function loadPrev(){
  loadState();
  Object.keys(state).forEach(i=>{
    const s = state[i];
    if(s && s.v){
      const el = document.querySelector('input[name="v'+i+'"][value="'+s.v+'"]');
      if(el) el.checked = true;
      setV(parseInt(i), s.v);
      const r = document.getElementById('r'+i);
      if(r && s.r) r.value = s.r;
    }
  });
  updateCount();
}
function exportJSON(){
  loadState();
  const out = [];
  for(let i=0;i<50;i++){
    const s = state[i]||{};
    out.push({i, verdict: s.v||'unlabeled', note: s.r||''});
  }
  const blob = new Blob([JSON.stringify(out,null,2)], {type:'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'shadow_no_label_verdicts.json';
  a.click();
}
function init(){ loadPrev(); }
window.addEventListener('DOMContentLoaded', init);
"""

HTML = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>shadow NO 라벨링 (50건)</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 720px; margin: 0 auto; padding: 12px 10px 80px; }}
  .header {{ position: sticky; top: 0; background: #fff; padding: 8px 0; border-bottom: 1px solid #ddd; z-index: 5; }}
  h1 {{ font-size: 17px; margin: 0 0 4px; }}
  .banner {{ background: #fff7ed; border: 1px solid #fdba74; border-radius: 8px; padding: 8px 10px; font-size: 13px; margin: 8px 0; }}
  .cnt {{ font-weight: bold; color: #2563eb; }}
  .card {{ border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px 12px; margin: 10px 0; background: #fff; }}
  .qid {{ font-size: 12px; color: #64748b; margin-bottom: 5px; }}
  .badge {{ display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; }}
  .badge.작업지시 {{ background: #dcfce7; color: #166534; }}
  .badge.질문 {{ background: #dbeafe; color: #1e40af; }}
  .badge.모호 {{ background: #f1f5f9; color: #475569; }}
  .q {{ font-size: 15px; line-height: 1.5; margin-bottom: 8px; }}
  .btns {{ display: flex; gap: 8px; flex-wrap: wrap; }}
  .lbl {{ display: flex; align-items: center; gap: 5px; border: 1px solid #cbd5e1; border-radius: 20px; padding: 5px 12px; font-size: 13px; cursor: pointer; }}
  .lbl:active {{ background: #e2e8f0; }}
  textarea {{ width: 100%; box-sizing: border-box; margin-top: 6px; border: 1px solid #e2e8f0; border-radius: 6px; padding: 5px; font-size: 12px; }}
  .export {{ position: fixed; bottom: 12px; right: 12px; background: #2563eb; color: #fff; border: 0; border-radius: 24px; padding: 12px 18px; font-size: 14px; font-weight: bold; z-index: 10; }}
</style></head>
<body>
<div class="header"><h1>shadow NO 쿼리 라벨링 <span class="cnt" id="cnt">0 / 50</span></h1></div>
<div class="banner"><b>판정 기준:</b> 이 쿼리가 <b>메모리 검색이 필요했던</b> 턴이었나?<br>
· <b>작업지시</b> — 명령/지시/진행 확인 (\"~해줘\", \"계속\", \"확인\" 등) — 메모리 불필요<br>
· <b>메모리 필요</b> — 과거 사실/설정/결과를 물어보는 질문 (검색이 필요했음)<br>
· <b>무답/기타</b> — 질문도 지시도 아닌 것, 시스템 메시지, 분류 불가</div>

{''.join(cards)}

<button class="export" onclick="exportJSON()">📤 JSON 내보내기</button>
<script>{js}</script>
</body></html>"""

with open(OUT, "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"생성: {OUT} ({len(sample)}건)")