"""대조군 — 정상 구간 KEEP 메모리 식별 (읽기 전용)

기준: 2026-09-29 ~ 10-01 (장애 이전, JEV 정상) stored + reason이 정상(store/type-rescue 등)
대상: user/asst 30~50건, fail_open 아님
"""
import json, os, sqlite3

CORE = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\core_state.db")
MNEMO = os.path.expandvars(r"%LOCALAPPDATA%\hermes\mnemosyne\data\mnemosyne.db")

c = sqlite3.connect(f"file:{CORE}?mode=ro", uri=True)
rows = c.execute("""
    SELECT idem_key, received_at, decisions_json, memory_ids_json
    FROM ingest_ledger
    WHERE status='stored'
      AND received_at >= '2026-09-29' AND received_at < '2026-10-02'
    ORDER BY received_at
""").fetchall()

# 정상 reason (fail_open 아님) + fail_open 마커 없는 stored만
normal = []
for idem, recv, dec, mids in rows:
    try:
        d = json.loads(dec or "{}")
    except Exception:
        continue
    # user/asst 중 하나라도 http-4xx/no-key/error 등이면 제외
    bad = False
    for role in ("user", "assistant"):
        r = d.get(role) or {}
        reason = str(r.get("reason") or "")
        if reason.startswith("http-") or reason in ("no-key", "error", "killswitch-off", "no-wg"):
            bad = True
    if bad:
        continue
    mids_l = json.loads(mids or "[]") if mids else []
    normal.append({"idem_key": idem, "received_at": recv, "memory_ids": mids_l, "decisions": d})

print(f"정상 구간(9/29~10/1) stored 턴: {len(normal)}")
print(f"메모리 row 합계: {sum(len(n['memory_ids']) for n in normal)}")

# user/asst 구분해서 어떤 메모리 row가 있는지
m = sqlite3.connect(f"file:{MNEMO}?mode=ro", uri=True)
cur = m.cursor()
cand = []  # (memory_id, role, content)
for n in normal:
    d = n["decisions"]
    mids = n["memory_ids"]
    for i, role in enumerate(("user", "assistant")):
        r = d.get(role) or {}
        if not r.get("keep") or i >= len(mids):
            continue
        mid = mids[i]
        row = cur.execute("SELECT content FROM working_memory WHERE id=?", (mid,)).fetchone()
        if row:
            cand.append((mid, role, row[0]))
m.close()

print(f"KEEP 메모리 후보: {len(cand)} (user {sum(1 for x in cand if x[1]=='user')}, asst {sum(1 for x in cand if x[1]=='assistant')})")
# 40건 샘플 (균형: user 20 + asst 20)
import random
random.seed(42)
users = [x for x in cand if x[1] == "user"]
assts = [x for x in cand if x[1] == "assistant"]
sample = random.sample(users, min(20, len(users))) + random.sample(assts, min(20, len(assts)))
print(f"샘플링: {len(sample)}건 (user {sum(1 for x in sample if x[1]=='user')} + asst {sum(1 for x in sample if x[1]=='assistant')})")

# 대조군 파일 저장
out = os.path.expandvars(r"%LOCALAPPDATA%\hermes\cache\scratch\failopen_control_group.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump([{"memory_id": x[0], "role": x[1], "content": x[2]} for x in sample],
              f, ensure_ascii=False, indent=1)
print(f"저장: {out}")