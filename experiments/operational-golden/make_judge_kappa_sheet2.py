#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""judge κ 보정 셋 2차 라벨링 시트 — 54건 (stage104 haiku 응답, no 16+yes 38)
기존 46건(stage102p deepcombo 응답)과 다른 응답 셋 — κ 확장 46→100"""
import json, html, os

BASE = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden"
items = json.load(open(os.path.join(BASE, "data", "judge_kappa_label54_stage104.json"), encoding="utf-8"))
OUT = os.path.join(BASE, "data", "judge_kappa_label_sheet2.html")
PREF = "jk54_"

cards = []
for i, x in enumerate(items):
    q = html.escape(x["query"])
    resp = html.escape(x["response"])
    hk = x.get("haiku_verdict", "?")
    trunc = len(x.get("response", "")) > 800
    resp_disp = resp[:800] + ("…" if trunc else "")
    cards.append(f"""
    <div class="card" id="c{i}" data-i="{i}">
      <div class="qid">#{i+1} <span class="badge">{x.get('cls','?')}</span> k={x.get('k')} fF={not x.get('framing')} src={x.get('src')} <span class="hk">haiku: {hk}</span> <span class="len">({len(x.get('response',''))}자)</span></div>
      <div class="q">{q}</div>
      <details open><summary>응답 원문 (전문)</summary><div class="resp">{resp_disp}</div></details>
      <div class="btns">
        <label class="lbl"><input type="radio" name="v{i}" value="yes" onclick="setV({i},'yes')"> ✅ 인용함</label>
        <label class="lbl"><input type="radio" name="v{i}" value="no" onclick="setV({i},'no')"> ❌ 안 함</label>
      </div>
      <textarea id="r{i}" rows="1" placeholder="비고(선택)" oninput="saveNote({i})"></textarea>
    </div>""")

js = f"""
const PREF = '{PREF}';
let state = {{}};
function loadState(){{ try {{ const s = localStorage.getItem(PREF+'state'); if(s) state = JSON.parse(s); }} catch(e){{}} }}
function saveState(){{ try {{ localStorage.setItem(PREF+'state', JSON.stringify(state)); }} catch(e){{}} }}
function setV(i, v){{
  state[i] = {{v: v, r: (state[i]&&state[i].r)||''}};
  saveState();
  const card = document.getElementById('c'+i);
  card.style.borderLeft = v==='yes' ? '4px solid #4ade80' : '4px solid #f87171';
  card.style.background = v==='yes' ? '#f0fdf4' : '#fef2f2';
  updateCount();
}}
function saveNote(i){{ state[i] = {{v:(state[i]&&state[i].v)||'', r: document.getElementById('r'+i).value}}; saveState(); }}
function updateCount(){{
  const done = Object.values(state).filter(s=>s&&s.v).length;
  document.getElementById('cnt').textContent = done + ' / ' + ITEMS;
}}
function loadPrev(){{
  loadState();
  Object.keys(state).forEach(i=>{{
    const s = state[i];
    if(s && s.v){{
      const el = document.querySelector('input[name="v'+i+'"][value="'+s.v+'"]');
      if(el) el.checked = true;
      setV(parseInt(i), s.v);
      const r = document.getElementById('r'+i);
      if(r && s.r) r.value = s.r;
    }}
  }});
  updateCount();
}}
function exportJSON(){{
  loadState();
  const out = [];
  for(let i=0;i<ITEMS;i++){{
    const s = state[i]||{{}};
    out.push({{i, verdict: s.v||'unlabeled', note: s.r||''}});
  }}
  const blob = new Blob([JSON.stringify(out,null,2)], {{type:'application/json'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'judge_kappa_verdicts2.json';
  a.click();
}}
const ITEMS = {len(items)};
window.addEventListener('DOMContentLoaded', loadPrev);
"""

HTML = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>판정 κ 보정 라벨링 2차 ({len(items)}건)</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 720px; margin: 0 auto; padding: 12px 10px 80px; }}
  .header {{ position: sticky; top: 0; background: #fff; padding: 8px 0; border-bottom: 1px solid #ddd; z-index: 5; }}
  h1 {{ font-size: 17px; margin: 0 0 4px; }}
  .banner {{ background: #eff6ff; border: 1px solid #93c5fd; border-radius: 8px; padding: 8px 10px; font-size: 13px; margin: 8px 0; }}
  .cnt {{ font-weight: bold; color: #2563eb; }}
  .card {{ border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px 12px; margin: 10px 0; background: #fff; }}
  .qid {{ font-size: 12px; color: #64748b; margin-bottom: 5px; }}
  .badge {{ display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; background: #dbeafe; color: #1e40af; }}
  .hk {{ color: #b45309; font-size: 11px; }}
  .len {{ color: #94a3b8; font-size: 11px; }}
  .q {{ font-size: 15px; line-height: 1.5; margin-bottom: 6px; }}
  details {{ margin-bottom: 6px; }}
  summary {{ font-size: 12px; color: #2563eb; cursor: pointer; }}
  .resp {{ font-size: 12px; color: #475569; background: #f8fafc; padding: 6px; border-radius: 6px; margin-top: 4px; white-space: pre-wrap; word-break: break-all; }}
  .btns {{ display: flex; gap: 8px; }}
  .lbl {{ display: flex; align-items: center; gap: 5px; border: 1px solid #cbd5e1; border-radius: 20px; padding: 5px 12px; font-size: 13px; cursor: pointer; }}
  textarea {{ width: 100%; box-sizing: border-box; margin-top: 6px; border: 1px solid #e2e8f0; border-radius: 6px; padding: 5px; font-size: 12px; }}
  .export {{ position: fixed; bottom: 12px; right: 12px; background: #2563eb; color: #fff; border: 0; border-radius: 24px; padding: 12px 18px; font-size: 14px; font-weight: bold; z-index: 10; }}
</style></head>
<body>
<div class="header"><h1>판정 κ 보정 라벨링 2차 <span class="cnt" id="cnt">0 / {len(items)}</span></h1></div>
<div class="banner"><b>판정 기준:</b> AI 응답이 <b>사용자 고유의 특정 정보</b>(파일 경로·설정 값·실험 수치·과거 사건/결론·사용자 고유 규칙)를 <b>구체적으로 인용했는가</b>?<br>
· <b>인용함(yes)</b> — 경로·숫자·모델명·규칙 등 사용자만 알 수 있는 정보 포함<br>
· <b>안 함(no)</b> — 일반 지식/추론으로도 답할 수 있는 내용뿐<br>
<span style="color:#b45309">⚠️ 응답 원문이 자동 펼침으로 표시됩니다. 전체를 보고 판정하세요. (stage104 = haiku 생성 응답, 기존 46건과 다른 셋)</span></div>

{''.join(cards)}

<button class="export" onclick="exportJSON()">📤 JSON 내보내기</button>
<script>{js}</script>
</body></html>"""

with open(OUT, "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"생성: {OUT} ({len(items)}건, no {sum(1 for x in items if x['haiku_verdict']=='no')} + yes {sum(1 for x in items if x['haiku_verdict']=='yes')})")