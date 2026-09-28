"""ab_assistant_gold50.html에 CARDS 데이터 주입 — 최종 UI 생성."""
import json
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "data" / "ab_assistant_gold50.jsonl"
TPL = HERE / "data" / "ab_assistant_gold50.html"
OUT = HERE / "data" / "ab_assistant_gold50_ready.html"

rows = [json.loads(l) for l in open(SRC, encoding="utf-8")]
cards = [
    {
        "i": idx,
        "text": r["utterance"],
        "jev_store": r["jev_store"],
        "jev_type": r["jev_type"],
        "jev_store_conf": r["jev_store_conf"] or 0.0,
        "jev_type_conf": r["jev_type_conf"] or 0.0,
    }
    for idx, r in enumerate(rows)
]
html = TPL.read_text(encoding="utf-8")
html = html.replace("__CARDS__", json.dumps(cards, ensure_ascii=False))
OUT.write_text(html, encoding="utf-8")
print(f"완료: {OUT} ({len(cards)}건)")