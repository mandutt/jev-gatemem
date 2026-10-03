"""P2b 테스트 오염 정리 — P2b 검증으로 생긴 테스트 데이터 제거.

- mnemosyne: P2b 테스트 메모리 (idem_key p2b-* / content P2b...)
- core_state: p2b ledger 행 + 테스트 incident (inc-78f54c6fc176, inc-de77e876947a)
실제 장애 403 2건 (48f06bb6ed2360d7, 8c7b3441597eb71c)과
inc-6e798b116d6b는 유지 (실제 데이터).
"""
import json
import os
import sqlite3

MNEMO_DB = os.path.expandvars(r"%LOCALAPPDATA%\hermes\mnemosyne\data\mnemosyne.db")
STATE_DB = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\core_state.db")

# 1. mnemosyne — P2b 테스트 행 삭제
mconn = sqlite3.connect(MNEMO_DB)
rows = mconn.execute(
    "SELECT id, metadata_json FROM working_memory WHERE metadata_json LIKE '%p2b%'"
    " OR content LIKE '%P2b%'").fetchall()
test_ids = []
for rid, meta_json in rows:
    meta = json.loads(meta_json or "{}")
    if str(meta.get("idem_key", "")).startswith("p2b-") or \
       str(meta.get("session_key", "")).startswith("hermes_p2b-"):
        test_ids.append(rid)
if test_ids:
    ph = ",".join("?" * len(test_ids))
    mconn.execute(f"DELETE FROM working_memory WHERE id IN ({ph})", test_ids)
    mconn.commit()
    print(f"mnemosyne: P2b 테스트 {len(test_ids)}건 삭제")
else:
    print("mnemosyne: P2b 테스트 행 없음")

# 2. core_state — p2b ledger 행 + 테스트 incident 삭제
sconn = sqlite3.connect(STATE_DB)
sconn.execute("DELETE FROM ingest_ledger WHERE idem_key LIKE 'p2b-%'")
sconn.execute(
    "DELETE FROM gate_outage WHERE incident_id IN (?,?)",
    ("inc-78f54c6fc176", "inc-de77e876947a"))
sconn.commit()
print("core_state: p2b ledger + 테스트 incident 삭제")

# 3. rejudge_verdicts — P2b 테스트 verdict 삭제 (있으면)
try:
    sconn.execute(
        "DELETE FROM rejudge_verdicts WHERE incident_id IN (?,?)",
        ("inc-78f54c6fc176", "inc-de77e876947a"))
    sconn.commit()
    print("rejudge_verdicts: 테스트 verdict 삭제")
except sqlite3.OperationalError:
    print("rejudge_verdicts: 테이블 없음 (스킵)")
print("정리 완료")