# Phase 1 실험 보고서 — Jev Choice Rerank (TypeSafe System One)

작성일: 2026-09-27
프로젝트: `jev-memory-middleware` (Mnemosyne + Jev memory middleware)

## 1. 실험 개요

| 항목 | 값 |
|---|---|
| 목표 | Mnemosyne 후보 풀에 Jev rerank를 적용해 recall 상승 검증 |
| 데이터셋 | 52개 쿼리 (factual 12, project 11, failure 9, causal 8, temporal 7, preference 5) |
| Snapshot DB | `snap-20260927.db` (766 working_memory rows, VACUUM INTO) |
| 후보 풀 | Lane pool (FTS 60 + vector 60, RRF k=30) → top-100 |
| Jev API | TypeSafe 직접 `POST https://api.typesafe.ai/v1/systemone`, model `jev-latest` |
| 질문 방식 | choice (후보 중 단일 best 선택, confidence/probabilities 반환) |
| 비용 | 52쿼리 × 1~3회 호출, 쿼리당 ~0.2~0.7초, 총 156회 호출 35초 |

## 2. 핵심 결과

### 최종 비교 (전체 pool 기준)

| metric | A lane RRF | **J1 Jev choice** | J3 (3 picks) |
|---|---|---|---|
| **recall@1** | 0.500 | **0.712** (+21.2pp) | 0.712 |
| **recall@3** | 0.750 (시뮬) | 0.750 | 0.750 |
| recall@10 | 0.760 | 0.760 (pool 한계) | 0.760 |
| **mrr** | 0.599 | **0.747** (+14.8pp) | 0.744 |
| **ndcg@10** | 0.618 | **0.732** (+11.4pp) | 0.730 |

*J1 = Jev choice 1회로 선택된 후보를 rank 1로 lift, 나머지는 lane pool 순서 유지.*

### 유형별 recall@1 (A vs J1)

| type | n | A | J1 | Δ |
|---|---|---|---|---|
| project | 11 | 0.455 | **0.909** | +45.4pp |
| temporal | 7 | 0.429 | **0.857** | +42.8pp |
| causal | 8 | 0.625 | 0.750 | +12.5pp |
| factual | 12 | 0.583 | 0.667 | +8.4pp |
| failure | 9 | 0.667 | 0.667 | 0 |
| preference | 5 | 0.000 | 0.200 | +20.0pp |

*lane +20pp 이상 개선*. project/temporal 유형에서 특히 강력.

## 3. 실험 과정에서 발견한 Jev의 동작 특성

1. **score 질문은 무용**: TypeSafe System One은 요청당 최대 2개 question만 답변 (batch 3/5/8 모두 answers=2). 40개 후보 스코어링 불가. 게다가 0~3 (또는 0~5) score가 상단에 몰림 → 순위 변별력 없음.
2. **choice 질문이 정답**: 전체 후보 중 "best 1개" 선택은 confidence 0.98, 확률 분포까지 반환. 한 요청에 후보 40개 포함 가능.
3. **비결정성**: 동일 입력·동일 프롬프트로 재실행 시 선택이 달라짐 (q110/q148이 이전 miss → 재실행에서 gold 선택). 이는 Jev 확률적 특성.
4. **excerpt 길이 무관**: 120/300/500자 모두 동일 선택 (q149/q150). 답변 결정에 excerpt 길이는 영향 없음.
5. **중요도 가중 효과 없음**: Jev choice + importance 조합은 recall@1 개선 못함 (J1L1 = J1과 동일).

## 4. miss 4개 분석

| 쿼리 | gold pool rank | Jev 선택 | 원인 |
|---|---|---|---|
| q110 (causal) | 0 | rank5 | 비결정성 (재실행 시 gold 선택 성공) |
| q148 (factual) | 1 | rank7 | 비결정성 (재실행 시 gold 선택 성공) |
| q149 (factual) | 0 | rank1 | 구조적: "언제 시작해?" 에 대해 "reap orphan gateways"가 더 직접적으로 보임 |
| q150 (failure) | 0 | rank5/2 | 구조적: "max_tokens 0자" 키워드가 gold excerpt에 없음 — 포괄적 실험 기록이 구체적 후보에 밀림 |

**결론**: miss 4개 중 2개는 Jev 비결정성(재실행 시 회복), 2개는 구조적 한계 (프롬프트·excerpt 개선으로 해결 불가).

## 5. 시도했으나 개선 실패한 방법

| 방법 | 결과 |
|---|---|
| score 질문 (0~3, 0~5 척도) | 요청당 2개 답변 한계 + 점수 몰림 → 무용 |
| Jev 단독 rerank (B) | lane 순서 정보 상실 → recall@1 0.135 |
| RRF(Mnemosyne, Jev) (C k=10~60) | 0.327 — Jev 점수가 잡음 |
| Jev pick + lane top-2 병합 (M2/L2J/L3J) | recall@1 0.500 — Jev가 맞힌 다수를 2위로 밀어냄 |
| 프롬프트 개선 ("포괄적 답 강조") | q149/q150 불변 |
| excerpt 120→500자 | q149/q150 불변 |

## 6. 최종 채택안: J1 (Jev choice lift)

```
retrieve: query → LanePool (FTS 60 + vec 60, RRF k=30) → top-100
rerank:   Jev choice 1회 → 선택 후보를 rank 1로 lift, 나머지 pool 순서 유지
```

- **이득**: recall@1 0.500→0.712, mrr 0.599→0.747, ndcg@10 0.618→0.732
- **비용**: 쿼리당 Jev 호출 1회 (≈0.25초), API 비용 소량
- **한계**: pool 밖 gold 10개 (구조적, Jev로 해결 불가), Jev 오판 2~4개 (비결정성+구조적)

## 7. 후속 제안 (Phase 2+)

1. **Hermes recall middleware 통합**: gateway.py에 J1 rerank 파이프라인 연결
2. **비결정성 완화**: Jev choice 2~3회 반복 후 다수결, 또는 confidence 하한 설정
3. **pool 개선**: FTS/vec lane 외 graph/fact lane 추가로 pool 밖 10개 회수 시도
4. **중요도/recency 반영**: Jev choice가 중요도 낮은 신규 memory를 과대평가하는 경향 보정

## 7.5 문서 기반 개선 실험 (2026-09-27 추가)

TypeSafe 공식 문서를 대조해 4가지 개선을 실험했다 (상세: `DOC_IMPROVEMENTS_REPORT.md`):

| 개선 | 방법 | 판정 |
|---|---|---|
| Choice probabilities 정렬 | semantic_find 방식 | ❌ A와 동일 (분포 극단) |
| Confidence-gating | conf<0.6이면 lane 유지 | ⚠️ causal/factual/failure +, project − |
| Noul rerank | rerank 쿡북 방식 | 🔴 recall@1 0.183 (한국어에서 실패) |
| Budget 100 | 255 옵션 활용 | ❌ J1과 동일 |

**최종: J1 유지.** 데이터가 더 쌓인 뒤 유형별 하이브리드 (project→J1, causal/factual/failure→J1c) 재검토 권장.

## 8. 재현 방법

```bash
cd C:/Users/mandu/hermes-made/jev-memory-middleware
./.venv/Scripts/python.exe -m experiments.run_phase1_v2 --budget 40 --picks 3 \
  --out experiments/results/phase1v2_picks3.json
# 분석
./.venv/Scripts/python.exe -m experiments.analyze_merge2
```

결과 파일: `experiments/results/phase1v2_picks3.json`