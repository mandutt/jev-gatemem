"""context 분류 17건 전체 추출 + 판정 UI 생성 — G-AS context 필터 재평가용.

대상: ab_assistant_classified.jsonl에서 type==context 전건 (17건)
  - store=STORE && type=context (8건): G-AS에서 SKIP되는 유일한 집단 (G1과의 차이)
  - store=NO_STORE && type=context (9건): G1에서도 SKIP — 대조군
판정: STORE(저장 가치 있음) / NO_STORE(저장 불필요)
출력: data/ab_assistant_ctx17.jsonl + data/ab_assistant_ctx17.html
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"

SRC = DATA / "ab_assistant_classified.jsonl"
OUT_JSONL = DATA / "ab_assistant_ctx17.jsonl"
OUT_HTML = DATA / "ab_assistant_ctx17.html"

TPL = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8"/>
<title>context 분류 17건 저장 가치 판정 (G-AS 재평가)</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 720px; padding: 0 1rem; }
  h1 { font-size: 1.2rem; }
  .progress { background:#eee; border-radius:8px; padding:4px 10px; margin: 8px 0; font-size: .9rem; }
  .card { border:1px solid #ccc; border-radius:10px; padding:14px 16px; margin:10px 0; }
  .card .meta { color:#888; font-size:.8rem; margin-bottom:6px; }
  .card .text { font-size:1rem; line-height:1.5; white-space:pre-wrap; }
  .btns { margin-top:10px; display:flex; gap:8px; flex-wrap:wrap; }
  .btns button { padding:8px 16px; border-radius:8px; border:1px solid #ccc; cursor:pointer; font-size:.9rem; }
  .store { background:#e6f4ea; }
  .store.active { background:#34a853; color:#fff; }
  .nostore { background:#fce8e6; }
  .nostore.active { background:#ea4335; color:#fff; }
  .summary { margin:16px 0; padding:12px; background:#f8f9fa; border-radius:10px; }
  .export { padding:10px 20px; background:#1a73e8; color:#fff; border:none; border-radius:8px; cursor:pointer; }
</style>
</head>
<body>
<h1>context 분류 17건 — 저장 가치 판정 (17건)</h1>
<div class="progress" id="progress">0 / 17 판정됨</div>
<div class="summary">
  <b>판정 기준</b>: 이 assistant 발화가 장기 메모리에 저장할 가치가 있나요?<br/>
  🟢 <b>STORE</b> = 결과물·진단·세션 상태 요약·결정 등 장기 기억 가치 있음<br/>
  🔴 <b>NO_STORE</b> = 진행 중 발언, 다음 단계 예고, 임시 상태 — 저장 불필요<br/>
  <i>이 17건은 JEV가 "context(임시)"로 분류한 것들입니다. 실제로 임시인지, 결과물인지 판정해 주세요.</i>
</div>
<div id="cards"></div>
<div style="margin:20px 0"><button class="export" onclick="exportJSON()">판정 결과 내보내기 (JSON)</button></div>
<script>
const CARDS = __CARDS__;
const store = JSON.parse(localStorage.getItem('ab_assistant_ctx17') || '{}');
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
      <div class="meta">#${c.i + 1} / ${CARDS.length} · JEV: ${c.jev_store} (conf ${c.jev_store_conf.toFixed(2)})</div>
      <div class="text"></div>
      <div class="btns">
        <button class="store ${v === 'store' ? 'active' : ''}" onclick="judge('store')">🟢 STORE (저장 가치 있음)</button>
        <button class="nostore ${v === 'nostore' ? 'active' : ''}" onclick="judge('nostore')">🔴 NO_STORE (저장 불필요)</button>
        <button onclick="next()">다음 →</button>
      </div>
    </div>`;
  div.querySelector('.text').textContent = c.text;
}
function judge(v) {
  store[CARDS[current].i] = v;
  localStorage.setItem('ab_assistant_ctx17', JSON.stringify(store));
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
  a.download = 'ab_assistant_ctx17.json';
  a.click();
}
render();
</script>
</body>
</html>"""


def main():
    rows = [json.loads(l) for l in open(SRC, encoding="utf-8")]
    ctx = [r for r in rows if r["jev"].get("type") == "context"]
    print(f"전체 {len(rows)}건 중 context: {len(ctx)}건")
    print(f"  store=STORE && context (G-AS로 SKIP): {sum(1 for r in ctx if r['jev'].get('store')=='STORE')}건")
    print(f"  store=NO_STORE && context (G1에서도 SKIP): {sum(1 for r in ctx if r['jev'].get('store')!='STORE')}건")

    # jsonl 저장
    out = []
    for idx, r in enumerate(ctx):
        out.append({
            "i": idx,
            "id": r["id"],
            "utterance": r["utterance"],
            "jev_store": r["jev"].get("store"),
            "jev_type": r["jev"].get("type"),
            "jev_store_conf": r["jev"].get("store_confidence") or 0.0,
            "jev_type_conf": r["jev"].get("type_confidence") or 0.0,
        })
    OUT_JSONL.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in out) + "\n", encoding="utf-8")

    # HTML 주입
    cards = [
        {"i": x["i"], "text": x["utterance"], "jev_store": x["jev_store"],
         "jev_store_conf": x["jev_store_conf"]}
        for x in out
    ]
    html = TPL.replace("__CARDS__", json.dumps(cards, ensure_ascii=False))
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"생성: {OUT_JSONL} / {OUT_HTML}")

    # 미리보기 (idx, store, conf, 앞 60자)
    for x in out:
        print(f"  [{x['i']}] {x['jev_store']} conf={x['jev_store_conf']:.2f} | {x['utterance'][:60]}")


if __name__ == "__main__":
    main()