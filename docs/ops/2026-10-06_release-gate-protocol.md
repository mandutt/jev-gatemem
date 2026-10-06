# 릴리스 게이트 프로토콜 — jev-mem 파이프라인 (2026-10-06 확정)

> 3종 AI 검토(A/B/C-보류3건+abstain무력 v2)의 공통 권고를 운영화.
> 파이프라인 변경(코드·프롬프트·게이트·excerpt·구조) 시 아래 게이트를 통과해야 반영한다.

## 게이트 구성 (3단)

| 단계 | 셋 | 콜 | 기준 |
|---|---|---|---|
| 1. 골든 회귀 | op 90 + snapshot noans 50 | 140 | hit@1 ≥ 74 (기준선), noans FP ≤ 27+비결정성(±3) |
| 2. 라이브 회귀 | live 60 (시점 필터) | 60 (1-run) / 180 (3-run) | **IRREL abstain ≥ 5 (차단)** + **YES_MISS/VALID 희생 ≤ 1** |
| 3. 3-run 확정 | 지표 경계 케이스 | 2×셋 | JEV 비결정성(±3~5) 내 확인 |

- **셋**: 스냅샷 `snapshots/mnemosyne_snapshot_20261006.db` (1,721+113행, 불변) + 라이브 60 시트(사용자 판정 49c)
- **러너**: `experiments/operational-golden/regression_live60.py` (라이브 60, 시점 필터 내장)
- **시점 필터**: `created_at < 2026-10-05` — stage49b에서 라이브 재생의 전제로 확정 (자기참조 누수 방지)

## 배경 실측 (이 게이트가 왜 이 기준인가)

1. **라이브 60 교차 (stage48)**: abstain 0/60 — 라이브 무답에 abstain 무력. 도입 후 그대로 회귀하는지 측정.
2. **라벨 보강 (stage49c)**: no 22건 = IRREL 15 / PLAUS 2 / **VALID 5** (규칙형 — 오히려 정답), yes 35건 top-5 정답 16.
3. **pool-in-pool (stage49d)**: yes-NO 21건 전부 IN (답이 rank 6~60) — rerank 실패 축.
4. **Noul 실험 (stage50/50b)**: 골든 noans(0.26)는 τ<0.5로 FP 50→8, 라이브 IRREL(0.91)은 분리 불가.
   → 라이브 축 합격선은 Noul 기준으로 못 만든다. **현행 기준선 0건 차단·0건 희생을 보수적 문턱으로**:
   변경이 이 수치를 유지하면 회귀 없음, IRREL 차단이 생기면 개선.
5. **u_true = 29.8%** (IRREL+PLAUS 17/57) — 무답이 라이브의 ~30%.

## 운영 지표 (KPI, noans FP 대체)

- `query_log` abstain율 + pool_n 분포 (데몬)
- **월간 라이브 샘플 라벨링**: trace에서 쿼리 60건 → 사람 yes/no/maybe → u_true·실제 FP율·h 추적
- snapshot noans FP는 **회귀 스트레스 테스트로만** (운영 KPI 금지 — stage49c/d가 셋 의존성 입증)

## 미결 (외부 AI 답변 대기, 2026-10-06)

- noul_top<0.5 게이트를 골든셋 방어로만 추가하는 부분 채택 (noans FP 50→8, op −5)
- 판정자 교체 (일반 LLM 금지 원칙 재검토)
- 요청서: `docs/review/2026-10-06_external-ai-review-request_라이브무답차단한계.md`