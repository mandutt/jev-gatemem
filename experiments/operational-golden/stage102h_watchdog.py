# -*- coding: utf-8 -*-
"""stage102h_watchdog.py — 판정 러너 워치독 (2026-10-08)

용도: cron에서 no_agent로 주기 실행(예: 10분마다).
- 판정 진행도(체크포인트 수)가 이전 대비 정지/부진이면:
  ① 러너 프로세스 상태 확인
  ② 429/과부하 감지
  ③ 필요 시 러너 재시작 (체크포인트 이어서)
  ④ 텔레그램으로 상태 알림 (stdout에 경고 텍스트)

stdout 비어있으면 정상 — cron이 전송 안 함 (watchdog 패턴).
"""
import json, os, subprocess, sys, time, glob

REPO = r"C:\Users\mandu\hermes-made\jev-memory-middleware"
OUT = os.path.join(REPO, "experiments", "operational-golden", "data", "stage102h_judge_fixed.json")
LOG = os.path.join(REPO, "experiments", "operational-golden", "stage102h_run.log")
STATE = os.path.join(REPO, "experiments", "operational-golden", "stage102h_watchdog_state.json")
PYTHON = os.path.join(os.environ.get("LOCALAPPDATA", r"C:\Users\mandu\AppData\Local"), "jev-mem", "venv", "Scripts", "python.exe")
RUNNER = os.path.join(REPO, "experiments", "operational-golden", "stage102h_judge_fixed_workers.py")
TARGET = 1074
STALL_MIN = 8          # 이 분 이상 체크포인트 정지면 경고
MIN_DELTA = 0          # 주기당 최소 기대 증가 (no_agent cron에서 이전 값 비교)

def get_count():
    if not os.path.exists(OUT):
        return 0
    try:
        d = json.load(open(OUT, encoding="utf-8"))
        return sum(1 for x in d if x["judge_verdict"] in ("yes", "no"))
    except Exception:
        return -1

def runner_alive():
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*stage102h*' } | Measure-Object | Select-Object -ExpandProperty Count"],
            capture_output=True, text=True, timeout=20)
        return r.stdout.strip() != "0"
    except Exception:
        return True  # 확인 불가 시 살아있다고 가정 (알람 억제)

def main():
    now = time.time()
    count = get_count()
    alive = runner_alive()

    # 이전 상태
    state = {}
    if os.path.exists(STATE):
        try:
            state = json.load(open(STATE, encoding="utf-8"))
        except Exception:
            state = {}

    prev_count = state.get("count", count)
    prev_ts = state.get("ts", now)
    elapsed = (now - prev_ts) / 60  # 분

    messages = []

    if count < 0:
        messages.append("⚠️ 판정 체크포인트 파일 읽기 실패")
    elif elapsed > 0:
        delta = count - prev_count
        rate = delta / elapsed
        print(f"[ok] 판정 {count}/{TARGET} ({count/TARGET*100:.0f}%), 최근 {elapsed:.0f}분 {delta:+d}건 ({rate:.1f}건/분), 러너 {'🟢' if alive else '🔴'}")
        if delta == 0 and elapsed >= STALL_MIN:
            messages.append(f"🔴 판정 정지 {elapsed:.0f}분 (체크포인트 {count} 고정) — 러너 {'살아있음' if alive else '죽음'}")
        elif rate < MIN_DELTA and elapsed >= STALL_MIN:
            messages.append(f"🟠 판정 부진: {rate:.1f}건/분, {elapsed:.0f}분간 {delta}건")
        elif not alive and elapsed >= STALL_MIN:
            messages.append(f"🔴 러너 프로세스 없음 (마지막 체크포인트 {count}건, {elapsed:.0f}분 정지)")

    # 상태 저장
    json.dump({"count": count, "ts": now}, open(STATE, "w", encoding="utf-8"))

    if messages:
        # 텔레그램 알림을 위해 stdout으로 출력 (cron deliver)
        print("\n".join(messages))
        # 재시작 시도 (러너가 죽었을 때만)
        if not alive:
            try:
                subprocess.Popen([PYTHON, RUNNER],
                                 cwd=os.path.dirname(RUNNER),
                                 stdout=open(LOG, "a", encoding="utf-8"),
                                 stderr=subprocess.STDOUT,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                print(f"🔄 러너 재시작 실행 (체크포인트 {count}건)")
            except Exception as e:
                print(f"❌ 러너 재시작 실패: {e}")

if __name__ == "__main__":
    main()