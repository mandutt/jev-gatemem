"""대조군 재평가 — 정상 구간 KEEP 40건을 같은 재판정 엔진(strict, 맥락결합)으로 평가

기대: 실시간 게이트가 KEEP한 메모리의 대부분이 재판정에서도 KEEP이어야 함.
측정: ① user/asst 단독 평가 ② asst는 맥락 결합 평가 → 불일치율(재판정 SKIP 비율) 기준선
"""
import json, os, sqlite3, sys, winreg, hashlib

sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")

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

CTRL = os.path.expandvars(r"%LOCALAPPDATA%\hermes\cache\scratch\failopen_control_group.json")
MNEMO = os.path.expandvars(r"%LOCALAPPDATA%\hermes\mnemosyne\data\mnemosyne.db")

control = json.load(open(CTRL, encoding="utf-8"))

m = sqlite3.connect(f"file:{MNEMO}?mode=ro", uri=True)
cur = m.cursor()

NORMAL_REASONS_KEEP = ("store", "type-rescue", "low-conf")  # user
NORMAL_REASONS_KEEP_AS = ("store", "context", "no-store", "commitment-fp-v4")
FAIL_PREFIX = ("http-", "no-key", "killswitch-off", "empty", "error")

class StrictError(Exception): pass

def strict_classify(r, role):
    reason = str(r.get("reason") or "")
    keep = bool(r.get("keep"))
    if keep:
        if role == "user" and reason in NORMAL_REASONS_KEEP:
            return "keep"
        if role == "assistant" and reason in NORMAL_REASONS_KEEP_AS:
            return "keep"
        if role == "assistant" and reason == "parse-fail":
            raise StrictError(f"parse-fail")
    if not keep:
        return "skip"
    raise StrictError(f"reason={reason!r} keep={keep}")

print(f"\n=== 대조군 {len(control)}건 재평가 (strict) ===")
stats = {"keep": 0, "skip": 0, "fail": 0}
detail = []
for i, item in enumerate(control, 1):
    mid, role, content = item["memory_id"], item["role"], item["content"]
    body = content
    if content.startswith("[USER] "):
        body = content[7:]
        role_eval = "user"
    elif content.startswith("[ASSISTANT] "):
        body = content[12:]
        role_eval = "assistant"
    else:
        stats["fail"] += 1
        detail.append({"memory_id": mid, "role": role, "verdict": "prefix-err", "content": content[:40]})
        continue
    try:
        if role_eval == "user":
            r = wg.evaluate(body)
        else:
            # asst 맥락 결합: 같은 turn의 user 본문 찾기 (idem_key로)
            row = cur.execute("SELECT content FROM working_memory WHERE metadata_json LIKE ? AND content LIKE '[USER]%' LIMIT 1",
                              (f'%"{item.get("idem_key","__none__")}"%',)).fetchone()
            user_ctx = row[0][7:].strip() if row else ""
            combined = f"직전 사용자 메시지: {user_ctx}\n\n{body}" if user_ctx else body
            r = wg.evaluate_assistant(combined)
        verdict = strict_classify(r, role_eval)
    except StrictError as e:
        stats["fail"] += 1
        detail.append({"memory_id": mid, "role": role_eval, "verdict": "strict-fail", "reason": str(e)})
        continue
    except Exception as e:
        stats["fail"] += 1
        detail.append({"memory_id": mid, "role": role_eval, "verdict": "error", "error": str(e)[:120]})
        continue
    stats[verdict] += 1
    detail.append({"memory_id": mid, "role": role_eval, "verdict": verdict, "reason": r.get("reason"),
                   "content": content[:60]})
    if i % 10 == 0:
        print(f"  ...{i}/{len(control)} keep={stats['keep']} skip={stats['skip']} fail={stats['fail']}")

print(f"\n=== 대조군 결과 ===")
print(f"  keep={stats['keep']} skip={stats['skip']} fail={stats['fail']} (총 {len(control)})")
print(f"  불일치율(재판정 SKIP): {stats['skip']}/{len(control)} = {stats['skip']/len(control)*100:.1f}%")

# 대상(장애)군과 비교용 저장
out = os.path.expandvars(r"%LOCALAPPDATA%\hermes\cache\scratch\failopen_control_result.json")
json.dump({"control": detail, "stats": stats}, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"결과 저장: {out}")

print("\n=== SKIP/FAIL 상세 ===")
for d in detail:
    if d["verdict"] != "keep":
        print(f"  [{d['role']}] {d['verdict']} ({d.get('reason','')}) | {d.get('content','')[:70]}")
m.close()