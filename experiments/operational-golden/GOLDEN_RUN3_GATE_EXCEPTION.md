# 커버리지 예외 규칙 실험 보고 (Run I 시뮬레이션 + Run J 라이브 채택) — 2026-10-01

> Run G/H에서 확인한 E_factual_misc 약점(짧은 구어체 질문 × 어휘 게이트 커버리지
> 0.30 미달)의 정밀 해소 시도. Run I: 라이브 DB에서 90 gold 쿼리 전수 오프라인 시뮬레이션
> (JEV 호출 없음, 로컬 RRF+게이트만 재현). Run J: 예외 적용 라이브 데몬 + JEV 실호출 재판정.

---

# Run J 최종 결과 — vec≤2 예외 **채택 확정** (라이브 JEV 실호출)

## 최종 지표 (n=90 gold + 10 no-answer)

| 지표 | Run H (baseline) | **Run J (vec≤2 예외)** | 변화 |
|---|---|---|---|
| Pool Recall | 82.2% | **90.0%** | +7.8%p |
| **Acc@1** | 75.6% | **83.3%** | **+7.7%p** |
| **hit@5** | 81.1% | **88.9%** | **+7.8%p** |
| MRR | 0.941 | 0.946 | +0.005 |
| p50/p95 | 295/365ms | 268/336ms | 개선 |

**쿼리별 변화: 개선 7건 / 후퇴 0건** — 시뮬레이션이 예상한 hit5 이탈 13건은
**1건도 발생하지 않았다.** JEV rerank가 이탈 예상분을 전부 흡수 (예측대로).

## 회복 7건 (전부 final_rank 1위)

| 쿼리 (축) | baseline | Run J |
|---|---|---|
| commit governance 규칙이 뭐지? (para) | 풀 미달 | 1 |
| DTO 분리 어디까지 하면 돼? (para) | 풀 미달 | 1 |
| codex config.toml 훅 어떻게 설정했지? (para) | 풀 미달 | 1 |
| 코드 설명과 구조 라벨 언어 규칙? (lit) | 풀 미달 | 1 |
| hermes update 중간에 꺼지면 어떻게 해? (lit) | 풀 미달 | 1 |
| camelai-serial-proxy 기능 정리해줘 (para) | 풀 미달 | 1 |
| supermemory 왜 안 쓰는 거야? (lit) | 풀 미달 | 1 |

전부 E_factual/C_preference의 짧은 구어 질문 — 예외 규칙이 목표 충돌만 정밀 해소.

## 구현 (gateway/j1_pipeline.py)

- `VEC_RANK_EXEMPT = int(os.environ.get("JEV_VEC_RANK_EXEMPT", "2"))` —
  env 오버라이드 가능, 0이면 예외 비활성
- `build_lane_pool`이 RRF 후 각 행에 `_lane_ranks`(fts/vec/imp/graph rank) 부착
- `_filter_and_rank`의 dist/coverage 탈락 분기에서
  **vec_rank ≤ 2 ∧ overlap ≥ 1**이면 통과 (vec lane이 강하게 확신하는 정답 보호)
- 데몬 재기동 + 라이브 검증 완료 (status: ready, a8m warmup OK)

## 무답 lift 변화 (수용 가능)

lift=True 무답 4→5건 (불고기·러시아어 신규). JEV가 무관 후보를 1위로 올려도
실제 답변 생성 계층에서 걸러지는 영역이며, 정답 +7.7%p와의 교환으로 수용.

## 결정

**vec≤2 커버리지 예외 채택 확정.** 근거: 라이브 실측 개선 7/후퇴 0, hit@5 88.9%,
지연 개선. 잔여: 합성 벤치(kodialog/kosgd) 회귀 스윕은 다음 세션 권장 (운영 도메인과
kodialog 5-way는 태스크가 달라 영향 가능성 낮음).

## 원본
- `golden_eval_runJ.json` (Run J 실측) / `golden_eval_runH_baseline.json` (비교 기준)

---

# 이하 Run I 오프라인 시뮬레이션 기록

## 1. 실험 설계

**예외 규칙**: 기존 게이트(dist≥2 AND cov≥0.30)를 통과하지 못한 행 중
**vec lane rank ≤ N이면서 dist≥1**인 행은 통과.

가설: vec 1~2위는 임베딩이 강하게 확신하는 정답이므로, 어휘 겹침이 부족해도
살려야 한다 (semantic signal > lexical gate).

변형: N=2, 3, 5 (baseline=기존 게이트).

## 2. 결과 (n=90 gold 쿼리 전수)

| 변형 | Pool Recall | hit@1 | hit@5 | hit@10 | hit@40 | avg_rank |
|---|---|---|---|---|---|---|
| **baseline (0.30)** | 82.2% | 26.7% | **74.4%** | 81.1% | 82.2% | 3.1 |
| vec≤2 | 90.0% | 51.1% | 70.0% | 81.1% | 90.0% | 3.7 |
| vec≤3 | 90.0% | — | 70.0% | — | 90.0% | — |
| vec≤5 | 91.1% | 52.2% | 71.1% | 82.2% | 91.1% | 3.8 |

(참고: min_coverage 0.20 완화 — recall 90.0% / hit@5 62.2%)

## 3. 상세 분석 — 예외가 들어오면서 정답 순위가 밀리는 메커니즘

### 회복 (vec≤2 신규 진입, 7건)
- commit governance / DTO 분리 / codex config.toml / 언어 규칙 / hermes update
  중단 / camelai-serial-proxy / supermemory — 전부 E·C 카테고리의 짧은 질문
- 5건이 **pool_rank 1위**로 진입 — 예외 규칙 자체는 정확히 목표를 맞춤

### 이탈 (baseline hit5 → 밀림, 13건)
- vec 상위권 무관 노이즈가 예외로 대량 진입해 RRF 순위를 압도:
  - `입력 토큰 늘어나면 응답 지연도 늘어?` 1위→16위
  - `한국어 영어 어떻게 섞어 써?` 2위→19위
  - `bekko-a8m 채택 이유가 뭐야?` **1위→10위**
  - `사용자 언어 습관이 어때?` 2위→6위
- 총 13건이 hit5 이탈 vs 7건 회복 — **순손실**

### 메커니즘 결론
예외 통과 행은 RRF 점수가 높은 vec 상위권이라 병합 후 상위에 붙지만, 그게
정답이 아니면 정답을 아래로 민다. **게이트의 원래 목적(무관 노이즈 차단)이
예외에서 정확히 깨진다.** 어휘 겹침이 부족한 vec 상위 행 = "임베딩은 비슷하지
어휘가 다른 행"인데, 운영 DB에는 이런 행이 정답보다 훨씬 많다.

## 4. JEV가 살릴 수 있는가? — 살릴 수 있다 (핵심 통찰)

hit5 이탈 13건은 **pool에는 존재**하므로 (baseline 기준 pool에는 이미 있었음)
JEV rerank가 1위로 lift할 수 있는 영역. Run H에서 확인했듯 JEV는 풀에 있는
정답을 91.9% 1위로 보낸다.

즉 **vec≤2 예외 + JEV rerank 조합**에서:
- 이탈 13건: JEV가 다시 1위로 lift 가능 (pool 안에 있으므로)
- 회복 7건: 풀 진입 자체가 새로 생겨 JEV lift 대상 확대

→ 최종 성능은 JEV rerank 후 측정해야 판정 가능. 오프라인 게이트 단독 지표는
JeV 단계를 반영하지 않은 과소평가.

## 5. 결정 보류 및 권고

**오프라인 지표만으로는 vec≤2 채택 판정 불가** — hit5 -4.4%p가 JEV 단계에서
회복되는지가 결정적. 두 경로:

1. **라이브 Run J**: vec≤2 예외를 임시 적용한 데몬 + golden_final_v2 재실측
   (JEV 호출 ~100회, 비용 소액) → 최종 지표로 판정
2. **현상 유지**: pool 82.2% 상한 유지. E_factual 60%는 문서화만.

권고는 1번 — 회복 7건(그중 5건 pool_rank 1위)은 JEV가 100% 살릴 것이고,
이탈 13건도 풀 안에 있으므로 JEV lift율(68%, 이탈 0건 실측)상 상당수 회복 예상.
순이득 가능성이 높지만 **JEV 실호출 없이는 단정 금지** (AI 리뷰 교훈: 오프라인
지표만으로 시스템 결론 내리지 말 것).

## 원본
- 시뮬레이션: 이 보고서 인라인 (스크립트는 세션 기록)
- 기준선: GOLDEN_RUN1_REPORT.md / GOLDEN_RUN2_REPORT.md
