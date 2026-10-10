# LongMemEval-S on jev-mem — 실행 결과 보고서

> 작성: 2026-10-10 · 상태: 완료 (결과 확정)
> 설계: `docs/longmemeval/2026-10-10_longmemeval-design.md`
> raw: `experiments/operational-golden/data/stage112~115_*.jsonl` (커밋 대상)

## 1. 실행 요약

| 항목 | 값 |
|---|---|
| 벤치 | LongMemEval-S (ICLR 2025), `longmemeval_s_cleaned.json` 500문항 |
| 파이프라인 | ingest(임베딩 off bulk + 배치 임베딩) → JEV choice 1콜/문항 → deepcombo reader → deepcombo judge |
| JEV 콜 | 500콜 (read-path만) ≈ 2.0M 토큰 (일일 무료 한도 2.1%) |
| 실행 시간 | Full: 4.7시간(ingest) + 8분(judge) / Oracle: 48분 |
| 오류 | **0건** (500/500 완주) |
| 키 | EXPLABS 2키 (xpl_), TYPESAFE 미사용 |

## 2. 메인 결과 (Full haystack)

| 지표 | 값 |
|---|---|
| **전체 정확도** | **24.1%** (119/494 판정) |
| abstention (30문항) | **100.0%** |
| single-session-user (70) | 51.4% (36/70) |
| single-session-assistant (53) | 56.6% (30/53) |
| single-session-preference (29) | 31.0% (9/29) |
| knowledge-update (76) | 26.3% (20/76) |
| multi-session (133) | 9.0% (12/133) |
| temporal-reasoning (133) | 9.0% (12/133) |
| JEV abstain 비율 | 52% (261/500) |
| JEV abstain 257건 중 judge 정답 | 33건 (12.8%) |

## 3. Oracle 상한 (evidence 세션만 제공)

| 지표 | Full | Oracle | Δ |
|---|---|---|---|
| **전체 정확도** | 24.1% | **25.1%** (123/491) | +1.0pp |
| abstention (30) | 100.0% | 96.7% | −1건 |
| 단일-세션-user | 51.4% (36/70) | 54.3% (38/70) | +2.9pp |
| 단일-세션-assistant | 56.6% (30/53) | 53.6% (30/56) | −3.0pp |
| 단일-세션-preference | 31.0% (9/29) | **46.7%** (14/30) | +15.7pp |
| knowledge-update | 26.3% (20/76) | 24.3% (17/70) | −2.0pp |
| multi-session | 9.0% (12/133) | 9.8% (13/133) | +0.8pp |
| temporal-reasoning | 9.0% (12/133) | 8.3% (11/132) | −0.7pp |
| JEV abstain 비율 | 52% (261/500) | **55%** (274/500) | +3pp |

## 4. 결론 (실측 기반)

### 4.1 abstain 임계 조정은 큰 개선 불가 (0콜 시뮬레이션)
- abstain 261건 중 abstain_p ≤ 0.5: **34건(13%)**만 — 임계 하향으로 살릴 수 있는 최대치
- 그러나 abstain 261건 중 **rows top-5에 정답 흔적: 49건(19%)뿐** → 노출해도 정답 불가 81%
- abstain 임계 조정의 상한 ≈ +49건 (24.1% → ~34%) — 절대 개선 아님

### 4.2 검색 레버가 아니다 (Oracle 결과)
- **evidence 세션만 제공해도 정확도 25.1%** — 답이 DB에 분명히 있어도 (oracle recall=완벽) 정확도 불변
- abstain도 55%로 줄지 않음 → **JEV 판정(choice) 단계가 근본 원인**
- 즉 "pool에 답이 없어서"가 아니라 **"JEV가 답 있는 메모리를 usable evidence로 인정하지 않음"**

### 4.3 JEV 단일-best pick 구조의 한계
- multi-session(9.0%)·temporal-reasoning(9.0%)은 **oracle에서도 바닥** — 답이 여러 세션에 분산/시간 합성 필요
- JEV read-path는 "단일 최적 메모리 1개"를 고르도록 설계됨 → 합성형 질문에 구조적으로 불리
- abstention(정직 거부)은 Full 100%·Oracle 96.7% — **우리 설계의 강점은 유지**

### 4.4 라이브와 벤치의 환경 차이
- 라이브 데몬: abstain 7% (유사 메모리가 항상 존재, 답이 곧바로 있는 규칙/사실 질문)
- LongMemEval: filler 중심 haystack → JEV가 "바로 쓸 메모리 없음" 판정이 잦음
- **JEV read-path는 "답이 단일 메모리에 있는" 라이브 환경에 최적화된 설계** — 합성/시간 추론 벤치 지표(9%)는 구조적 한계로 수용

## 5. 산출물

| 파일 | 내용 |
|---|---|
| `stage112_lmev_results.jsonl` | Full 500문항 결과 (question/answer/jev/hypothesis) |
| `stage113_lmev_judged.jsonl` | Full judge 판정 500건 |
| `stage115_lmev_oracle_results.jsonl` | Oracle 500문항 결과 |
| `stage115_lmev_oracle_judged.jsonl` | Oracle judge 판정 500건 |
| `stage110_lmev_smoke.py` | 스모크 러너 |
| `stage112_lmev_serial.py` | Full 실행 러너 (단독 프로세스) |
| `stage115_lmev_oracle.py` | Oracle 실행 러너 |

## 6. 후속 방향 (보류)

1. **read-path 구조 변경은 불가** — JEV choice는 단일-best pick이라 합성형 질문 대응 위해선 choice 구조 자체 변경 필요 (운영 회귀 위험, 사용자 원칙상 보류)
2. **벤치 선택 조정** — LongMemEval은 "추출형 단일 메모리" 중심이라 JEV read-path 평가에는 부적합. 향후 벤치는 **추출형/규칙형 질문 위주** (예: 라이브 쿼리 스냅샷 기반 회귀 셋) 또는 **abstention 포함 단일-세션 벤치** 지향
3. **canary/회귀 셋과의 정합** — abstention 100%·single-session 51~57% 수치는 라이브 회귀 셋(L2 YES/NOANS)과 다른 축이므로, **벤치 결과를 운영 튜닝에 직접 반영하지 않음** (라이브가 SoT)