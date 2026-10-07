# STAGE95 — τ 감사 + canary 보강 (2026-10-07, 0콜)

## 요약

**τ=0.3 유지 확정 근거 확보 — 정답군 abstain_p>0.3 = 0건 (132건 전수). canary 보강 4건 완료.**

## 1. τ 감사 (a-ai/b-ai/c-ai 공통 요청, 0콜)

### 실측
- **stage85 live60 valid/yes 132건** (3-run × {k60, k20} — production-exact):
  - `abstain_p > 0.3`: **0건**
  - max 0.160 / p95 0.030 / 중앙 0.000
- stage85 block 38건: abstain_p max 0.160, >0.3 = 0건
- stage84 k60 op: abstain 3건 (gold_rank 8) — c-ai 인용 확인

### 판정
- **τ=0.3 정답군 오차단 0** — 3-AI 모두 "τ 유지" 권고와 일치
- τ 상향(0.4~0.5) 근거 없음 — abstain_p가 0.3 이하에 포진 (stage84/85 동일)
- abstain 3건(gold rank 8)은 **정답이 pool에 있는데 abstain한 케이스** — τ와 무관한 모델 판정 문제 (stage88 trace의 "아까/일단"과 다른 유형)

### 주의
- stage87 raw에는 abstain_p가 **미저장** — a-ai가 지목한 "op-90 정답 78건 감사"는 stage87로 불가, stage84/85(production-exact)로 대체함
- 라이브 trace의 >0.3 7건("아까" 0.81 등)은 저정보 발화 — b-ai "14건 라벨링"으로 정직 거부 여부 판정 필요 (보류)

## 2. canary 보강 (c-ai/b-ai 지적 4건 반영)

| 항목 | 기존 | 보강 |
|---|---|---|
| L2_YES drift 판정 | 미사용 (기준선만) | **정답 10개 중 1개 abstain이면 즉시 알림** (과다거부 센서) |
| timeout | 25s | **5s** (production J1과 일치) |
| abstain_p>0.3 카운트 | 미기록 | **L1 abstain_p_gt03 기록 + drift 감지** (τ 게이트 발동 근접) |
| pick drift | 미기록 | **choice_idx 중앙 기록 + ±5 drift 감지** |
| L1 abstain율 임계 | ±3콜 (25pp) | **±2콜** (a-ai 권고) |

### baseline 참고
- L1: abstain 12/12, abstain_p_med **1.0** (전부 abstain 선택 — 정상, L1은 무답 쿼리로 설계)
- L2_NOANS: abstain 0/10, ap_med 0.04 — **무답 쿼리에서 abstain 0 (과잉 pick)** — 기준선이므로 drift 기준으로만 사용
- L2_YES: abstain 0/10, ap_med 0.02

## 파일
- `experiments/operational-golden/canary_run.py` (보강 반영)
- `data/canary_baseline.json` (10-07 18:20 수집)
- `data/canary_log.jsonl` (2회 실행)

## 결론
- **사안 F: τ=0.3 유지** (정답 오차단 0 실측) — τ 재조정 불필요. 남은 과제는 b-ai "7+7건 라벨링" (정직 거부 vs 과다거부 판정)
- **사안 D: canary 보강 완료** — 사용자 승인 후 cron resume (현재 PAUSED → 09:00 KST 예약됨, 10-08부터 실행)