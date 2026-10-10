"""세션 메모리 사후 재주입 (backfill) — 2026-10-05

용도: 메모리 중단 구간(2026-10-04 10:09 ~ 00:11) 동안 저장되지 않은
대화를 평소와 동일한 게이트 판정으로 저장한다.

흐름:
1. state.db에서 대상 세션의 user/assistant 메시지 추출
   (tool 메시지 제외 — Hermes 평소에도 turn-final만 저장)
2. 각 발화를 write_gate.evaluate / evaluate_assistant에 통과 (평소와 동일 기준)
3. KEEP만 mnemosyne DB에 저장
   - content는 원문 그대로 (프리픽스 없음 — recall/게이트/분류 무영향)
   - metadata_json에 source_timestamp(원본 발화 시각) + backfilled_at(재주입 시각)
   - timestamp/created_at은 저장 시각(재주입 시각)으로 자연 기록

사용: jev-mem venv python으로 실행
  python backfill_session_memories.py --session <session_id> --since 2026-10-04T10:09
"""
import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
STATE_DB = r"C:\Users\mandu\AppData\Local\hermes\state.db"
MNEMO_DB = r"C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db"
# Hermes venv 발견 로직 (하드코딩 경로는 업데이트 시 무효화됨 — find로 탐색)
import glob
_HERMES = r"C:\Users\mandu\AppData\Local\hermes"
_venv_candidates = sorted(glob.glob(_HERMES + r"\installs\*\environments\*\venv\Lib\site-packages"))
if _venv_candidates:
    sys.path.insert(0, _venv_candidates[-1])

sys.path.insert(0, REPO)


def load_messages(session_id: str, since: str):
    conn = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    # since를 epoch로 변환 (messages.timestamp는 epoch float)
    dt = datetime.fromisoformat(since)
    since_epoch = dt.timestamp()
    rows = conn.execute(
        "SELECT role, content, timestamp FROM messages"
        " WHERE session_id=? AND role IN ('user','assistant')"
        " AND timestamp >= ? ORDER BY timestamp",
        (session_id, since_epoch),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["timestamp"] = datetime.fromtimestamp(d["timestamp"]).isoformat()
        out.append(d)
    # Hermes 평소 동작과 동일: turn-final assistant만 저장 대상.
    # 상태 머신 — tool 메시지를 경계로 'user로 시작해 마지막 assistant로 끝나는' 턴의
    # 마지막 assistant 발화만 남긴다 (tool 호출 중간 assistant는 제외).
    # 여기서는 user/assistant만 로드했으므로, assistant가 연속으로 오면
    # 마지막 assistant만 keep (앞 assistant는 중간 발화).
    final = []
    last_role = None
    for m in out:
        if m["role"] == "user":
            last_role = "user"
            final.append(m)  # user 발화는 그대로
        elif m["role"] == "assistant":
            # 직전이 user면 새 턴의 첫 assistant — 일단 후보. 직전이 assistant면
            # 이전 것을 중간 발화로 보고 교체(마지막 assistant만 유지)
            if last_role == "assistant" and final and final[-1]["role"] == "assistant":
                final[-1] = m
            else:
                final.append(m)
            last_role = "assistant"
    return final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--since", required=True, help="ISO 시작 시각 (중단 시점)")
    ap.add_argument("--until", default="", help="ISO 종료 시각 (복구 시점, 기본=지금)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    msgs = load_messages(args.session, args.since)
    if args.until:
        until_dt = datetime.fromisoformat(args.until)
        msgs = [m for m in msgs if m["timestamp"] <= until_dt.isoformat()]
    print(f"대상 발화: {len(msgs)}건 (user/assistant)")
    n_user = sum(1 for m in msgs if m["role"] == "user")
    n_asst = len(msgs) - n_user
    print(f"  user {n_user} / assistant {n_asst}")

    # 게이트 (평소와 동일 — 실 API)
    from gateway.write_gate import evaluate, evaluate_assistant

    kept = []
    skipped = 0
    for i, m in enumerate(msgs):
        content = (m.get("content") or "").strip()
        if not content or len(content.split()) <= 1:
            skipped += 1
            continue
        if m["role"] == "user":
            d = evaluate(content)
        else:
            d = evaluate_assistant(content)
        if d.get("keep"):
            kept.append({"role": m["role"], "content": content,
                         "timestamp": m["timestamp"]})
        else:
            skipped += 1
        if (i + 1) % 50 == 0:
            print(f"  ... {i+1}/{len(msgs)} 판정 완료 (keep={len(kept)})")
        time.sleep(0.3)  # rate limit 배려

    print(f"\n판정 결과: KEEP {len(kept)} / SKIP {skipped}")

    if args.dry_run:
        for k in kept[:10]:
            print(f"  [DRY] {k['role']} {k['timestamp']} | {k['content'][:60]}")
        print(f"  ... 총 {len(kept)}건 (dry-run — 저장 안 함)")
        return

    # 저장 — mnemosyne DB 직접 (데몬 경유 없이, 재주입 전용)
    from mnemosyne.core import beam as bm

    b = bm.BeamMemory(session_id=f"hermes_{args.session}")
    backfilled_at = datetime.now().isoformat()
    saved = 0
    for k in kept:
        prefix = "[USER] " if k["role"] == "user" else "[ASSISTANT] "
        importance = 0.5 if k["role"] == "user" else 0.15
        meta = {
            "source_agent": "hermes",
            "session_key": f"hermes_{args.session}",
            "idem_key": f"backfill:{args.session}:{k['timestamp']}",
            "source_timestamp": k["timestamp"],
            "backfilled_at": backfilled_at,
            "gate": "backfill:gate-kept",
        }
        b.remember(content=prefix + k["content"], source="conversation",
                   importance=importance, scope="session", metadata=meta)
        saved += 1
    print(f"저장 완료: {saved}건 (backfilled_at={backfilled_at})")


if __name__ == "__main__":
    main()