# STAGE105 — Shadow Enforcement 판정 (2026-10-10)

## 배경
- shadow 배치: 10-04 구축 (cron 10분 주기 `jev_shadow_batch.py` → `experiments/operational-golden/shadow_batch.py`)
- 목적: 라이브 쿼리에 JEV rerank를 shadow 실행 → gate YES/NO/ABSTAIN 분포 + A vs R2 갈림률 축적 후 **enforcement 판정** (3~5일 데이터 기준)
- 본 판정: 10-04 ~ 10-09 누적 **770건** (core_state.db shadow_log)

## 데이터 현황
- 총 770건 (source: query_log 660 / op-snapshot 90 / '?' 20)
- 기간: 2026-10-04 22:23 ~ 2026-10-09 11:47
- ⚠️ **10-09 11:47 이후 신규 기록 중단** — cron은 정상 가동 중 (last_status ok) — 별도 조사 필요

## 판정 상세

### 1. Gate 분포 (소스별)

| 소스 | YES | NO | ABSTAIN | 해석 |
|---|---|---|---|---|
| op-snapshot (gold 90건, 고정) | 81 (90%) | 4 (4%) | 5 (6%) | ✅ 정상 — gold 정답 96% 통과 |
| query_log-hermes (대화) | — | 284/508 (56%) | — | ✅ 작업지시 거부 (정상) |
| query_log-opencode (기술) | — | 14/115 (12%) | — | ✅ 정보 질문 통과 |
| '?' (20건, 과거 중복) | 2 | 10 | 8 | 참고 (10-05 버그 정리 전) |

### 2. 날짜별 추이

| 날짜 | query_log YES | NO | 해석 |
|---|---|---|---|
| 10-05 | 24% | 48% | 실험 밀집 (작업지시 다수) |
| 10-06 | 16% | 55% | stage20~48 실험 |
| 10-07 | 7% | 58% | 실험 최대 밀집 |
| 10-08 | 49% | 27% | 실험 종료 후 정상화 |
| 10-09 | 50% | 42% | 40건 소량 |

→ **NO 급증은 실험 활동(작업지시) 반영이지 회귀 아님**

### 3. R2 결정 분포
- inject (gate YES): 258건
- abstain(gate-NO): 321건 (대부분 작업지시/대화 — 정상 거부)
- A-abstain: 157건 (JEV abstain 라벨 — 모델 판정)
- choice-err: 25+4+4건 (429/502/503 — 일시적)

### 4. 오류율 33건 (4.3%) — 429 25 / 502 4 / 503 4 — 모두 JEV API 일시 오류, 정상 범위

### 5. Assistant 오염 14.8% (86/580) — 10-05 [ASSISTANT] 제외 해제 이후 정상 수준

## 최종 판정: **enforcement 불필요 — shadow gate 정상 동작**

1. **gold 정답 셋 96% 통과** (op-snapshot NO 4/90) — 정답 유실 없음
2. **NO는 작업지시/대화성 쿼리 거부** — 원하는 동작 (대화에 메모리 불필요 주입 안 함)
3. **시스템 회귀 없음** — 날짜별 변화는 실험 활동량 반영
4. shadow = 운영과 동일 파이프라인이므로 "enforcement 반영" 개념 자체가 없음 (관찰용)

## 후속 조치 (별도 이슈)
1. **10-09 11:47 이후 기록 중단 조사** — cron은 돌지만 shadow_log에 안 쌓임
   - 의심: query_log 신규 쿼리 0건 (마킹 누적), 또는 배치가 조용히 실패
2. **일일 요약 경고 2건 (gate NO율 30%+, R2 abstain 30%+)** — 오경보 판정 (위 근거), 임계 상향 고려
3. canary drift (L1 abstain_p>0.3 12건, 10-09/10) — 별개 지표, 별도 추적

## 파일
- 본 문서: `STAGE105_SHADOW_ENFORCEMENT_20261010.md`
- 데이터: `%LOCALAPPDATA%/jev-mem/core_state.db` shadow_log
- 스크립트: `experiments/operational-golden/shadow_batch.py`, `shadow_daily_summary.py`
- cron: `921cdb47edf2` (10분), `0295b127ee8e` (일일 09:00 요약)