"""P0' — assistant 5건 맥락 결합 재평가 (JEV 5회, <1¢)

A-AI 보완책: assistant 재판정은 직전 user 발화 + assistant 발화 세트로 평가.
직전 user 발화를 write_gate.evaluate_assistant 입력 앞에 prefix로 결합.
원래 단독 평가(skip)와 결과 비교.
"""
import json, os, sqlite3, sys, winreg, hashlib

sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")

# 키: HKCU 우선 (셸 env 옛 값 회피)
def _resolve_api_key():
    k = os.environ.get("TYPESAFE_API_KEY", "")
    try:
        hk = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment")
        try:
            reg_k, _ = winreg.QueryValueEx(hk, "TYPESAFE_API_KEY")
            if reg_k: k = reg_k
        finally:
            winreg.CloseKey(hk)
    except FileNotFoundError:
        pass
    return k

_key = _resolve_api_key()
if _key:
    os.environ["TYPESAFE_API_KEY"] = _key
print("키 해시:", hashlib.sha256(_key.encode()).hexdigest()[:16] if _key else "EMPTY")

from gateway import write_gate as wg

MNEMO = os.path.expandvars(r"%LOCALAPPDATA%\hermes\mnemosyne\data\mnemosyne.db")
RESULT = os.path.expandvars(r"%LOCALAPPDATA%\hermes\cache\scratch\failopen_rejudge_result.json")

res = json.load(open(RESULT, encoding="utf-8"))
asst_skips = [x for x in res["results"] if x["role"] == "assistant" and x["verdict"] == "skip"]

m = sqlite3.connect(f"file:{MNEMO}?mode=ro", uri=True)
cur = m.cursor()

print(f"\n=== assistant {len(asst_skips)}건 맥락 결합 재평가 ===")
for s in asst_skips:
    row = cur.execute("SELECT content, metadata_json FROM working_memory WHERE id=?", (s["memory_id"],)).fetchone()
    if not row:
        continue
    content, meta = row
    meta = json.loads(meta or "{}")
    idem = meta.get("idem_key", "")
    asst_body = content[12:] if content.startswith("[ASSISTANT] ") else content
    # 같은 idem_key의 [USER] 본문 (직전 user 발화)
    user_row = cur.execute(
        "SELECT content FROM working_memory WHERE metadata_json LIKE ? AND content LIKE '[USER]%' LIMIT 1",
        (f'%"{idem}"%',),
    ).fetchone()
    user_body = user_row[0][7:].strip() if user_row else "(없음)"

    # 맥락 결합 평가: "직전 USER: ...\n\n[assistant 발화]"
    combined = f"직전 사용자 메시지: {user_body}\n\n{asst_body}"
    try:
        r = wg.evaluate_assistant(combined)
        reason = r.get("reason")
        keep = r.get("keep")
        verdict = "keep" if keep else "skip"
    except Exception as e:
        reason, keep, verdict = f"error:{str(e)[:60]}", None, "error"
    print(f"--- {s['memory_id'][:8]} 원래={s['verdict']}({s['reason']}) → 맥락결합={verdict}({reason}) | keep={keep}")
    print(f"    [U] {user_body[:60]}")
    print(f"    [A] {asst_body[:60]}")

m.close()