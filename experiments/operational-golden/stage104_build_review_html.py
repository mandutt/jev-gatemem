#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stage104_contradiction_review.html 생성 — 모순 유병률 사람 판정 시트 (2026-10-09)

기준 (header 배너 고정):
- V (사실/답변 중복·새 버전) = 같은 사실·답변·규칙 내용이 2회 이상 저장 — 옛 행 supersede 누락 (자동 supersede 대상)
- I (독립 메모리) = 주제는 겹치지만 다른 내용 (정상)
- W (지시/이벤트 반복) = [USER] 지시·벤치 태스크·재전송·상태 점검 등 반복 (기존 실측 결론)
- S = 건너뛰기

네이티브 라디오 + label (검증된 유일한 터치 방식). JSON export 버튼.
"""
import json, html

SRC = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data\stage104_contradiction_clusters.json"
OUT = r"C:\Users\mandu\hermes-made\jev-memory-middleware\experiments\operational-golden\data\stage104_contradiction_review.html"

clusters = json.load(open(SRC, encoding="utf-8"))

def esc(s):
    return html.escape(s or "", quote=True)

cards = []
for g in clusters:
    rows_html = []
    for r in g["rows"]:
        rows_html.append(
            f'<div class="row"><div class="rid">{esc(r["id"])}</div>'
            f'<div class="meta">{esc(r["created"])} · {esc(r["type"])}</div>'
            f'<div class="content">{esc(r["content"])}</div></div>'
        )
    card = f"""
    <div class="card" id="g{g['group']}" data-g="{g['group']}">
      <div class="ghead">그룹 {g['group']} <span class="n">n={g['n']}</span></div>
      {''.join(rows_html)}
      <div class="verdict">
        <label><input type="radio" name="g{g['group']}" value="V"> 사실/답변 중복·새 버전</label>
        <label><input type="radio" name="g{g['group']}" value="I"> 독립 메모리</label>
        <label><input type="radio" name="g{g['group']}" value="W"> 지시/이벤트 반복</label>
        <label><input type="radio" name="g{g['group']}" value="S"> 건너뛰기</label>
      </div>
    </div>"""
    cards.append(card)

page = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>모순 유병률 판정 — {len(clusters)}그룹</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 0; padding: 56px 12px 60px; background: #f6f7f9; }}
  header {{ position: fixed; top: 0; left: 0; right: 0; background: #1a1d24; color: #fff; padding: 8px 14px; z-index: 10; font-size: 13px; }}
  header b {{ color: #ffd166; }}
  .wrap {{ max-width: 900px; margin: 0 auto; }}
  .card {{ background: #fff; border: 1px solid #ddd; border-radius: 10px; padding: 14px; margin: 14px 0; }}
  .ghead {{ font-weight: 700; font-size: 15px; margin-bottom: 8px; }}
  .n {{ color: #888; font-size: 12px; }}
  .row {{ border-top: 1px solid #eee; padding: 8px 0; }}
  .rid {{ font-family: monospace; font-size: 11px; color: #999; }}
  .meta {{ font-size: 12px; color: #777; }}
  .content {{ white-space: pre-wrap; font-size: 13px; margin-top: 4px; }}
  .verdict {{ margin-top: 10px; display: flex; flex-wrap: wrap; gap: 10px; }}
  .verdict label {{ background: #eef1f5; border: 1px solid #ccc; border-radius: 20px; padding: 6px 12px; font-size: 13px; cursor: pointer; }}
  .verdict input {{ margin-right: 4px; }}
  .verdict label.chosen {{ background: #cfe3ff; border-color: #4a7dff; }}
  .bar {{ position: fixed; bottom: 0; left: 0; right: 0; background: #fff; border-top: 1px solid #ccc; padding: 8px 14px; display: flex; gap: 10px; align-items: center; z-index: 10; }}
  .bar button {{ padding: 8px 16px; border-radius: 8px; border: 0; cursor: pointer; font-size: 14px; }}
  #exportBtn {{ background: #2d6cdf; color: #fff; }}
  #resetBtn {{ background: #eee; }}
  #prog {{ font-size: 13px; color: #444; }}
</style></head><body>
<header><b>모순 유병률 판정 기준</b> — V: 같은 사실·답변·규칙 내용이 2회 이상 저장(옛 행 supersede 누락 — 자동 supersede 대상) · I: 주제 겹침만, 다른 내용(정상) · W: [USER] 지시·벤치 태스크·재전송·상태 점검 반복 · S: 건너뛰기</header>
<div class="wrap">
{''.join(cards)}
</div>
<div class="bar">
  <button id="exportBtn">JSON 내보내기</button>
  <button id="resetBtn">초기화</button>
  <span id="prog"></span>
</div>
<script>
(function(){{
  const cards = document.querySelectorAll('.card');
  const lsKey = 'am_contradiction_v2';
  const saved = {{}};
  try {{ Object.assign(saved, JSON.parse(localStorage.getItem(lsKey) || '{{}}')); }} catch(e) {{}}
  cards.forEach(c => {{
    const g = c.dataset.g;
    const radios = c.querySelectorAll('input[type=radio]');
    radios.forEach(r => {{
      if (saved[g] === r.value) {{ r.checked = true; r.closest('label').classList.add('chosen'); }}
      r.addEventListener('change', () => {{
        c.querySelectorAll('label').forEach(l => l.classList.remove('chosen'));
        r.closest('label').classList.add('chosen');
        saved[g] = r.value;
        localStorage.setItem(lsKey, JSON.stringify(saved));
        updateProg();
      }});
    }});
  }});
  function updateProg() {{
    const done = Object.values(saved).length;
    document.getElementById('prog').textContent = done + ' / ' + cards.length + ' 판정';
  }}
  updateProg();
  document.getElementById('exportBtn').addEventListener('click', () => {{
    const out = {{}};
    cards.forEach(c => {{ const g = c.dataset.g; if (saved[g]) out['g' + g] = saved[g]; }});
    const blob = new Blob([JSON.stringify(out, null, 1)], {{type: 'application/json'}});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'am_contradiction_verdicts.json';
    document.body.appendChild(a); a.click(); a.remove();
  }});
  document.getElementById('resetBtn').addEventListener('click', () => {{
    if (!confirm('모든 판정을 지울까요?')) return;
    localStorage.removeItem(lsKey);
    cards.forEach(c => {{ c.querySelectorAll('input').forEach(r => r.checked = false); c.querySelectorAll('label').forEach(l => l.classList.remove('chosen')); }});
    updateProg();
  }});
}})();
</script>
</body></html>"""

open(OUT, "w", encoding="utf-8").write(page)
print("생성:", OUT, f"({len(clusters)}그룹)")