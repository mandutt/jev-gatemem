"""state.db에서 assistant 메시지 추출 — JEV 엄격 게이트 실측용.

동작:
- role='assistant' 메시지 중 최근 21일, 길이 30~3000자 샘플 추출
- (formatting-only / 도구호출 결과 요약성 짧은 것 제외)
- 출력: data/ab_live_assistant.jsonl [{id, ts, session_id, utterance}]

용도: "assistant 발화를 엄격 게이트(G-qual-assistant)로 저장하면
얼마나 걸러지고 얼마나 남는가" 실측.
"""
import json
import re
import sqlite3
from pathlib import Path

HERE = Path(__file__).parent
STATE_DB = Path(r"C:\Users\mandu\AppData\Local\hermes\state.db")
OUT = HERE / "data" / "ab_live_assistant.jsonl"

# 도구/포맷 전용 assistant 메시지 패턴 — 저장 가치 없는 것 우선 제외
TOOLISH_PATTERNS = [
    r"^```",                     # 코드블록 시작
    r"^\*?OK\*?[,.]?$",           # OK.
    r"^준비 완료",                # 준비 완료
    r"^완료",                     # 완료
    r"^\s*$",                     # 빈 메시지
]


def is_toolish(text: str) -> bool:
    t = text.strip()
    if len(t) < 30 or len(t) > 3000:
        return True
    for p in TOOLISH_PATTERNS:
        if re.match(p, t):
            return True
    return False


def main():
    conn = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
    ts_col = "timestamp" if "timestamp" in cols else None
    print(f"messages cols: {cols}")

    # 최근 21일 (timestamp가 epoch float일 가능성 — 확인 후 처리)
    sample = conn.execute("SELECT timestamp FROM messages WHERE role='assistant' ORDER BY timestamp DESC LIMIT 1").fetchone()
    print(f"최신 assistant timestamp: {sample['timestamp']!r} ({type(sample['timestamp']).__name__})")

    # epoch float면: 최근 21일 = now - 21*86400
    import time
    now = time.time()
    cutoff = now - 21 * 86400

    rows = conn.execute(
        "SELECT id, timestamp, session_id, content FROM messages "
        "WHERE role='assistant' AND timestamp >= ? "
        "ORDER BY timestamp",
        (cutoff,),
    ).fetchall()
    print(f"최근 21일 assistant: {len(rows)}건")

    kept = []
    for r in rows:
        content = r["content"] or ""
        if is_toolish(content):
            continue
        kept.append({
            "id": str(r["id"]),
            "ts": r["timestamp"],
            "session_id": r["session_id"],
            "utterance": content.strip()[:3000],
        })

    kept = kept[:200]  # 실측 배치 크기 제한 (1회 200건)
    OUT.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in kept), encoding="utf-8")
    print(f"샘플 {len(kept)}건 -> {OUT}")


if __name__ == "__main__":
    main()