# STAGE53 — pool20/두 라벨/2콜 실측: **일일 무료 토큰 한도 소진으로 연기** (2026-10-06)

> A-7(pool 60→20) / B-4(abstain 두 라벨 분리) / C-4(진짜 2콜 winner-Noul) — 3종 AI 검토의
> 미실측 3건을 실측하려던 러너가 **JEV 일일 무료 토큰 한도 소진(429)** 으로 전량 실패.

## 진행 경과

1. **stage53 러너 작성** (`stage53_missed3.py`) — 100쿼리 × 4구조(base/pool20/dual/two_call)
   통합 비교. two_call은 winner noul 2콜 포함 ~500콜.
2. **1차 실행 (run1)**: err 57/100 — 전부 `http429`. 후반부만 성공(43건).
3. **2차 시도 (run2/run3)**: 429 대기·키 전환 로직 추가했으나 계속 429 — 중단/무효.
4. **원인 확정 (1콜 probe)**: 429 본문 = **일일 무료 토큰 한도 소진**
   `"You've hit the daily free allowance for jev-latest: 47,617,873 of 47,619,047 input tokens
   today... It resets at 00:00 UTC"`
   → **분당 rate limit이 아니라 일일 한도** — 키 전환·디바운스로 해결 불가.
   리셋 = 00:00 UTC = **KST 09:00**.

## 판정

- **stage53 실측은 2026-10-07 KST 09:00 이후 재시도 필요** (러너는 수정본 그대로 사용).
- 미실측 3건(A-7 pool20 / B-4 두 라벨 / C-4 2콜) 상태는 유지 — 외부 AI 문의 시 "일일 한도로
  연기"로 명시.

## 교훈 (스킬 §20 반영)

- 429는 응답 본문으로 **분당 rate limit vs 일일 토큰 한도**를 구분하라.
- `daily free allowance`/`resets at 00:00 UTC` → 키·대기 불가, 리셋까지 중단.
- 러너는 429 본문 일부·진행 카운트를 로그에 남기고, 실행 전 1콜 probe로 가용 확인.

## raw

- `stage53_missed3.py` (수정본 — 디바운스+키전환+로그 내장, 리셋 후 재실행 가능)
- `stage53_keyprobe.py` (키 상태 진단 — 400/200/429 판별)
- `data/stage53_run*.log` (전부 429로 무효), `data/stage53_missed3.json` (run1 부분 — 43건만 유효)