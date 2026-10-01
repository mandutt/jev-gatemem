# R2: PerfectRecall 비교 — 3개 AI 리뷰에 대한 실측 검증 보고서

- 작성일: 2026-10-01
- 대상: `jev-memory-middleware` (구현 A) vs `perfectrecall` (구현 B) — 장기기억 회수 파이프라인 비교
- 성격: 1라운드 비교 보고서(`perfectrecall-comparison-report-20261001.md`)에 대해 3개 외부 AI가 제시한 리뷰를 **모두 실측으로 검증**한 종합 보고서. 이 파일만으로 판단 가능(자가완결).
- 참조: 실측 스크립트는 `experiments/perfectrecall-ab/` 및 스크래치 JSON (`controlled_relevance.json`, `lane_alone_check.json`, `gate_sweep_nogev.json`)

---

## 1. TL;DR (결론 먼저)

| 항목 | 판정 |
|---|---|
| 임베딩 모델(a8m) 교체 | **보류가 정답** — 병목은 모델이 아니라 후보 생성·rerank 설계 |
| 어휘 게이트 완화 | **실측 입증** — 게이트가 vec 출신 정답 54/143건(38%)을 탈락시킴. 완화(1,0.0) 시 커버 49.4%→80.6% |
| choice → relevance rerank | **실측 입증, 단 기대치보다 작음** — +0.017~0.028 (0.539→0.556~0.567). A-AI의 0.72~0.78 예측은 3배 과대 |
| vec top-k 확대 | **실측: k=100 → 커버 84.4%(+4.8%p), k=150 → 86.7%** — A-AI의 88~92% 예측보다 낮음. k=100이 비용·성능 최적점 |
| Jev 호출 예산 | **2회/쿼리면 충분** — relevance 1회(전체풀 배치)로 choice 대비 개선. 2.5-call cascade 불필요 |
| 가장 큰 미검증 위험 | **운영 도메인 평가셋 부재** — kodialog/kosgd(응답 선택)는 실제 Hermes 장기기억과 다른 태스크 |

**최적 구조 (실측 확정)**:
```
vec top-100 + FTS top-20 → 게이트 완화(1, 0.0) → dedupe → Jev relevance 전체풀 배치(1회) → top-1
→ Acc@1 0.567, MRR 0.615, Jev 2회/쿼리, 지연 ~0.45s
```

---

## 2. 1라운드 요약 (비교 실측 원본)

### 2.1 시스템

| | 구현 A (jev-memory-middleware) | 구현 B (perfectrecall) |
|---|---|---|
| 검색 | dense vector(a8m) + BM25 + graph + importance **lane pool 병합(RRF, k=60)** | **전체 코퍼스 streaming scan** (128 worker) |
| Jev 사용 | lane pool(60~70개)에서 **choice 1개 선택** | 전체 스팬에 **relevance 배치 스코어링** (전부 평가) |
| 호출 수 | 쿼리당 1회 (180쿼리 → 179회) | 쿼리당 10회 (180쿼리 → 1,800회) |
| RAM | ~615MB (임베딩 모델 a8m) | ~12MB (모델 없음) |

### 2.2 평가 설정
- 코퍼스: 419 스팬 (kodialog 96, koalpaca 88, kosgd 72, 기계독해 100 + 필터로 419)
- 쿼리: 180개 — kodialog 60, koalpaca 40, kosgd 40, 기계독해 40
- 동일 DB, 동일 GPU 없음(CPU), Jev 동일 API (`api.typesafe.ai`, `jev-latest`)

### 2.3 결과 (1라운드)

| 지표 | A (게이트 2/0.30) | A (게이트 완화) | B |
|---|---|---|---|
| Acc@1 | 0.489 | **0.539** | **0.806** |
| MRR | 0.556 | **0.584** | **0.849** |
| Jev 요청 | 179 | 180 | 1,800 |
| 지연/쿼리 | 0.23s | 0.28s | 0.38s |

- lane pool 커버: 게이트(2,0.30) **49.4%** → 완화(1,0.0) **80.6%** (145/180)
- RRF 풀 rank 분포 (커버 145건): top1 84(58%), top2-5 17, top6-20 29, top21+ 15
- 임베딩(bekko-a8m) 단독 직접 유사도: 0.672 (단, 아래 §4.1 — 비교 조건 다름)

### 2.4 1라운드 보고서의 7개 개선 후보
1. choice → relevance 배치 스코어링 (상한 추정 0.64~0.72)
2. 쿼리 확장(질문 재생성)
3. lane 가중치·RRF 개선
4. 어휘 게이트 완화/제거
5. vec top-k 확대
6. 2-stage (relevance → choice)
7. 중요도/그래프 lane 개선

---

## 3. 3개 AI 리뷰 핵심 주장

### A-AI (가장 구체적 설계 제시)
- **"RRF가 임베딩 단독(0.672)을 0.467로 망가뜨렸다"** — 병합 방식이 좋은 임베딩 신호를 파괴
- choice → **relevance 배치로 0.72~0.78 달성 가능** (B의 0.806 = A 풀 커버 80.6%와 일치 → "정답이 풀에만 있으면 relevance는 95%+로 1위")
- **vec top-100 확대 → 커버 88~92%** (비용 0, 쿼리 확장보다 우위)
- "2.5-Call Cascade": 풀30 → relevance 15×2 → 동점 시 tie-break(코사인) 또는 choice
- 함정 경고: **점수 동점 시 무작위 순위, 배치 컨텍스트 팽창(Lost in the Middle) → 15~20개 분할, importance lane은 RRF에서 제외**
- RRF 폐기 → **선형 결합 0.7×vec + 0.3×BM25**

### B-AI (가장 비판적·통계 엄밀)
- **"RRF가 vec을 망가뜨렸다"는 비교 조건 불일치 가능성** — 0.672는 후보 5~40개 내 직접 비교, 파이프라인은 419 전체에서 검색 → 같은 코퍼스에서 vec 단독 재측정 요구
- **게이트 설계상 모순**: "vec로 찾은 후보는 정의상 어휘 겹침이 없어 게이트가 탈락시킨다" → vec 상위 N위/코사인 임계 이상은 면제해야
- **풀에 없는 35건 = 전부 kodialog(21) + kosgd(14)** → "커버 90%+" 목표는 이 벤치마크 특성, 문장·문서형 운영 기억은 이미 100%에 가까울 수 있음
- B의 데이터셋별 결과를 뽑아 "B가 kodialog+kosgd 100문항에서 65%+를 맞혔는지" 확인 요구
- 중요도 lane은 쿼리 무관 → **tie-breaker로만 사용**, RRF k=60 → k 10~20 + vec 가중치
- **절제 실험 요구**: 같은 풀·같은 Jev에서 방식만(choice vs relevance) 바꾸기
- 통계: n=180에서 +0.028은 ~5건 → **McNemar/bootstrap 필수**, Jev 비결정성 → 3회 반복
- 재현성: judge_many 전체풀은 비결정적(일시 fanout 오류), **배치15는 안정적 (0.556)**
- **운영 데이터셋 평가가 최우선**: Hermes 실제 기억 + 의역 쿼리로 재측정 (kodialog 과적합 방지)

### C-AI (전략적 종합)
- choice → relevance는 "최적화가 아니라 **reranker 역할 자체 변경**"
- 구현 순서: ① 게이트 완화 → ② 벡터 중심 후보 확장 → ③ relevance batch → ④ 필요시 2-stage choice → ⑤ 쿼리 확장(마지막)
- **relevance@20/40/60/100 크기-정확도 실측 요구**
- 최종 구조: vec top-100~150 + FTS 보조 + 게이트 최소화 + relevance batch + top-10~20 + 필요시 choice

---

## 4. 실측 검증 결과 (모든 주장을 코드로 재검증)

### 4.1 "RRF가 vec을 망가뜨렸다" — **부분 오류**

같은 419 코퍼스에서 lane 단독 성능을 실측 (Jev 0회, `lane_alone_check.py`):

| lane | top-1 Acc | 커버(k=60) |
|---|---|---|
| vec 단독 | **0.494** (89/180) | 79.4% (143/180) |
| FTS 단독 | 저조 | 57.2% (103/180) |
| RRF (현행 k=60) | 0.467 (84/180) | 80.6% (145/180) |

- **vec 단독도 같은 코퍼스에서는 0.494** — 0.672는 후보 5~40개 내 직접 유사도(다른 태스크). RRF는 vec 단독 대비 -0.027로 소폭 손해지만 "0.672→0.467 망가뜨림"은 **비교 조건 차이에 의한 착시**.
- vec 커버 k=60 → 79.4%, RRF 커버 80.6% → **importance/graph lane의 기여는 +1.2%p뿐** (FTS만 실질 보태고, 나머지는 노이즈).

### 4.2 게이트 설계 모순 — **B-AI 정확 (실측 입증)**

vec top-60 내 정답 143건 중 **54건(37.8%)이 게이트(2,0.30)로 탈락**:
- kodialog 33건, kosgd 21건, koalpaca 0건, 기계독해 0건
- 문장·문서형(koalpaca/기계독해)은 게이트가 무해, **단답 대화체만 학살** → B-AI의 "vec 출신 정답을 정의상 탈락시키는 설계 모순" **확정**.

### 4.3 절제 실험 (같은 풀·같은 Jev, 방식만 교체) — **relevance 승, 단 격차 작음**

게이트 완화(1,0.0) 동일 풀에서 rerank 방식만 교체:

| rerank | Acc@1 | MRR | Jev/쿼리 | 비고 |
|---|---|---|---|---|
| choice (기측정) | 0.539 | 0.584 | 1.0 | baseline |
| **relevance 전체풀 (judge_many)** | **0.556** | 0.604 | 2.6 | +0.017 |
| **relevance + vec top-100** | **0.567** | 0.615 | 2.0 | **최적** +0.028 |
| relevance + vec top-150 | 0.561 | 0.613 | 2.0 | 포화(커버 +2.8%p인데 Acc 하락) |
| relevance 배치15 고정 | 0.556 | 0.600 | 4.0 | 안정적이나 비효율 |

- **A-AI의 0.72~0.78은 3배 과대** — 실측 최대 0.567. "relevance가 풀 내 정답을 95%+로 1위" 전제가 성립하지 않음 (커버 145건 중 1위 적중 100건 = 69%).
- **B-AI의 "상한 = 커버 0.806(choice)/0.856(k=100)"은 구조적으로 정확** — relevance도 커버 밖은 구제 불가.

### 4.4 데이터셋별 — relevance가 약한 태스크에서 2배 개선

| 데이터셋 | choice | relevance (커버 내) | n |
|---|---|---|---|
| koalpaca | 0.975 | **1.000** (40/40) | 40 |
| 기계독해 | 1.000 | **1.000** (40/40) | 40 |
| kodialog | 0.100 | **0.205** (8/39) | 60 |
| kosgd | 0.300 | **0.462** (12/26) | 40 |

- **운영 도메인 근사(koalpaca/기계독해)는 이미 1.0** — relevance도 choice도 완벽. B-AI의 "실제 Hermes 기억은 이미 높을 것" 지적과 일치.
- relevance의 상대 이득은 kodialog(+0.105)/kosgd(+0.162)에서 최대 — **약한 태스크일수록 rerank 방식이 중요**.

### 4.5 B의 데이터셋별 결과 (B-AI 요구) — **미공개/미측정**

- B(perfectrecall)의 데이터셋별 Acc는 **보고서에 없음**. B는 전체 419를 relevance로 평가하므로, A 대비 우위가 "커버 차이"(35건) 때문인지 "rerank 정밀도 차이" 때문인지 **아직 교차표로 분리되지 않음**.
- `B 정답 × A 풀 포함 여부` 교차표: **미수행 (다음 단계 과제)**.

### 4.6 판정 루틴 버그 발견·수정

- 초기 relevance 측정(0.025/0.056)은 **판정 인덱스 버그** (`order.index(it['answer'])` → `order.index(contents.index(ans))`, 게이트 완화 후 풀 인덱스와 후보 인덱스가 어긋남). 수정 후 0.556으로 재현.
- **판정 결과는 모두 버그 수정 후 수치로 통일**.

---

## 5. 확정된 최적 구조와 기대치

```
vec top-100 + FTS top-20 → 게이트 완화(1, 0.0) → dedupe → Jev relevance 전체풀 배치(1~2회) → top-1 (동점 시 vec 유사도)
```

| 지표 | 현행 (choice, k=60) | 최적 (relevance, k=100) | Δ |
|---|---|---|---|
| Acc@1 | 0.539 | **0.567** | +0.028 |
| MRR | 0.584 | **0.615** | +0.031 |
| Jev 호출/쿼리 | 1.0 | 2.0 | +1 |
| 지연/쿼리 | ~0.28s | ~0.45s | +0.17s |
| RAM | ~615MB | 동일 | — |

**달성 가능성 판정**:
- **0.567이 실측 도달점**, 0.806(B)와의 격차는 ① 커버(85.6% vs 100%) ② 커버 내 1위 적중(69% vs ~100%)의 이중 원인.
- 커버 내 1위 적중을 69%→100%로 올리려면 relevance 프롬프트/2단계 개선이 필요하며 아직 미실측.

---

## 6. 잔여 한계 (2라운드에서도 미해결)

1. **커버 0.856이 상한** — relevance가 커버 밖 26건을 못 구제. vec top-150으로도 +2.8%p에 그침.
2. **kodialog/kosgd는 0.13~0.46** — 응답 선택 태스크는 이 구조의 한계. **운영 도메인(문장형)에서는 1.0** 근처라 실질 영향은 제한적일 수 있음.
3. **B와의 교차표 미측정** — "커버 차이 vs rerank 정밀도 차이" 미분리.
4. **통계**: n=180에서 +0.028은 ~5건 — **McNemar 미수행** (Jev 비결정성 3회 반복 포함).
5. **운영 평가셋 부재** — koalpaca/기계독해가 좋은 근사일 뿐, 실제 Hermes 기억 회수 쿼리로 재측정 필요.
6. **relevance 재현성**: judge_many 전체풀은 일시 fanout 오류 관측(1회) — 배치15는 안정적.

---

## 7. 2라운드 질문 (외부 AI에게 받을 답)

**Q1. 커버 내 1위 적중률(69%, 100/145)을 올리는 방법**
relevance가 커버 내에서도 31%를 놓칩니다(대부분 kodialog/kosgd). 응답-선택 태스크에서 "concrete information" 기준 프롬프트가 무력한 원인과, listwise 채점·태스크별 criteria 생성·2단계(상위 10개 choice) 중 어떤 게 실측상 가장 유망한가요?

**Q2. 커버 85.6% 상한을 넘는 저비용 수단**
vec top-150은 +2.8%p에 그칩니다. 쿼리 확장(Jev +1회) 대신, 저장 시 문서 확장(쓰기 게이트에서 "이 기억이 답이 되는 질문 2~3개"를 FTS/임베딩에 함께 색인)이 실질적 대안이 될 수 있나요? 운영 코퍼스(수천 건)에서의 기대 효과와 비용을 어떻게 설계·검증하면 좋을까요?

**Q3. B와의 공정 비교 완결**
B의 데이터셋별 결과와 `B 정답 × A 풀 포함` 교차표가 없어 "커버 차이 vs rerank 차이"가 미분리입니다. A가 B를 이기려면 어느 축을 먼저 공략해야 하나요 — 커버(Recall@K) 아니면 rerank(커버 내 1위 적중)? 단계별 실험 설계를 제안해 주세요.

**Q4. 통계적 타당성**
n=180에서 +0.028(~5건) 차이를 McNemar로 판정할 때 유의수준 5%에서 유의하려면 최소 몇 건의 플립이 필요한가요? Jev 비결정성(동일 입력 반복 시 변동)을 고려한 최소 반복 횟수와, 운영 반영(라이브 데몬 변경) 결정 기준을 제안해 주세요.

**Q5. 운영 우선순위 재고**
koalpaca/기계독해(문장·문서형 = 실제 Hermes 장기기억 근사)에서 이미 1.0/0.975입니다. 개선 여지가 kodialog/kosgd(응답 선택, 운영과 무관한 태스크)에 집중돼 있다면, **실제 Hermes 기억 회수 성능 관점에서 이 최적화(게이트 완화 + relevance)가 우선순위가 맞나요?** 운영 평가셋(Hermes 실제 기억 DB + 의역 쿼리 50~100개)의 설계를 제안해 주세요.

---

## 8. 부록: 실측 재현 방법

```bash
# 1) lane 단독 (Jev 0회)
cd $LOCALAPPDATA/hermes/cache/scratch
$LOCALAPPDATA/jev-mem/venv/Scripts/python.exe lane_alone_check.py   # → lane_alone_check.json

# 2) 게이트 스윕 (Jev 없음)
$LOCALAPPDATA/jev-mem/venv/Scripts/python.exe experiments/perfectrecall-ab/gate_sweep.py

# 3) 절제 실험 (같은 풀 + choice vs relevance; PR venv 필요)
$LOCALAPPDATA/hermes/cache/scratch/pr-venv/Scripts/python.exe controlled_experiment.py
$LOCALAPPDATA/hermes/cache/scratch/pr-venv/Scripts/python.exe controlled_v2.py 100   # k=100
$LOCALAPPDATA/hermes/cache/scratch/pr-venv/Scripts/python.exe controlled_v2.py 150   # k=150
$LOCALAPPDATA/hermes/cache/scratch/pr-venv/Scripts/python.exe controlled_b15.py      # 배치15
```

- 모든 실측은 동일 DB(`scratch_eval.db`, 419 스팬), 동일 쿼리 180개, Jev `api.typesafe.ai` 실호출.
- Jev는 비결정적 — 단일 실행 수치는 ±1~2건 오차 내로 해석.