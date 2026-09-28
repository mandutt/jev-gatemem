"""A/B 판정 카드 UI 생성 — SKIP 83건 중 실제 저장 가치 판정.

judge는 SKIP된 메시지를 보고:
- 'skip-ok': 정말 저장 안 해도 됨 (JEV 옳음)
- 'skip-bad': 저장해야 했음 (JEV 틀림 — 누락 위험)
판정을 localStorage에 저장, export 가능.
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
rows = [json.loads(l) for l in (HERE / "data" / "ab_live_jev.jsonl").open(encoding="utf-8")]
skip = [r for r in rows if r["type"] == "NO_STORE" and r["store"] == "NO_STORE"]

cards = []
for i, r in enumerate(skip):
    cards.append({
        "i": i,
        "score": r["type_confidence"],
        "text": r["utterance"],
    })

# 판정 UI: 카드별 skip-ok / skip-bad 버튼, 전체 진행률, export 버튼
html = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8"/>
<title>JEV v8 게이트 A/B — SKIP 판정</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 720px; padding: 0 1rem; }
  h1 { font-size: 1.2rem; }
  .progress { background:#eee; border-radius:8px; padding:4px 10px; margin: 8px 0; font-size: .9rem; }
  .card { border:1px solid #ccc; border-radius:10px; padding:14px 16px; margin:10px 0; }
  .card .meta { color:#888; font-size:.8rem; margin-bottom:6px; }
  .card .text { font-size:1rem; line-height:1.5; }
  .btns { margin-top:10px; display:flex; gap:8px; }
  .btns button { padding:8px 16px; border-radius:8px; border:1px solid #ccc; cursor:pointer; font-size:.9rem; }
  .ok { background:#e6f4ea; }
  .ok.active { background:#34a853; color:#fff; }
  .bad { background:#fce8e6; }
  .bad.active { background:#ea4335; color:#fff; }
  .summary { margin:16px 0; padding:12px; background:#f8f9fa; border-radius:10px; }
  .export { padding:10px 20px; background:#1a73e8; color:#fff; border:none; border-radius:8px; cursor:pointer; }
</style>
</head>
<body>
<h1>JEV v8 게이트 A/B — SKIP 판정 (83건)</h1>
<div class="progress" id="progress">0 / __N__ 판정됨</div>
<div class="summary">
  <b>판정 기준</b>: JEV가 "저장 안 해도 되는 일회성 발화"로 SKIP한 메시지입니다.<br/>
  🟢 <b>skip-ok</b> = 정말 저장 안 해도 됨 (JEV 판단 옳음)<br/>
  🔴 <b>skip-bad</b> = 저장해야 할 내용인데 JEV가 놓침 (누락 위험)<br/>
  <i>내용이 길면 끝까지 읽고 판정해 주세요.</i>
</div>
<div id="cards"></div>
<div style="margin:20px 0"><button class="export" onclick="exportJSON()">판정 결과 내보내기 (JSON)</button></div>
<script>
const CARDS = __CARDS__;
const store = JSON.parse(localStorage.getItem('ab_skip_verdicts') || '{}');
let current = 0;

function render() {
  const c = CARDS[current];
  const prog = document.getElementById('progress');
  const judged = Object.keys(store).length;
  prog.textContent = judged + ' / ' + CARDS.length + ' 판정됨';
  const div = document.getElementById('cards');
  const v = store[c.i];
  div.innerHTML = `
    <div class="card">
      <div class="meta">#${c.i + 1} / ${CARDS.length} · conf ${c.score.toFixed(2)}</div>
      <div class="text"></div>
      <div class="btns">
        <button class="ok ${v === 'ok' ? 'active' : ''}" onclick="judge('ok')">🟢 skip-ok (저장 불필요)</button>
        <button class="bad ${v === 'bad' ? 'active' : ''}" onclick="judge('bad')">🔴 skip-bad (저장 필요!)</button>
        <button onclick="next()">다음 →</button>
      </div>
    </div>`;
  div.querySelector('.text').textContent = c.text;
}
function judge(v) {
  store[CARDS[current].i] = v;
  localStorage.setItem('ab_skip_verdicts', JSON.stringify(store));
  next();
}
function next() {
  if (current < CARDS.length - 1) { current++; render(); }
  else { document.getElementById('cards').innerHTML = '<p style="font-size:1.2rem">🎉 모든 카드 판정 완료! 내보내기 버튼으로 결과 저장.</p>'; }
  render();
}
function exportJSON() {
  const out = { judged_at: new Date().toISOString(), verdicts: store };
  const blob = new Blob([JSON.stringify(out, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'ab_skip_verdicts.json';
  a.click();
}
render();
</script>
</body>
</html>"""

html = html.replace("__N__", str(len(cards))).replace("__CARDS__", json.dumps(cards, ensure_ascii=False))
out = HERE / "data" / "ab_skip_judge.html"
out.write_text(html, encoding="utf-8")
print(f"생성: {out} ({len(cards)}건 카드)")