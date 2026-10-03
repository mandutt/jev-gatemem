"""P2b 재판정 엔진 v2 — strict mode, incident batch, lease, verdict 기록.

사용법:
  python tools/jed_failopen_rejudge_v2.py --incident inc-xxx [--strict] [--apply]
  python tools/jed_failopen_rejudge_v2.py --list                # 격리 대상 목록
  python tools/jed_failopen_rejudge_v2.py --batch 20            # 오래된 순 처리

- 격리 대상: metadata_json에 fail_open 마커 + incident_id (또는 전부)가 있는 행
- strict: JEV 실패/파싱 실패 시 예외 -> 해당 행 마커 불변 (rejudge_failed)
- --apply: verdict 반영 (keep -> rejudged:keep / skip -> rejudged:skip+archived)
- 기본 dry-run: 결과만 보고
"""
import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

MNEMO_DB = os.path.expandvars(r"%LOCALAPPDATA%\hermes\mnemosyne\data\mnemosyne.db")
STATE_DB = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\core_state.db")

# (kept, skipped) verdict 기록 테이블
VERDICT_TABLE = """
CREATE TABLE IF NOT EXISTS rejudge_verdicts (
  memory_id    TEXT PRIMARY KEY,
  verdict      TEXT NOT NULL,           -- keep | skip | failed
  model        TEXT NOT NULL,
  reason       TEXT,
  conf         REAL,
  lat_ms       INTEGER,
  rejudged_at  TEXT NOT NULL,
  incident_id  TEXT,
  apply_status TEXT                    -- none | applied
);
"""


def _hkc_key() -> str:
    """Resolve TYPESAFE_API_KEY from HKCU env (셸 env 옛 키 문제 회피)."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            v, _ = winreg.QueryValueEx(k, "TYPESAFE_API_KEY")
            return v
    except OSError:
        return os.environ.get("TYPESAFE_API_KEY", "")


def _gate_eval(utterance: str, *, role: str, key: str) -> dict:
    """Strict mode gate evaluation via write_gate (JEV live call)."""
    from gateway.write_gate import evaluate, evaluate_assistant
    if role == "assistant":
        return evaluate_assistant(utterance)
    return evaluate(utterance)


def _quarantine_rows(conn, incident_id: str | None) -> list[dict]:
    q = ("SELECT id, content, metadata_json, timestamp FROM working_memory"
         " WHERE metadata_json LIKE '%fail_open%'")
    args: list = []
    if incident_id:
        q += " AND metadata_json LIKE ?"
        args.append(f"%{incident_id}%")
    q += " ORDER BY timestamp"
    rows = conn.execute(q, args).fetchall()
    out = []
    for r in rows:
        meta = {}
        try:
            meta = json.loads(r["metadata_json"] or "{}")
        except Exception:
            pass
        out.append({
            "id": r["id"], "content": r["content"], "metadata": meta,
            "ts": r["timestamp"],
            "incident_id": meta.get("incident_id"),
            "fail_open": str(meta.get("gate", "")).replace("fail_open:", ""),
        })
    return out


def _verdict_db() -> sqlite3.Connection:
    conn = sqlite3.connect(STATE_DB)
    conn.row_factory = sqlite3.Row
    conn.executescript(VERDICT_TABLE)
    return conn


def _record(vconn, *, memory_id, verdict, model, reason, conf, lat_ms,
            incident_id, apply_status):
    vconn.execute(
        "INSERT OR REPLACE INTO rejudge_verdicts"
        " (memory_id, verdict, model, reason, conf, lat_ms, rejudged_at,"
        "  incident_id, apply_status) VALUES (?,?,?,?,?,?,?,?,?)",
        (memory_id, verdict, model, reason, conf, lat_ms,
         datetime.now().isoformat(timespec="seconds"), incident_id, apply_status))
    vconn.commit()


def _apply_verdict(conn, memory_id: str, verdict: str, model: str) -> None:
    """비파괴 반영: keep = rejudged:keep, skip = rejudged:skip + archived."""
    row = conn.execute(
        "SELECT metadata_json FROM working_memory WHERE id = ?", (memory_id,)
    ).fetchone()
    if not row:
        return
    meta = {}
    try:
        meta = json.loads(row["metadata_json"] or "{}")
    except Exception:
        pass
    # 이력 보존: 기존 gate/fail_open 값은 유지, verdict 기록
    meta["gate"] = f"rejudged:{verdict}@{model}"
    meta["rejudged_at"] = datetime.now().isoformat(timespec="seconds")
    if verdict == "skip":
        meta["archived"] = True
        # ★컬럼 write 필수 — recall 필터(beam.py)는 컬럼을 본다.
        # metadata만 쓰면 archived 행이 live recall에서 걸러지지 않음 (2026-10-03 실측).
        vu = datetime.now().isoformat(timespec="seconds")
        meta["valid_until"] = vu
        conn.execute(
            "UPDATE working_memory SET metadata_json = ?, valid_until = ?"
            " WHERE id = ?",
            (json.dumps(meta, ensure_ascii=False), vu, memory_id))
    else:
        conn.execute(
            "UPDATE working_memory SET metadata_json = ? WHERE id = ?",
            (json.dumps(meta, ensure_ascii=False), memory_id))
    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--incident", default=None, help="incident_id 필터")
    ap.add_argument("--batch", type=int, default=20, help="최대 처리 수")
    ap.add_argument("--strict", action="store_true", help="JEV 실패 시 예외(행 불변)")
    ap.add_argument("--apply", action="store_true", help="verdict 반영 (기본 dry-run)")
    ap.add_argument("--list", action="store_true", help="격리 대상 목록만 출력")
    args = ap.parse_args()

    mconn = sqlite3.connect(f"file:{MNEMO_DB}?mode=ro", uri=True)
    mconn.row_factory = sqlite3.Row
    rows = _quarantine_rows(mconn, args.incident)
    if args.list:
        print(f"격리 대상: {len(rows)}건")
        for r in rows[:50]:
            print(f"  {r['id'][:16]} [{r['fail_open']}] inc={r['incident_id']} {r['content'][:40]!r}")
        return

    # 배치 제한
    rows = rows[: args.batch]
    if not rows:
        print("격리 대상 없음")
        return

    key = _hkc_key()
    if not key:
        print("TYPESAFE_API_KEY 없음 (HKCU 확인)")
        sys.exit(2)
    os.environ["TYPESAFE_API_KEY"] = key

    vconn = _verdict_db()
    model = os.environ.get("JEV_MODEL", "jev-latest")

    print(f"=== 재판정 시작: {len(rows)}건 (strict={'ON' if args.strict else 'OFF'}) ===")
    results = {"keep": 0, "skip": 0, "failed": 0}
    for r in rows:
        content = r["content"]
        # [USER]/[ASSISTANT] prefix에서 role 추론
        role = "assistant" if content.strip().startswith("[ASSISTANT]") else "user"
        utterance = content
        for p in ("[USER] ", "[ASSISTANT] "):
            if utterance.startswith(p):
                utterance = utterance[len(p):]

        t0 = time.perf_counter()
        try:
            verdict = _gate_eval(utterance, role=role, key=key)
            lat = int((time.perf_counter() - t0) * 1000)
        except Exception as e:
            lat = int((time.perf_counter() - t0) * 1000)
            print(f"  [FAILED] {r['id'][:16]} JEV 오류: {e}")
            results["failed"] += 1
            _record(vconn, memory_id=r["id"], verdict="failed", model=model,
                    reason=str(e)[:200], conf=None, lat_ms=lat,
                    incident_id=r["incident_id"], apply_status="none")
            if args.strict:
                sys.exit(3)  # strict: 행 불변 + 중단
            continue

        keep = bool(verdict.get("keep"))
        reason = str(verdict.get("reason") or "")
        # 규칙 기반 정상 판정 여부 (pipeline의 NORMAL_REASONS와 동일)
        normal = reason in ("store", "type-rescue", "low-conf", "skip", "context",
                            "no-store", "commitment-fp-v4", "parse-fail")
        if keep:
            v = "keep" if normal else "skip"
        else:
            v = "skip"
        results[v] += 1
        print(f"  [{v.upper():4}] {r['id'][:16]} conf={verdict.get('conf')} reason={reason}")
        _record(vconn, memory_id=r["id"], verdict=v, model=model, reason=reason,
                conf=verdict.get("conf"), lat_ms=lat,
                incident_id=r["incident_id"], apply_status="none")
        if args.apply:
            _apply_verdict(mconn, r["id"], v, model)
            _record(vconn, memory_id=r["id"], verdict=v, model=model,
                    reason=reason, conf=verdict.get("conf"), lat_ms=lat,
                    incident_id=r["incident_id"], apply_status="applied")

    print(f"\n=== 결과: keep={results['keep']} skip={results['skip']} failed={results['failed']}"
          f" ({'적용됨' if args.apply else 'dry-run'}) ===")


if __name__ == "__main__":
    main()