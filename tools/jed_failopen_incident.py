"""P2b 장애 구간 스캔 → incident 생성 (D7) — gate_outage 테이블 백필.

사용법:
  python tools/jed_failopen_incident.py --scan      # fail_open 메모리 스캔 → incident 연결
  python tools/jed_failopen_incident.py --outages   # gate_outage 현황
  python tools/jed_failopen_incident.py --close inc-xxx  # incident 닫기

장애 기간(fail_open 마커)이 있으면 gate_outage에 incident를 생성하고,
메모리 metadata에 incident_id를 연결한다. (P2b 백필 — 신규 장애는
pipeline이 자동 기록)
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


def _ts(s) -> float:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def scan_and_connect() -> dict:
    mconn = sqlite3.connect(MNEMO_DB)  # 쓰기 필요 (metadata incident 연결)
    mconn.row_factory = sqlite3.Row
    sconn = sqlite3.connect(STATE_DB)
    sconn.row_factory = sqlite3.Row

    # fail_open 메모리 행 수집
    rows = mconn.execute(
        "SELECT id, timestamp, metadata_json FROM working_memory"
        " WHERE metadata_json LIKE '%fail_open%' AND metadata_json NOT LIKE '%rejudged%'"
        " ORDER BY timestamp").fetchall()
    print(f"재판정 전 fail_open 행: {len(rows)}건")

    # 기존 open incidents (reason+class 별 최신)
    open_inc = {}
    for r in sconn.execute(
            "SELECT * FROM gate_outage WHERE status = 'open'").fetchall():
        open_inc.setdefault((r["reason"], r["failure_class"]), []).append(dict(r))

    # 행별로 incident 연결 (5분 이내 연속 장애는 같은 incident로 병합)
    created = reused = 0
    for r in rows:
        meta = json.loads(r["metadata_json"] or "{}")
        gate = str(meta.get("gate", ""))
        reason = gate.replace("fail_open:", "") or "unknown"
        # failure_class 추론 (reason 기반)
        fcls = "unknown"
        if reason.startswith("http-402"):
            fcls = "billing"
        elif reason.startswith(("http-401", "http-403")):
            fcls = "auth"
        elif reason.startswith(("http-429", "http-5")):
            fcls = "transient"
        elif reason in ("no-key", "kill", "killswitch-off", "no-wg"):
            fcls = "config"

        ts = _ts(r["timestamp"])
        # 기존 incident 재사용 (같은 class, 5분 내)
        inc = None
        for cand in open_inc.get((reason, fcls), []):
            if ts - _ts(cand["started_at"]) < 300 and ts >= _ts(cand["started_at"]) - 300:
                inc = cand
                break
        if inc is None:
            inc_id = f"inc-{os.urandom(6).hex()}"
            now = datetime.now().isoformat(timespec="seconds")
            sconn.execute(
                "INSERT INTO gate_outage (incident_id, started_at, ended_at, reason,"
                " failure_class, count, status, created_at) VALUES (?,?,?,?,?,1,'open',?)",
                (inc_id, r["timestamp"], r["timestamp"], reason, fcls, now))
            open_inc.setdefault((reason, fcls), []).append(
                {"incident_id": inc_id, "started_at": r["timestamp"],
                 "reason": reason, "failure_class": fcls})
            inc = {"incident_id": inc_id, "started_at": r["timestamp"]}
            created += 1
        else:
            sconn.execute(
                "UPDATE gate_outage SET ended_at = ?, count = count + 1"
                " WHERE incident_id = ?", (r["timestamp"], inc["incident_id"]))
            reused += 1

        # 메모리 metadata에 incident_id 연결 (master: metadata)
        if "incident_id" not in meta:
            meta["incident_id"] = inc["incident_id"]
            mconn.execute(
                "UPDATE working_memory SET metadata_json = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), r["id"]))
    sconn.commit()
    mconn.commit()
    print(f"incident 생성: {created}건, 기존 병합: {reused}건")
    return {"created": created, "reused": reused, "total": len(rows)}


def show_outages() -> None:
    sconn = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    sconn.row_factory = sqlite3.Row
    rows = sconn.execute(
        "SELECT * FROM gate_outage ORDER BY started_at DESC LIMIT 30").fetchall()
    if not rows:
        print("gate_outage 기록 없음")
        return
    for r in rows:
        print(f"  {r['incident_id']} [{r['status']}] {r['reason']} "
              f"class={r['failure_class']} count={r['count']} "
              f"start={r['started_at']} end={r['ended_at']}")


def close_incident(incident_id: str) -> None:
    sconn = sqlite3.connect(STATE_DB)
    sconn.execute(
        "UPDATE gate_outage SET ended_at = ?, status = 'closed'"
        " WHERE incident_id = ? AND status = 'open'",
        (datetime.now().isoformat(timespec="seconds"), incident_id))
    sconn.commit()
    print(f"incident {incident_id} closed")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true", help="fail_open 스캔 → incident 생성")
    ap.add_argument("--outages", action="store_true", help="gate_outage 현황")
    ap.add_argument("--close", default=None, help="incident 닫기")
    args = ap.parse_args()

    if args.scan:
        scan_and_connect()
    elif args.outages:
        show_outages()
    elif args.close:
        close_incident(args.close)
    else:
        ap.print_help()