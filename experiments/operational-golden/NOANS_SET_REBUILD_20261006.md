# noans 셋 재구성 — 시점 고정 스냅샷 프로토콜 (2026-10-06)

## 배경

noans hard 셋(50건)이 시간에 따라 **변질**되는 문제를 발견 (stage38에서 최초 관찰:
같은 noans 쿼리가 stage35에선 abstain → stage38에선 FP로 뒤집힘, 8건).

**원인**: 질문 셋 생성(2026-10-04) 이후 우리 실험 대화 자체가 메모리에 쌓이면서
noans 쿼리와 어휘·의미가 겹치는 **자기참조 오염** 발생. "답 없음" 전제가 깨짐.

## 스냅샷 고정

- **파일**: `experiments/operational-golden/snapshots/mnemosyne_snapshot_20261006.db`
  (sqlite backup API, WAL-safe, 무결성 OK)
- working_memory 1,721행 / episodic 113행 (2026-10-06 10:25 기준, 임베딩 전수 bekko-a8m)
- **규칙**: 이후 모든 noans 평가는 이 스냅샷 기준으로 실행한다. 실측 시점이 달라도
  비교 집합이 동일하다.

## 변질 판정 (0콜)

1. **기계 스캔**: 각 noans 쿼리 FTS 상위 5 후보 + 질문 셋 이후(≥2026-10-04) 생성 여부
2. **임베딩 sim**: 후보 top-3의 코사인 유사도 → HIGH(≥0.75)/MID(0.6~0.75)/LOW(<0.6)
3. **인간 판정** (리뷰 시트 `stage43_noans_review.html`, 23건):
   - `spoiled`: 셋 이후 생성 메모리에 실제 답 존재 → **제외**
   - `related`: 주제만 겹침 → 유지
   - `irrelevant`: 무관 → 유지

## 판정 결과 (2026-10-06)

- HIGH/MID 23건 판정: **spoiled 5건 / related 4건 / irrelevant 14건**
- 제외 5건: `nans2_008`(JEV_API_URL), `nans2_009`(Free tier $0.75),
  `nans2_015`(pip uv), `nans2_028`(pool_rank), `nans2_047`(keyring 키 수)
  — 전부 셋 이후 생성 메모리에 실제 답이 생긴 항목
- (11번은 related 유지 — "snippet 윈도우 반영" 보고로 직접 답 아님, 이중 확인)

## 신규 보충 (5건, `nans3_001~005`)

축소 운영(45건)은 하드-네이버 검증 커버리지 축소 → **50건 유지**로 보충.

선정 기준 (기존 셋과 동일 성격):
- 질문 셋과 같은 템플릿형 (시점/규칙/옵션 확인형)
- 코퍼스에 하드-네이버 다수 존재 (FTS 히트: deepseek 39, RRF 55, cron 24, 게이트류 77~186)
- **실제 답 부재를 bekko 전체 1,729벡터 상위 유사도 0.11~0.16으로 검증** (기존 hard 0.7+와 대비)

| qid | 쿼리 | top-1 sim |
|---|---|---|
| nans3_001 | deepseek 모델을 muse로 바꾼 적이 있어? | 0.114 |
| nans3_002 | RRF 가중치를 바꿔본 적이 있어? | 0.118 |
| nans3_003 | cron 작업이 한 번도 실패한 적이 있어? | 0.121 |
| nans3_004 | 게이트가 KEEP 대신 SKIP을 먼저 반환하던 시절이 있었어? | 0.122 |
| nans3_005 | Tailscale 대신 ZeroTier를 쓴 적이 있어? | 0.135 |

## 파일

- `data/golden_noanswer_hard_queries.json` — 50건 (45 hard + 5 fresh, 백업 `.bak_20261006_103054`)
- `data/stage43_noans_snapshot_scan.json` — FTS 스캔 raw
- `data/stage43_noans_sim_scores.json` — 임베딩 sim + 판정 태그
- `stage43_noans_review.html` — 인간 판정 리뷰 시트
- `snapshots/mnemosyne_snapshot_20261006.db` — 평가 기준 스냅샷

## 용도

- **abstain 라벨 문구 재검증** (stage38/39 보류 안건) — 깨끗한 셋 + 스냅샷 기준
- **IDF 필터 재검증** (stage41 보류 안건) — 동일 조건
- **#3 abstain 위치 c0 2×2** — 스냅샷에서 실행
- 향후 평가: 스냅샷 기준 noans + 신규 검증 쿼리 병행