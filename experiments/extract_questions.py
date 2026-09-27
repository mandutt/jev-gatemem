"""Extract candidate real-user questions from Hermes state.db for the eval dataset.

Read-only SELECT on the LIVE state.db is safe (no writes), but to be extra
conservative we copy the messages table into the project snapshot dir first.

Method:
  1. Copy messages+sessions into scratch SQLite (project-local).
  2. user-role messages, short(ish), non-empty, question-like.
  3. Heuristic filters: length, contains '?' or interrogative particles, no
     pure command/url/file noise.
  4. Output JSON: [{"id","session_id","msg_id","ts","text"}] for manual curation.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

LIVE_DB = Path(r"C:\Users\mandu\AppData\Local\hermes\state.db")
OUT = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\extracted_questions_raw.json")

# question-ish markers (ko/en)
_Q_MARK = re.compile(
    r"[?？]|"
    r"(무엇|어떻게|어떤|왜|언제|어디|누구|뭘|뭐가|뭐로|몇|인지|는지|할지|할까|해줘|해줄래|가능|알려|확인|점검|방법|차이|맞나|맞지|되나|되나요|있나요|없나요|설치|복구|수정|제거|만들어|구현|적용|연동|이유)",
    re.I,
)
_NOISE = re.compile(
    r"^@|^!|^/|^\$|^https?://|(다시 시도|retry|테스트|test|확인 바람|OK|ok$)|"
    r"^\s*[`~*_#>-]",
    re.M,
)
_MAX_LEN = 600
_MIN_LEN = 8


def main():
    # 1) local copy of messages + sessions
    scratch = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware\data\state_scratch.db")
    if scratch.exists():
        scratch.unlink()
    src = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True)
    dst = sqlite3.connect(scratch)
    dst.execute(f"ATTACH DATABASE {str(LIVE_DB)!r} AS src")
    dst.execute("CREATE TABLE messages AS SELECT * FROM src.messages")
    dst.commit()
    # sessions: id + title + created_at (for provenance)
    dst.execute("PRAGMA table_info(messages)")
    cols = [r[1] for r in dst.execute("PRAGMA table_info(messages)")]
    print("messages cols:", cols)
    dst.execute("CREATE TABLE sessions AS SELECT * FROM src.sessions")
    dst.commit()
    src.close()

    mcols = [r[1] for r in dst.execute("PRAGMA table_info(messages)")]
    s_cols = [r[1] for r in dst.execute("PRAGMA table_info(sessions)")]
    print("sessions cols:", s_cols)
    dst.close()


    # 2) query user messages
    con = sqlite3.connect(scratch)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    # columns may differ per schema; build dynamically
    def col(row, *names):
        for n in names:
            if n in row.keys():
                return row[n]
        return None

    rows = cur.execute("SELECT * FROM messages WHERE role IN ('user','human') OR role IS NULL").fetchall()
    print("user-ish rows:", len(rows))
    out = []
    for r in rows:
        text = col(r, "content", "text", "message") or ""
        if not isinstance(text, str):
            continue
        text = text.strip()
        if len(text) < _MIN_LEN or len(text) > _MAX_LEN:
            continue
        if _NOISE.search(text):
            continue
        if not _Q_MARK.search(text):
            continue
        # skip tool-ish / attached file headers
        if text.startswith("@") or "\n---\n" in text[:80]:
            continue
        out.append({
            "msg_id": col(r, "id"),
            "session_id": col(r, "session_id", "conversation_id"),
            "ts": col(r, "created_at", "timestamp", "ts"),
            "text": text[:300],
        })
    con.close()

    # dedupe by text (keep first)
    seen = set()
    dedup = []
    for item in out:
        key = item["text"][:80]
        if key in seen:
            continue
        seen.add(key)
        dedup.append(item)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dedup, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(dedup)} to {OUT}")


if __name__ == "__main__":
    main()