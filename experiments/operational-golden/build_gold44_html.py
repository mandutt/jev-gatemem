"""gold44 모바일 판정 HTML 생성기 (2026-10-04)

gold44_items.json → 모바일(안드로이드) 터치 친화 인터랙티브 판정 시트 HTML.
- Y/N/모호 탭 선택, 스와이프·자동저장(localStorage), 진행률 바, 결과 내보내기(JSON 복사)
- 의존성 0 (순수 HTML+CSS+JS), 파일로 열기 가능
"""
import json, os, sys, html

sys.stdout.reconfigure(encoding="utf-8")
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
items = json.load(open(os.path.join(DATA, "gold44_items.json"), encoding="utf-8"))

def esc(t):
    return html.escape(t or "", quote=True)

cards = []
for it in items:
    n = it["n"]
    qid = it["qid"]
    q = esc(it["query"])
    gold = esc(it["gold"])
    mtype = esc(it.get("mtype") or "")
    src = esc(it.get("source") or "")
    score = it.get("score6")
    score_txt = f'<span class="score">6차 점수: <b>{score:.3f}</b></span>' if score is not None else ""
    cards.append(f"""
<div class="card" data-n="{n}" data-qid="{qid}">
  <div class="card-head">
    <span class="num">{n:02d}/44</span>
    <span class="meta">{mtype} · {src[:24]}{'…' if len(src)>24 else ''}</span>
    {score_txt}
  </div>
  <div class="q"><b>Q.</b> {q}</div>
  <details class="gold"><summary>gold 보기 (tap)</summary>
    <div class="gold-body">{gold}</div>
  </details>
  <div class="verdict">
    <button class="vbtn" data-v="Y" type="button" onclick="setV(this,'Y')">✓ Y<br><small>직접 답</small></button>
    <button class="vbtn" data-v="N" type="button" onclick="setV(this,'N')">✗ N<br><small>답 아님</small></button>
    <button class="vbtn" data-v="M" type="button" onclick="setV(this,'M')">? 모호<br><small>판단 필요</small></button>
  </div>
  <textarea class="reason" rows="2" placeholder="근거 (선택)"></textarea>
</div>""")

html_doc = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>new 44건 gold 라벨 판정</title>
<style>
  :root {{
    --bg:#0f1115; --card:#1a1d24; --border:#2a2e37; --txt:#e8eaf0; --muted:#8b90a0;
    --y:#2e7d32; --n:#c62828; --m:#f9a825; --accent:#4fc3f7;
  }}
  * {{ box-sizing:border-box; -webkit-tap-highlight-color:transparent; }}
  body {{ margin:0; background:var(--bg); color:var(--txt); font-family:-apple-system,Roboto,'Noto Sans KR',sans-serif; padding-bottom:90px; }}
  header {{ position:sticky; top:0; z-index:10; background:var(--bg); padding:12px 14px 8px; border-bottom:1px solid var(--border); }}
  header h1 {{ margin:0 0 6px; font-size:16px; }}
  .prog {{ display:flex; align-items:center; gap:8px; font-size:12px; color:var(--muted); }}
  .bar {{ flex:1; height:8px; background:var(--border); border-radius:4px; overflow:hidden; }}
  .bar-fill {{ height:100%; width:0%; background:linear-gradient(90deg,var(--y),var(--accent)); transition:width .3s; }}
  .count {{ white-space:nowrap; }}
  main {{ padding:10px; }}
  .card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:12px; margin-bottom:12px; }}
  .card-head {{ display:flex; justify-content:space-between; align-items:center; font-size:11px; color:var(--muted); margin-bottom:8px; }}
  .num {{ font-weight:700; color:var(--accent); font-size:13px; }}
  .meta {{ flex:1; margin-left:8px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .score {{ font-size:11px; }}
  .score b {{ color:var(--m); }}
  .q {{ font-size:14px; line-height:1.45; margin-bottom:8px; }}
  .gold summary {{ font-size:12px; color:var(--accent); cursor:pointer; padding:4px 0; user-select:none; }}
  .gold-body {{ font-size:12px; color:var(--muted); background:#12141a; border:1px solid var(--border); border-radius:8px; padding:8px; margin-top:4px; max-height:160px; overflow-y:auto; white-space:pre-wrap; line-height:1.45; }}
  .verdict {{ display:flex; gap:8px; margin:10px 0 6px; }}
  .vbtn {{ flex:1; padding:10px 4px; font-size:13px; font-weight:700; border:2px solid var(--border); border-radius:10px; background:#12141a; color:var(--txt); cursor:pointer; }}
  .vbtn small {{ display:block; font-weight:400; font-size:10px; color:var(--muted); margin-top:2px; }}
  .vbtn.Y {{ background:var(--y); border-color:var(--y); color:#fff; }}
  .vbtn.N {{ background:var(--n); border-color:var(--n); color:#fff; }}
  .vbtn.M {{ background:var(--m); border-color:var(--m); color:#111; }}
  .vbtn.Y small, .vbtn.N small {{ color:rgba(255,255,255,.85); }}
  .reason {{ width:100%; background:#12141a; border:1px solid var(--border); border-radius:8px; color:var(--txt); font-size:12px; padding:8px; resize:vertical; }}
  footer {{ position:fixed; bottom:0; left:0; right:0; background:var(--bg); border-top:1px solid var(--border); padding:10px 14px; display:flex; gap:8px; }}
  footer button {{ flex:1; padding:12px; border-radius:10px; border:none; font-size:13px; font-weight:700; cursor:pointer; }}
  #exportBtn {{ background:var(--accent); color:#0b1220; }}
  #resetBtn {{ background:var(--border); color:var(--txt); }}
  .toast {{ position:fixed; bottom:84px; left:50%; transform:translateX(-50%); background:#333; color:#fff; padding:8px 16px; border-radius:20px; font-size:12px; opacity:0; transition:opacity .3s; pointer-events:none; z-index:20; }}
  .done {{ opacity:1; }}
  .done-card {{ border-color:var(--y); box-shadow:0 0 0 1px var(--y); }}
</style>
</head>
<body>
<header>
  <h1>new 44건 gold 라벨 판정</h1>
  <div class="prog">
    <span>진행</span>
    <div class="bar"><div class="bar-fill" id="barFill"></div></div>
    <span class="count" id="count">0/44</span>
  </div>
</header>
<main id="main">
{''.join(cards)}
</main>
<footer>
  <button id="exportBtn" onclick="exportJSON()">📋 결과 내보내기</button>
  <button id="resetBtn" onclick="resetAll()">↺ 초기화</button>
</footer>
<div class="toast" id="toast"></div>
<script>
const KEY = 'gold44_verdicts';
let state = {{}};
let storageOK = true;
try {{
  state = JSON.parse(localStorage.getItem(KEY) || '{{}}');
}} catch(e) {{
  storageOK = false;
  state = {{}};
}}
try {{ localStorage.setItem(KEY, JSON.stringify({{}})); }} catch(e) {{ storageOK = false; }}

// onclick="setV(this,'Y')" — 초기화 버튼과 동일한 직접 바인딩 방식 (모바일 호환 최대)
function setV(btn, v) {{
  const card = btn.closest('.card');
  const n = card.dataset.n;
  if (state[n] && state[n].v === v) {{
    delete state[n];
  }} else {{
    state[n] = {{ v: v, reason: (state[n] && state[n].reason) || '' }};
  }}
  card.querySelectorAll('.vbtn').forEach(b => b.classList.remove('Y','N','M'));
  if (state[n]) card.querySelector('.vbtn.' + state[n].v).classList.add(state[n].v);
  renderCard(card, n, true);
  save();
}}

function renderCard(card, n, keepReason) {{
  const s = state[n];
  card.classList.toggle('done-card', !!(s && s.v));
  if (s) {{
    const btn = card.querySelector('.vbtn.' + s.v);
    if (btn) btn.classList.add(s.v);
    if (keepReason && s.reason) {{
      const ta = card.querySelector('.reason');
      if (ta && !ta.value) ta.value = s.reason;
    }}
  }}
}}
function bindReason() {{
  document.querySelectorAll('.reason').forEach(ta => {{
    ta.addEventListener('input', () => {{
      const n = ta.closest('.card').dataset.n;
      if (!state[n]) state[n] = {{ v:'', reason:'' }};
      state[n].reason = ta.value;
      save();
    }});
  }});
}}
function save() {{
  if (storageOK) {{
    try {{ localStorage.setItem(KEY, JSON.stringify(state)); }} catch(e) {{ storageOK = false; }}
  }}
  const done = Object.values(state).filter(s => s && s.v).length;
  document.getElementById('count').textContent = done + '/44';
  document.getElementById('barFill').style.width = (done/44*100) + '%';
}}
function exportJSON() {{
  const out = [];
  document.querySelectorAll('.card').forEach(card => {{
    const n = card.dataset.n;
    const s = state[n] || {{}};
    out.push({{ n: +n, qid: card.dataset.qid, verdict: s.v || '', reason: s.reason || '' }});
  }});
  const txt = JSON.stringify(out, null, 1);
  if (navigator.clipboard) {{
    navigator.clipboard.writeText(txt).then(() => toast('클립보드에 복사됨 (붙여넣기로 전송)')).catch(() => fallbackCopy(txt));
  }} else {{ fallbackCopy(txt); }}
}}
function fallbackCopy(txt) {{
  const ta = document.createElement('textarea');
  ta.value = txt; document.body.appendChild(ta); ta.select();
  try {{ document.execCommand('copy'); toast('클립보드에 복사됨'); }} catch(e) {{ toast('복사 실패 — 직접 복사 필요'); }}
  document.body.removeChild(ta);
}}
function resetAll() {{
  if (!confirm('44건 판정을 모두 초기화할까요?')) return;
  state = {{}};
  if (storageOK) {{ try {{ localStorage.removeItem(KEY); }} catch(e) {{ storageOK = false; }} }}
  document.querySelectorAll('.card').forEach(c => {{
    c.querySelectorAll('.vbtn').forEach(b => b.classList.remove('Y','N','M'));
    c.querySelector('.reason').value = '';
    c.classList.remove('done-card');
  }});
  save(); toast('초기화됨');
}}
function toast(msg) {{
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('done');
  setTimeout(() => t.classList.remove('done'), 2000);
}}
// 초기 복원
document.querySelectorAll('.card').forEach(card => renderCard(card, card.dataset.n, false));
document.querySelectorAll('.reason').forEach(ta => {{
  const s = state[ta.closest('.card').dataset.n];
  if (s && s.reason) ta.value = s.reason;
}});
bindReason(); save();
</script>
</body>
</html>"""

out_path = os.path.join(DATA, "gold44_review.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html_doc)
print(f"생성: {out_path} ({len(html_doc)} 바이트)")