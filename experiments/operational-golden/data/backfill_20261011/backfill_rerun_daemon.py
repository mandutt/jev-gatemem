# -*- coding: utf-8 -*-
"""백필 복구 STEP 2: 데몬 venv(임베딩 정상: sitecustomize가 bench/bekko-a8m 등록)로
14개 세션 재실행. gate는 실 JEV 판정 (평소와 동일). KEEP만 저장 + 임베딩 포함.
"""
import os, sys, sqlite3, time
from datetime import datetime

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
sys.path.insert(0, REPO)

GAP_START = datetime.fromisoformat("2026-10-09T11:47")
GAP_END = datetime.fromisoformat("2026-10-10T18:00")

# 자기 검증: 이 venv가 bekko 등록 상태인지 (데몬 venv sitecustomize 기대)
try:
    from fastembed import TextEmbedding
    names = [m["model"] for m in TextEmbedding.list_supported_models()]
    assert any("bekko" in n for n in names), "이 venv는 bekko 미지원 — 데몬 venv로 실행하라"
    print("[check] bekko registered OK")
except Exception as e:
    print("[FATAL] fastembed/bekko 확인 실패:", e)
    sys.exit(2)

from gateway.write_gate import evaluate, evaluate_assistant
from mnemosyne.core import beam as bm

STATE_DB = r"C:\Users\mandu\AppData\Local\hermes\state.db"

SESSIONS = ["20261008_124838_4e6768", "20261009_121159_a1889f86", "20261009_170102_23af68",
    "20261009_202405_a3547d", "20261009_204758_9c4effac", "20261009_210137_5c8cd152",
    "20261009_213132_71a5b708", "20261009_215051_ab0ffc99", "20261010_000744_6cc8edd4",
    "20261010_001402_e6a182c5", "20261010_002027_a9264deb", "20261010_002807_ed5c5339",
    "20261010_112326_8e4f2320", "20261010_143419_985ebd", "20261010_211831_9a13e3",
    "cron_1f064a795460_20261009_093030"]

def load_messages(session_id):
    conn = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    s0, s1 = GAP_START.timestamp(), GAP_END.timestamp()
    rows = conn.execute(
        "SELECT role, content, timestamp FROM messages WHERE session_id=? AND role IN ('user','assistant') AND timestamp>=? AND timestamp<? ORDER BY timestamp",
        (session_id, s0, s1)).fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({"role": r["role"], "content": r["content"], "timestamp": datetime.fromtimestamp(r["timestamp"]).isoformat()})
    # turn-final (연속 assistant는 마지막만)
    final, last = [], None
    for m in out:
        if m["role"] == "user":
            last = "user"; final.append(m)
        else:
            if last == "assistant" and final and final[-1]["role"] == "assistant":
                final[-1] = m
            else:
                final.append(m)
            last = "assistant"
    return final

total_kept = 0
for sid in SESSIONS:
    msgs = load_messages(sid)
    kept = []
    skipped = 0
    for m in msgs:
        content = (m.get("content") or "").strip()
        if not content or len(content.split()) <= 1:
            skipped += 1; continue
        d = evaluate(content) if m["role"] == "user" else evaluate_assistant(content)
        if d.get("keep"):
            kept.append((m["role"], content, m["timestamp"]))
        else:
            skipped += 1
        time.sleep(0.3)
    print(f"=== {sid}: KEEP {len(kept)} / SKIP {skipped} ===", flush=True)
    b = bm.BeamMemory(session_id=f"hermes_{sid}")
    backfilled_at = datetime.now().isoformat()
    saved = 0
    for role, content, ts in kept:
        prefix = "[USER] " if role == "user" else "[ASSISTANT] "
        importance = 0.5 if role == "user" else 0.15
        meta = {"source_agent":"hermes", "session_key":f"hermes_{sid}",
                "idem_key":f"backfill:{sid}:{ts}", "source_timestamp":ts,
                "backfilled_at":backfilled_at, "gate":"backfill:gate-kept"}
        try:
            b.remember(content=prefix+content, source="conversation", importance=importance,
                       scope="session", metadata=meta)
            saved += 1
        except Exception as e:
            print(f"  [ERR] {role} {ts[:16]} 저장 실패: {str(e)[:100]}", flush=True)
    total_kept += len(kept)
    print(f"  저장 {saved}/{len(kept)}건", flush=True)
print(f"\n전체 KEEP 합계: {total_kept}")