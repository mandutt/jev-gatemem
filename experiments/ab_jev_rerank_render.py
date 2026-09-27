"""JEV_RERANK 실사용 A/B — 페어와이즈 비교 (Option A, 2026-09-27).

실사용 user 쿼리에 대해 두 파이프라인을 각각 실행해 생성되는
'## Mnemosyne Context' 블록을 블라인드(A/B 랜덤)로 비교한다.

  - OFF = base Mnemosyne prefetch (JEV_RERANK=0 경로와 동일)
  - ON  = J1 pipeline (lane pool -> gate -> Jev lift) top-5

판정 기준:
  - disagreement: ON 블록과 OFF 블록의 id 순서가 다른 쿼리 (Jev가 실제로 뭔가 바꿈)
  - 사용자는 disagreement 쿼리 위주로 판정 (동일 블록은 자동 '비슷함')

출력:
  - experiments/ab_jev_rerank/pairs.html     블라인드 비교 UI
  - experiments/ab_jev_rerank/judgments.json 사용자 판정 기록 (없으면 생성)
  - experiments/ab_jev_rerank/run_<ts>.json 1회 실행 스냅샷 (raw)

사용:
  .venv/Scripts/python.exe experiments/ab_jev_rerank_render.py [--limit N] [--dry]
"""
from __future__ import annotations

import argparse
import html
import json
import os
import random
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

OUT_DIR = REPO / "experiments" / "ab_jev_rerank"
OUT_DIR.mkdir(parents=True, exist_ok=True)

LIVE_DB = r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db"
STATE_DB = r"C:\Users\mandu\AppData\Local\hermes\state.db"

# 쿼리 선별: 너무 짧거나(<=10자) 메타 지시('좋아', '진행해줘' 등) 제외
_MIN_LEN = 12
_SKIP_PATTERNS = (
    "좋아", "진행", "승인", "계속", "그래", "ㅇㅋ", "ok", "네 ", "응 ",
    "지시문", "핸드오프", "HANDOFF", "다음 단계", "실행해줘",
)


def _load_env() -> None:
    if os.environ.get("TYPESAFE_API_KEY"):
        return
    env_path = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("TYPESAFE_API_KEY="):
                os.environ["TYPESAFE_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")


_load_env()

import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ab_jev_rerank")


def collect_queries(limit: int = 16) -> list[str]:
    """최근 21일 user turns -> 평가 쿼리 목록 (지시/질문 위주)."""
    con = sqlite3.connect(STATE_DB)
    cur = con.cursor()
    cutoff = time.time() - 21 * 86400
    rows = cur.execute(
        "SELECT content FROM messages WHERE role='user' AND timestamp >= ? ORDER BY timestamp DESC",
        (cutoff,),
    ).fetchall()
    con.close()
    out = []
    seen = set()
    for (content,) in rows:
        c = (content or "").strip()
        if len(c) < _MIN_LEN:
            continue
        if any(p in c for p in _SKIP_PATTERNS):
            continue
        # 여러 줄이면 첫 줄만 (지시문 문서 제외)
        first = c.splitlines()[0].strip()
        if len(first) < _MIN_LEN:
            continue
        if first in seen:
            continue
        seen.add(first)
        out.append(first)
        if len(out) >= limit:
            break
    return out


def run_pair(query: str, with_jev: bool, timeout: float = 5.0) -> dict:
    """ON/OFF 하나 실행 -> {'ids': [...], 'block': str, 'jev_choice': str|None}"""
    os.environ.pop("JEV_RERANK", None)
    if not with_jev:
        os.environ["JEV_RERANK"] = "0"

    from backends.mnemosyne import MnemosyneBackend
    from gateway.gateway import MemoryGateway

    backend = MnemosyneBackend(db_path=LIVE_DB)
    gw = MemoryGateway(backend, timeout=timeout)
    cands = gw.retrieve_candidates(query)
    ids = [c.id for c in cands]
    block = _format_block_from_cands(cands)
    jev_choice = None
    if with_jev:
        # jev_rank==1 이 Jev pick (또는 pool 첫번째)
        jev_choice = cands[0].id[:12] if cands else None
    return {"ids": ids, "block": block, "jev_choice": jev_choice}


def _format_block_from_cands(cands) -> str:
    """MemoryCandidate 목록 -> '## Mnemosyne Context' 블록 (harness 포맷 재현)."""
    lines = ["## Mnemosyne Context"]
    for c in cands[:5]:
        lines.append(
            f"  [{c.created_at}] (importance {c.importance:.2f}, source {c.source_agent}) {c.short_excerpt}"
        )
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=14)
    ap.add_argument("--dry", action="store_true", help="OFF/ON 실행 없이 쿼리 목록만")
    args = ap.parse_args()

    queries = collect_queries(args.limit)
    if args.dry:
        print("쿼리 후보:")
        for i, q in enumerate(queries):
            print(f"  {i:2d} [{len(q):3d}] {q}")
        return 0

    pairs = []
    for i, q in enumerate(queries):
        off = run_pair(q, with_jev=False)
        on = run_pair(q, with_jev=True)
        disagree = off["ids"][:5] != on["ids"][:5]
        pairs.append({
            "idx": i,
            "query": q,
            "off": off,
            "on": on,
            "disagree": disagree,
        })
        log.info("[%02d] disagree=%s off_n=%d on_n=%d :: %s",
                 i, disagree, len(off["ids"]), len(on["ids"]), q[:40])

    ts = time.strftime("%Y%m%d_%H%M%S")
    run_path = OUT_DIR / f"run_{ts}.json"
    run_path.write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "n_queries": len(queries),
        "pairs": [
            {
                "idx": p["idx"],
                "query": p["query"],
                "disagree": p["disagree"],
                "off_ids": p["off"]["ids"][:5],
                "on_ids": p["on"]["ids"][:5],
                "off_block": p["off"]["block"],
                "on_block": p["on"]["block"],
                "jev_choice": p["on"]["jev_choice"],
            }
            for p in pairs
        ],
        "stats": {
            "disagree_count": sum(1 for p in pairs if p["disagree"]),
            "disagree_rate": sum(1 for p in pairs if p["disagree"]) / max(len(pairs), 1),
            "avg_off_n": sum(len(p["off"]["ids"]) for p in pairs) / max(len(pairs), 1),
            "avg_on_n": sum(len(p["on"]["ids"]) for p in pairs) / max(len(pairs), 1),
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # HTML 블라인드 UI
    render_html(pairs, run_path)
    print(f"\n분석 스냅샷: {run_path}")
    print(f"disagree: {sum(1 for p in pairs if p['disagree'])}/{len(pairs)}")
    print(f"HTML: {OUT_DIR / 'pairs.html'}")


def render_html(pairs: list, run_path: Path):
    """A/B 랜덤 순서 블라인드 비교 UI (local file, JS로 판정 저장)."""
    cards = []
    for p in pairs:
        a, b = p["off"], p["on"]
        if random.random() < 0.5:
            left, right = a, b
            left_lbl, right_lbl = "A", "B"
        else:
            left, right = b, a
            left_lbl, right_lbl = "B", "A"
        cards.append({
            "idx": p["idx"],
            "query": p["query"],
            "disagree": p["disagree"],
            "left": left["block"],
            "right": right["block"],
            "left_lbl": left_lbl,
            "right_lbl": right_lbl,
        })

    card_html = []
    for c in cards:
        q = html.escape(c["query"])
        left = html.escape(c["left"])
        right = html.escape(c["right"])
        disagree = "disagree" if c["disagree"] else "same"
        card_html.append(f"""
<div class="card {disagree}" data-idx="{c['idx']}" data-query="{q}">
  <div class="qh"><span class="tag">{disagree}</span> {q}</div>
  <div class="cols">
    <div class="blk"><div class="lbl">{c['left_lbl']}</div><pre>{left}</pre></div>
    <div class="blk"><div class="lbl">{c['right_lbl']}</div><pre>{right}</pre></div>
  </div>
  <div class="judge">
    <button class="jbtn" data-v="left">A 가 낫다</button>
    <button class="jbtn" data-v="right">B 가 낫다</button>
    <button class="jbtn" data-v="tie">비슷하다</button>
    <button class="jbtn" data-v="none">둘 다 무의미</button>
    <span class="note"></span>
  </div>
</div>""")

    html_doc = """<!DOCTYPE html>
    <html lang="ko"><head><meta charset="utf-8">
    <title>JEV_RERANK A/B — 블라인드 비교</title>
    <style>
      body { font-family: system-ui; margin: 24px; background: #fafafa; color: #222; }
      h1 { font-size: 20px; }
      .sub { color: #666; font-size: 13px; margin-bottom: 16px; }
      .card { background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 12px; margin-bottom: 16px; }
      .card.disagree { border-color: #e8a13a; }
      .qh { font-weight: 600; margin-bottom: 8px; }
      .tag { display: inline-block; font-size: 11px; padding: 1px 6px; border-radius: 4px; margin-right: 6px; background: #eee; }
      .tag.disagree { background: #fde9d2; color: #a05a00; }
      .cols { display: flex; gap: 12px; }
      .blk { flex: 1; }
      .lbl { font-size: 12px; font-weight: 700; color: #555; margin-bottom: 4px; }
      pre { background: #f5f5f5; border: 1px solid #eee; padding: 8px; font-size: 11px; white-space: pre-wrap; word-break: break-all; min-height: 60px; }
      .judge { margin-top: 8px; }
      .jbtn { font-size: 12px; padding: 4px 10px; margin-right: 6px; border: 1px solid #ccc; border-radius: 4px; background: #fff; cursor: pointer; }
      .jbtn.sel { background: #cfe8ff; border-color: #4a9; }
      .note { font-size: 12px; color: #666; margin-left: 8px; }
      #summary { margin-top: 20px; padding: 12px; background: #eef; border-radius: 8px; font-size: 13px; }
    </style></head><body>
    <h1>JEV_RERANK 실사용 A/B — 블라인드 비교</h1>
    <div class="sub">각 카드: 같은 쿼리에 대한 OFF(베이스)와 ON(J1) 블록을 랜덤 순서로 표시. A/B 라벨은 무작위. 판정 후 저장 버튼을 누르세요.</div>
    __CARDS__
    <div id="summary">판정 없음</div>
    <script>
    const JUDGE_KEY = 'jev_ab_judgments';
    let judgments = {};
    try { judgments = JSON.parse(localStorage.getItem(JUDGE_KEY) || '{}'); } catch(e) {}

    document.querySelectorAll('.card').forEach(card => {
      const idx = card.dataset.idx;
      const saved = judgments[idx];
      if (saved) {
        card.querySelectorAll('.jbtn').forEach(b => {
          if (b.dataset.v === saved) b.classList.add('sel');
        });
        card.querySelector('.note').textContent = '(저장됨)';
      }
      card.querySelectorAll('.jbtn').forEach(btn => {
        btn.addEventListener('click', () => {
          card.querySelectorAll('.jbtn').forEach(b => b.classList.remove('sel'));
          btn.classList.add('sel');
          judgments[idx] = btn.dataset.v;
          localStorage.setItem(JUDGE_KEY, JSON.stringify(judgments));
          card.querySelector('.note').textContent = '(저장됨)';
          updateSummary();
        });
      });
    });

    function updateSummary() {
      const total = document.querySelectorAll('.card').length;
      const done = Object.keys(judgments).length;
      const counts = {};
      Object.values(judgments).forEach(v => counts[v] = (counts[v]||0) + 1);
      document.getElementById('summary').textContent =
        '판정 ' + done + '/' + total + ' — A승 ' + (counts['left']||0) + ' · B승 ' + (counts['right']||0) + ' · 비슷 ' + (counts['tie']||0) + ' · 무의미 ' + (counts['none']||0) + '  (브라우저 localStorage에 저장됨)';
    }
    updateSummary();
    </script></body></html>"""
    html_doc = html_doc.replace("__CARDS__", "".join(card_html))
    (OUT_DIR / "pairs.html").write_text(html_doc, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())