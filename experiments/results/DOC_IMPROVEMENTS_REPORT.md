# 문서 기반 개선 실험 보고서 — TypeSafe 공식 문서 대조 (2026-09-27)

## 1. 배경

Phase 1에서 J1 (Jev choice lift, recall@1 0.654, mrr 0.747)을 채택했다.
TypeSafe 공식 문서 (docs.typesafe.ai)를 참고해 4가지 개선점을 실험·검증했다.

## 2. 참고한 문서

- Introduction (System One 모델 개념, 3 primitives)
- Choice / Score / Noul (질문 타입별 상세)
- Confidence (확신도 3분할 라우팅)
- State (구조화된 state 권장)
- Confidence-gated routing 패턴 (low confidence → fallback)
- Re-ranking 쿡북 (Noul per pair, top-1 5%→18%)
- Line-by-line search 쿡북 (Choice probabilities를 relevance로)
- Models (jev-latest = jev-1.13.0, $42/Btok, 64k context, **CJK 지원 제한**)

## 3. 실험 설계

- 데이터: 52개 쿼리 (기존 curated dataset), snapshot DB (766 rows)
- 기준: A (lane RRF), J1 (choice lift) — Phase 1 결과
- 개선안:
  - **C_p**: Choice probabilities 전체 분포로 정렬 (semantic_find 방식)
  - **J1c**: confidence ≥ 0.6일 때만 choice lift (confidence-routing 방식)
  - **N**: 후보별 Noul 질문 1개, noul 값으로 정렬 (rerank 쿡북 방식)
  - **B100**: budget 40 → 100 전체 (Choice 255 옵션 한도 활용)
- 실행: `run_doc_improvements.py` — 쿼리당 Choice 1회 + Noul 1회, 52쿼리 전부 실제 API 호출

## 4. 결과 요약

| metric | A | C_p | **J1** | J1c (conf 0.6) | N | B100 |
|---|---|---|---|---|---|---|
| recall@1 | 0.452 | 0.452 | **0.654** | 0.654 | 0.183 | 0.654 |
| recall@3 | 0.606 | 0.606 | **0.750** | 0.702 | 0.577 | 0.750 |
| recall@10 | 0.760 | 0.760 | 0.760 | 0.760 | 0.683 | 0.760 |
| mrr | 0.599 | 0.599 | **0.747** | 0.735 | 0.417 | 0.747 |
| ndcg@10 | 0.618 | 0.618 | 0.732 | 0.720 | 0.473 | 0.732 |

### 유형별 recall@1

| type | n | A | J1 | J1c | N |
|---|---|---|---|---|---|
| causal | 8 | 0.500 | 0.625 | **0.750** | 0.125 |
| factual | 12 | 0.542 | 0.625 | **0.708** | 0.167 |
| failure | 9 | 0.611 | 0.611 | **0.722** | 0.167 |
| preference | 5 | 0.000 | 0.200 | 0.200 | 0.000 |
| project | 11 | 0.455 | **0.909** | 0.636 | 0.182 |
| temporal | 7 | 0.357 | **0.714** | 0.714 | 0.429 |

## 5. 개선점별 판정

### 개선점 2: Choice probabilities (C_p) — ❌ 무효
- 결과가 A와 **완전 동일** (0.452)
- 원인: 우리 후보 풀에서 choice probabilities가 c0=1.0, 나머지 0.0의 **극단 분포**
- semantic_find 쿡북의 218개 라인은 고르게 분포했지만, 우리는 뚜렷한 우위 후보가 있어 뾰족
- **probabilities는 "1위가 얼마나 확실한지"만 알려주고 전체 순위 재정렬에는 무용**

### 개선점 3: Confidence-gating (J1c) — ⚠️ 유형 선택적 유효
- 전체 recall@1 = J1과 동일 (0.654), mrr 소폭 하락 (0.735)
- **유형별로는 causal/factual/failure에서 J1보다 우수**:
  - causal 0.625 → 0.750 (+0.125)
  - factual 0.625 → 0.708 (+0.083)
  - failure 0.611 → 0.722 (+0.111)
- **단 project에서 크게 하락**: 0.909 → 0.636 (−0.273)
  - Jev가 project 유형에서 고신뢰(conf ≥ 0.6)로 맞히는 케이스를 conf-gating이 차단
- **결론**: conf-gating은 "Jev가 불확실할 때 lane 유지"가 유리한 유형(causal/factual/failure)과
  "Jev가 확실할 때 lift"가 유리한 유형(project)이 갈림

### 개선점 1: Noul rerank (N) — 🔴 최악
- recall@1 0.183, mrr 0.417 — **A(0.452)보다 2.5배 나쁨**
- 원인: Noul 값이 후보 간 변별력 부족 (0.3~0.4 수준으로 몰림), 상위 랭킹이 잘못됨
- rerank 쿡북은 영어 법률 문서에서 성공했지만, **한국어 memory에서는 실패**
- **Models 문서의 "CJK는 영어보다 정확도 낮음" 경고가 실제로 확인된 사례**

### 개선점 4: Budget 100 (B100) — ❌ 무효
- J1과 완전 동일 (0.654) — budget 40에서 이미 최적 선택
- Choice 255 옵션 한도는 여유지만, 후보 100개 전체를 봐도 선택 결과 동일

## 6. 최종 결정

**J1 (Jev choice lift) 유지** — recall@1 0.654, mrr 0.747로 최적.

- 개선점 3 (conf-gating)은 유형별 상충(trade-off)이 있어 단일 전역 설정으로 채택하지 않음
- **향후 데이터가 충분히 쌓인 뒤(예: 2,000+ rows) 유형별 하이브리드 재검토 권장**:
  - project/temporal/preference → J1 (conf 무관 lift)
  - causal/factual/failure → J1c (conf ≥ 0.6일 때만 lift)
- Noul 기반 rerank는 한국어에서 실패했으므로 재실험 시 영어 변환 여부 등 별도 설계 필요

## 7. 재현 방법

```bash
cd C:/Users/mandu/hermes-made/jev-memory-middleware
# 전체 실험 (52쿼리, Choice 1회 + Noul 1회/쿼리)
./.venv/Scripts/python.exe -m experiments.run_doc_improvements \
  --out experiments/results/doc_improvements_full.json
# 집계만 (재호출 없음)
./.venv/Scripts/python.exe -m experiments.aggregate_doc
```

결과 파일: `experiments/results/doc_improvements_full.json`

## 8. API 동작 프로브 결과 (추가 발견)

- **Noul ×10: 10개 전부 답변** (0.3초) — 다중 질문 1회 요청 정상 동작
- **Score ×3: 3개 전부 답변** — 이전 "score는 2개만 답한다" 발견은 특정 조건(긴 criteria?)의 문제였을 수 있음
- **Choice: probabilities 8~100개 전부 반환**, confidence 제공
- 다중 질문 1회 요청으로 Noul 52×40 = 2,080 질문을 52회 호출로 처리 가능 (비용 효율)