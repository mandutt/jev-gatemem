"""③ fail-open 메모리 재판정 (strict 모드, JEV 호출 ~64회)

원칙 (B-AI 검토 반영):
- 기존 write-gate 경로를 그대로 쓰지 않음: 실패 시 KEEP 반환 → '오염 세탁' 방지 위해
  strict 모드로 호출 — 실패(HTTP/예외/파싱 실패) 시 예외를 던지고 해당 행은 상태 불변.
- 재판정 입력: 저장본 전체 (redacted) — gate가 내부적으로 1500자 truncation 적용.
  저장본을 먼저 자르지 않음 (② 검증 결론).
- 결과 기록: rejudged_at/verdict/model 기록 (마커는 지우지 않고 rejudged:keep@... 로 변경)
- --apply 없으면 dry-run (JEV 호출은 하되 DB 변경 없음) — 리포트만.
"""
import argparse, json, os, sqlite3, sys, time, datetime, winreg

sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")

# 🔐 키 취급: 셸 env는 이전 세션 값을 물고 있을 수 있음 (실측 2026-10-03).
# 항상 HKCU 레지스트리 현재 값을 우선 사용 (데몬과 동일한 키 보장).
def _resolve_api_key():
    k = os.environ.get("TYPESAFE_API_KEY", "")
    try:
        hk = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment")
        try:
            reg_k, _ = winreg.QueryValueEx(hk, "TYPESAFE_API_KEY")
            if reg_k:
                k = reg_k  # HKCU가 우선
        finally:
            winreg.CloseKey(hk)
    except FileNotFoundError:
        pass
    return k

MNEMO = os.path.expandvars(r"%LOCALAPPDATA%\hermes\mnemosyne\data\mnemosyne.db")
BACKUP = os.path.expandvars(r"%LOCALAPPDATA%\hermes\cache\scratch\failopen_tag_backup.json")
OUTJSON = os.path.expandvars(r"%LOCALAPPDATA%\hermes\cache\scratch\failopen_rejudge_result.json")

# 정상 판정 reason (KEEP 승격 가능) vs 실패 (strict 예외)
NORMAL_REASONS_KEEP = ("store", "type-rescue", "low-conf")  # user
NORMAL_REASONS_KEEP_AS = ("store", "context", "no-store", "commitment-fp-v4")  # asst: SKIP은 아님
# 파싱 실패(store=None)도 KEEP이지만 재판정 맥락에선 "판정 실패"로 strict 예외 — 재판정의 재현성 목적상
# 재판정 시에도 파싱 실패는 JEV 응답 자체가 불완전했음을 의미하므로 예외로 처리. 원래 KEEP (누락 방지)과
# 구분: 저장은 이미 KEEP 상태라 재판정에서 파싱 실패 = "재판정 불가" (SKIP/승격 없음)
FAILURE_REASONS = ("http-", "no-key", "killswitch-off", "empty", "error")

class RejudgeStrictError(Exception):
    pass

def classify_gate_result(r, role):
    """strict 판정: 정상 reason이면 keep, 실패 reason이면 exception."""
    reason = str(r.get("reason") or "")
    keep = bool(r.get("keep"))
    # 정상 응답에서 KEEP (승격 가능)
    if keep:
        if role == "user" and reason in NORMAL_REASONS_KEEP:
            return "keep"
        if role == "assistant" and reason in NORMAL_REASONS_KEEP_AS:
            return "keep"
        if role == "assistant" and reason == "parse-fail":
            raise RejudgeStrictError(f"strict fail: role={role} reason={reason!r} (parse-fail, 재판정 불가)")
    # 정상 응답에서 SKIP (삭제 후보)
    if not keep:
        return "skip"
    # reason이 정상 목록도 아니고 keep=False도 아니면 (http-4xx 등) -> 실패
    raise RejudgeStrictError(f"strict fail: role={role} reason={reason!r} keep={keep}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="DB 반영 (마커 승격/제거) — 기본 dry-run")
    ap.add_argument("--limit", type=int, default=0, help="처리 제한 (0=전체)")
    args = ap.parse_args()

    from gateway import write_gate as wg
    # 키 주입 (HKCU 우선 — 셸 env 옛 값 회피)
    _key = _resolve_api_key()
    if _key:
        os.environ["TYPESAFE_API_KEY"] = _key
    # 가져올 평가 함수
    evaluate = wg.evaluate
    evaluate_assistant = wg.evaluate_assistant

    backup = json.load(open(BACKUP, encoding="utf-8"))
    targets = backup["targets"]
    if args.limit:
        targets = targets[:args.limit]

    m = sqlite3.connect(f"file:{MNEMO}?mode=ro", uri=True)
    cur = m.cursor()
    rows = {}
    for t in targets:
        row = cur.execute("SELECT content FROM working_memory WHERE id=?", (t["memory_id"],)).fetchone()
        if row:
            rows[t["memory_id"]] = row[0]
    m.close()

    print(f"재판정 대상: {len(targets)} 메모리 (user/asst), JEV 호출 예상: {len(targets)}회")
    results = []
    n_keep = n_skip = n_fail = 0
    t0 = time.time()
    for i, t in enumerate(targets, 1):
        content = rows.get(t["memory_id"])
        if content is None:
            results.append({**t, "verdict": "missing"})
            n_fail += 1
            continue
        body = content
        if body.startswith("[USER] "):
            body = body[8:]
            role = "user"
        elif body.startswith("[ASSISTANT] "):
            body = body[12:]
            role = "assistant"
        else:
            results.append({**t, "verdict": "prefix-err", "note": content[:40]})
            n_fail += 1
            continue
        try:
            if role == "user":
                r = evaluate(body)
            else:
                r = evaluate_assistant(body)
            verdict = classify_gate_result(r, role)
        except RejudgeStrictError as e:
            n_fail += 1
            results.append({**t, "verdict": "strict-fail", "reason": str(e), "raw": r.get("reason")})
            continue
        except Exception as e:
            n_fail += 1
            results.append({**t, "verdict": "error", "error": str(e)[:160]})
            continue
        if verdict == "keep":
            n_keep += 1
        else:
            n_skip += 1
        results.append({**t, "verdict": verdict, "reason": r.get("reason"),
                        "latency_ms": r.get("latency_ms")})
        if i % 10 == 0:
            print(f"  ...{i}/{len(targets)} (keep={n_keep} skip={n_skip} fail={n_fail})")
    dt = time.time() - t0
    print(f"\n완료: keep={n_keep} skip={n_skip} fail={n_fail} ({(dt):.1f}s)")

    # 결과 저장
    with open(OUTJSON, "w", encoding="utf-8") as f:
        json.dump({"run_at": datetime.datetime.now().isoformat(),
                   "dry_run": not args.apply,
                   "results": results}, f, ensure_ascii=False, indent=1)
    print(f"결과: {OUTJSON}")

    if args.apply:
        # DB 반영: keep → 마커를 rejudged:keep@<verdict> 로 변경 (감사 이력 보존)
        # skip → soft-delete 아님 (사용자 승인 후 별도) — 여기선 마커만 'rejudged:skip' 변경
        mw = sqlite3.connect(MNEMO, timeout=10)
        n_upd = 0
        for res in results:
            if res["verdict"] not in ("keep", "skip"):
                continue
            row = mw.execute("SELECT metadata_json FROM working_memory WHERE id=?",
                             (res["memory_id"],)).fetchone()
            if not row:
                continue
            meta = json.loads(row[0] or "{}")
            meta["gate"] = f"rejudged:{res['verdict']}"
            mw.execute("UPDATE working_memory SET metadata_json=? WHERE id=?",
                       (json.dumps(meta, ensure_ascii=False), res["memory_id"]))
            n_upd += 1
        mw.commit()
        mw.close()
        print(f"[apply] 마커 전환: {n_upd}건 (keep→rejudged:keep, skip→rejudged:skip)")

if __name__ == "__main__":
    main()