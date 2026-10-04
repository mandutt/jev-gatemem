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
    <label class="vbtn" data-verdict="Y"><input type="radio" name="v{n}" value="Y"><span>✓ Y</span><small>직접 답</small></label>
    <label class="vbtn" data-verdict="N"><input type="radio" name="v{n}" value="N"><span>✗ N</span><small>답 아님</small></label>
    <label class="vbtn" data-verdict="M"><input type="radio" name="v{n}" value="M"><span>? 모호</span><small>판단 필요</small></label>
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
  body {{ margin:0; background:var(--bg); color:var(--txt); font-family:-apple-system,Roboto,'Noto Sans KR',sans-serif; padding-bottom:120px; }}
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
  .vbtn {{ flex:1; position:relative; display:flex; flex-direction:column; align-items:center; gap:2px; padding:10px 4px; font-size:13px; font-weight:700; border:2px solid var(--border); border-radius:10px; background:#12141a; color:var(--txt); cursor:pointer; user-select:none; -webkit-user-select:none; }}
  .vbtn small {{ font-weight:400; font-size:10px; color:var(--muted); }}
  .vbtn input {{ position:absolute; opacity:0; width:0; height:0; }}
  .vbtn.sel-y {{ background:var(--y); border-color:var(--y); color:#fff; }}
  .vbtn.sel-n {{ background:var(--n); border-color:var(--n); color:#fff; }}
  .vbtn.sel-m {{ background:var(--m); border-color:var(--m); color:#111; }}
  .vbtn.sel-y small, .vbtn.sel-n small {{ color:rgba(255,255,255,.85); }}
  .vbtn.sel-m small {{ color:rgba(17,17,17,.7); }}
  .vbtn:active {{ transform:scale(0.97); }}
  .reason {{ width:100%; background:#12141a; border:1px solid var(--border); border-radius:8px; color:var(--txt); font-size:12px; padding:8px; resize:vertical; }}
  footer {{ position:fixed; bottom:0; left:0; right:0; background:var(--bg); border-top:1px solid var(--border); padding:10px 14px; display:flex; gap:8px; pointer-events:none; }}
  footer button {{ flex:1; padding:12px; border-radius:10px; border:none; font-size:13px; font-weight:700; cursor:pointer; pointer-events:auto; }}
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

// 라디오 change → 상태 저장 (클릭은 브라우저 네이티브 라디오가 처리)
function bindRadios() {{
  document.querySelectorAll('.card').forEach(card => {{
    const n = card.dataset.n;
    // 초기 복원
    const saved = state[n];
    if (saved && saved.v) {{
      const radio = card.querySelector('input[value="' + saved.v + '"]');
      if (radio) radio.checked = true;
    }}
    card.querySelectorAll('input[type="radio"]').forEach(r => {{
      r.addEventListener('change', () => {{
        if (r.checked) {{
          state[n] = {{ v: r.value, reason: (state[n] && state[n].reason) || '' }};
          card.classList.add('done-card');
          card.querySelectorAll('.vbtn').forEach(b => b.classList.remove('sel-y','sel-n','sel-m'));
          const lbl = r.closest('.vbtn');
          lbl.classList.add(r.value === 'Y' ? 'sel-y' : (r.value === 'N' ? 'sel-n' : 'sel-m'));
        }}
        save();
      }});
    }});
    // 저장된 판정 시각적 복원
    if (saved && saved.v) {{
      const lbl = card.querySelector('input[value="' + saved.v + '"]').closest('.vbtn');
      lbl.classList.add(saved.v === 'Y' ? 'sel-y' : (saved.v === 'N' ? 'sel-n' : 'sel-m'));
      card.classList.add('done-card');
    }}
  }});
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
    c.querySelectorAll('.vbtn').forEach(b => b.classList.remove('sel-y','sel-n','sel-m'));
    c.querySelectorAll('input[type="radio"]').forEach(r => r.checked = false);
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
// 초기화: 라디오 바인딩 + reason 복원
bindRadios();
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