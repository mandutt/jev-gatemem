"""state.db에서 실제 Hermes 데스크탑 사용자 메시지 추출 — 라이브 A/B 입력 생성.

동작:
- state.db의 messages 테이블에서 role='user' 메시지 추출 (최근 21일)
- 메타 지시문(진행해줘/좋아/다음 단계 등) 및 짧은 메시지(<12자) 제외
- 멀티라인 붙여넣기는 첫 줄만 유지
- 출력: data/ab_live_queries.jsonl [{id, ts, session_id, utterance, line_count}]
"""
import json
import re
import sqlite3
import time
from pathlib import Path

HERE = Path(__file__).parent
STATE_DB = Path(r"C:\Users\mandu\AppData\Local\hermes\state.db")
OUT = HERE / "data" / "ab_live_queries.jsonl"

# 메타 지시문 (전체 반복 패턴) — 실제 저장 가치 없는 짧은 진행 명령
META_PATTERNS = [
    r"^(좋아|그래|오케이|네|응|알겠어|알겠습니다|계속 진행|진행해줘|진행해 주세요|다음 단계|다음으로 진행|계속해줘|계속 해줘|멈춰|잠깐|잠시만)[.!~]*$",
    r"^(그래 진행해줘|좋아 진행해줘|좋아 다음 단계|다음단계 진행|계속 진행해줘|계속 진행해 주세요|이어서 진행|이어서 계속)[.!~]*$",
    r"^(잠깐만|잠시만요|확인해줘|확인해 주세요|정리해줘|요약해줘|진행 상황|중간 진행 상황|지금 뭐 하고 있어)[.!~]*$",
    r"^(3번|2번|1번) (진행|진행하자|진행해줘|으로 진행|부터 진행)[.!~]*$",
    r"^[0-9]+번 (진행|해줘|하자)[.!~]*$",
]


def is_meta(text: str) -> bool:
    t = text.strip()
    if len(t) < 12:
        return True
    for p in META_PATTERNS:
        if re.match(p, t):
            return True
    return False


def main():
    print(f"DB: {STATE_DB} (exists={STATE_DB.exists()})")
    conn = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    # 테이블 구조 확인
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print("tables:", tables)

    # messages 테이블 구조 확인
    cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
    print("messages cols:", cols)

    # role/user/timestamp 컬럼 확인 후 추출
    ts_col = "timestamp" if "timestamp" in cols else ("created_at" if "created_at" in cols else None)
    role_col = "role" if "role" in cols else None
    if ts_col is None or role_col is None:
        print("!! 필요한 컬럼 없음")
        return

    # UNIX epoch float 확인 (timestamp가 float면 epoch, ISO면 문자열)
    sample = conn.execute(
        f"SELECT {ts_col}, typeof({ts_col}) FROM messages LIMIT 1").fetchone()
    print(f"timestamp sample: {sample[0]!r} type={sample[1]}")

    if sample[1] in ("integer", "real"):
        cutoff = time.time() - 21 * 86400
        rows = conn.execute(
            f"SELECT id, session_id, {ts_col} AS ts, content FROM messages "
            f"WHERE role='user' AND CAST({ts_col} AS REAL) >= ? "
            f"ORDER BY {ts_col} DESC", (cutoff,)).fetchall()
    else:
        rows = conn.execute(
            f"SELECT id, session_id, {ts_col} AS ts, content FROM messages "
            f"WHERE role='user' ORDER BY {ts_col} DESC LIMIT 2000").fetchall()

    print(f"추출된 user 메시지: {len(rows)}건")

    out = []
    seen = set()
    for r in rows:
        content = (r["content"] or "").strip()
        if not content:
            continue
        # 멀티라인: 첫 줄만 (붙여넣기 작업)
        first_line = content.splitlines()[0].strip()
        if len(content.splitlines()) > 1:
            line_count = len(content.splitlines())
        else:
            line_count = 1
        if is_meta(first_line):
            continue
        # 중복 제거
        key = first_line[:100]
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "id": f"live_{len(out):04d}",
            "ts": str(r["ts"])[:19] if r["ts"] else "",
            "session_id": r["session_id"] or "",
            "utterance": first_line,
            "line_count": line_count,
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for row in out:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"출력: {OUT} ({len(out)}건)")


if __name__ == "__main__":
    main()