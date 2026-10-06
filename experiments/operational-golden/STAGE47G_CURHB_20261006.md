# stage47g: current 라벨 + head-150+겹침-150(non-overlap) 병합 (2026-10-06)

stage47f에서 imphbn(improved+head겹침)의 WHY 구제는 윈도우 효과, gold50 손실은
improved 라벨 효과로 분리 → **current 라벨 + head겹침** 조합 검증.
2조건 동일 세션 (op 90 + noans 50 = 140콜/cond × 2 = 280콜, err 1).

## 결과

| cond | hit@1 | hit@3 | abstain | noans FP |
|---|---|---|---|---|
| cur (현행) | 73 | 78 | 6 | 21 |
| **curhb (current + head겹침)** | **75** | **79** | **3** | 24 |

## 목표 달성

- ✅ WHY 3건 구제: 마우스(cur abstain→rank 1), pi 프록시(abstain→rank 1), 코덱스(rank 3→rank 1)
  — head겹침 윈도우 효과가 current 라벨에서도 발휘
- ✅ gold50 보존: rank 1 유지 (improved 라벨 제거로 stage47f의 유일한 열위 해소)
- ✅ gemini/codex head 보존: rank 1 유지
- ✅ hit@1 75(+2), hit@3 79(+2)

## ⚠️ 유일한 약점 — noans FP 24 (cur 21 대비 +3)

- op에서 hit된 마우스/pi가 noans 쿼리에서 FP (답 존재 과신 여전)
- 규칙 확인형 noans 4건(주석 영어/테스트 생략/로그 한국어/browser.backend) 새 FP
  — head겹침이 head(질문 서술)+겹침을 만들어 규칙 확인 질문에 정답처럼 보이는
  메모리를 살림 (추정)

## 3개 후보 트레이드오프

| 후보 | hit@3 | noans FP | WHY 구제 | gold50 |
|---|---|---|---|---|
| cur (현행) | 78 | 21 | ❌ | ✅ |
| imphbn (improved+head겹침) | 79 | **14** | ✅ | ❌ |
| **curhb (current+head겹침)** | **79** | 24 | ✅ | ✅ |

- **imphbn**: noans 최강(FP 14), WHY 구제, gold50 손실
- **curhb**: WHY+gold50 모두 해결, noans FP는 현행보다 나쁨(+3)
- 선택은 "noans 방어(imphbn) vs gold50 보존(curhb)" 사이의 운영 판단 —
  u(무답 비율)·h(오주입 해로움) 실측이 필요

## raw

- `data/stage47g_curhb.json` (280 레코드)
- 러너: `stage47g_curhb.py`, 로그: `stage47g_run.log`