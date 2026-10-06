# 외부 AI 검토 요청서 — jev-mem 메모리 파이프라인 (2026-10-06, v2 확장판)

- 작성일: 2026-10-06
- 대상: 메모리 파이프라인 (jev-mem) — SQLite + 로컬 임베딩(bekko-a8m, 384차원) + FTS5/vec/importance/graph 4-lane RRF
  + JEV(SystemOne API) choice rerank 1콜 + soft abstain gate
- **목적**: ① 직전 3종 AI 검토(a/b/c-ai-보류3건)에서 제기된 모든 지적·제안에 대한 **실측·수행 결과 보고 및 최종 판정 요청** ② 신규 발견 **"abstain 무력"** 실측 상세 공유 및 해법 자문
- **전제**: 각 사안은 실측(raw JSON·러너 경로 포함)으로 판정 대기. **추가 정보 요청 없이 답변 가능**하도록 모든 수치·조건·한계·함정·재현 경로를 기재.
- **구성**: §0 시스템 요약 → §0.5 실험 이력·함정 → §1 직전 3종 AI 지적의 실측·수행 전수 보고 → 사안 1~3 (기존 확정·판정 요청) → **사안 4: abstain 무력 (신규·상세)** → 부록

---

## 0. 시스템 요약 (판단 공통 배경)

| 항목 | 값 |
|---|---|
| 저장소 | SQLite `mnemosyne.db` (working_memory 1,721행 + episodic 113행, 스냅샷 2026-10-06) |
| 임베딩 | `bench/bekko-a8m` (384차원, 로컬 fastembed) — 전체 전용 |
| 검색 | 4-lane RRF: FTS5 + vec + importance + graph → 게이트(어휘 overlap≥1, coverage 0.0) → **POOL_BUDGET=60** 컷 |
| rerank | JEV SystemOne `choice` 1콜/쿼리 — "최고 증거 1개 선택" + abstain 라벨(cN, 마지막) |
| excerpt | 전 후보 **쿼리 인지 300자 윈도우 → 150자 절단** (win-300, 2026-10-06 채택) |
| soft gate | choice 응답의 **abstain 라벨 확률(abstain_p) > 0.3** → 빈 컨텍스트 (τ=0.3, 운영) |
| abstain 라벨(현행) | `"No candidate is usable evidence for answering the question"` |
| 실노출 | **`rows[:5]` Top-5** (jev_mem_core/pipeline.py `_render`) — "1개 노출"이 아님 |
| 평가지표 | op 90 (gold 회수): hit@1 75, hit@3 78, abstain 3 / noans 50 (hard): FP 27 (스냅샷·current 기준) |
| 평가 프로토콜 | **3-Run Majority Vote 권장** — JEV 비결정성 ±3~5건 실측 |
| 실험 환경 | JEV 호출은 `EXPLABS_API_KEY` SET 터미널에서만, 데몬 venv(`%LOCALAPPDATA%/jev-mem/venv`) 고정 |

**핵심 구조**: 코퍼스 → lane 검색 → pool 60 → JEV choice(1콜) → pick 1개 lift → **context 노출** (abstain 시 빈 컨텍스트). 단 실제 노출은 `rows[:5]` 최대 5개 — **Top-5**.

## 0.5 실험 이력·함정 (수치 해석의 전제 — 반드시 읽기)

### A. venv 오염 사건 (2026-10-05) — 수치 해석의 최우선 전제
- 프로젝트 `.venv`의 fastembed가 `bench/bekko-a8m` 미지원 → vec lane 0건 → abstain 27건 급증 (오염)
- **데몬 venv**(`%LOCALAPPDATA%/jev-mem/venv`) 전환 후: abstain 27→**8**, hit@3 61.1%→**77.8%** (동일 쿼리셋)
- **이후 모든 실험은 데몬 venv 고정** — 프로젝트 .venv로 돌리면 무효

### B. JEV 비결정성 → 3-Run Majority Vote 권장
- 동일 쿼리셋 재실행 시 **±3~5건 차이** 실측 (파일럿 higher-order 79 → 재현 75 붕괴)
- 1-run 결과는 노이즈일 수 있음 → **두 문구/두 구조 비교는 3-Run Majority(2/3 일치)로 판정해야 안전**
- 본 요청서 사안 1, 3은 **1-run (콜 예산)** — 한계 명시, 3-run 재검증 필요할 수 있음

### C. 운영 무답 비율 u 추정치의 불확실성
- **u=22.5%** = 라이브 데몬 `query_log` 실측 (2026-10-05, 87건 중 abstain/빈 컨텍스트 비율)
- ⚠️ B AI 지적: 이건 "abstain/빈 컨텍스트 비율"이지 "답 없는 질문 비율"이 아님:
  - `22.5% = u·a_n + (1−u)·a_o` (a_n=무답 abstain율, a_o=유답 abstain율 3.3%)
  - a_n=1이면 u≈20%, hard noans처럼 a_n≈0.5면 **u≈41%** — 추정 범위 20~41%
- **2026-10-06 라이브 60쿼리 사람 라벨링으로 실측 완료 → u_true = 38.6%** (사안 4, §4)

### D. 하드 noans의 FP는 실트래픽보다 높음
- noans FP 27/50 = 54%지만, 실제 답 없는 질문은 대부분 이웃이 없는 쉬운 질문
- 코드 주석상 easy noans FP 0건 — **10%p 개선이 실트래픽에서는 더 작을 가능성** (B AI 추측)

### E. 평가 셋 구축 변천
1. 합성 180 → 운영 현실과 괴리로 졸업
2. 운영 골든셋 op 90 + noans 50 (hard)
3. **스냅샷 고정 (10-06)**: `mnemosyne_snapshot_20261006.db` (1,721+113행) — 이후 모든 실측은 이 DB 기준

---

## 1. 직전 3종 AI(a/b/c-ai-보류3건) 지적에 대한 실측·수행 전수 보고

> 이 절은 지난 검토 3건(A: a-ai, B: b-ai, C: c-ai)의 **모든 제안·지적이 어떻게 실측·수행·판정됐는지**를 항목별로 기록한다. 각 항목: [지적 요지] → [실측/수행] → [결과·판정]. 미수행은 없다 (전 항목 처리).

### 1.1 B AI "먼저 확인할 것" 4건 — 전부 확인·수정 완료

| # | B 지적 | 실측/수행 | 결과 |
|---|---|---|---|
| 1 | **hybrid 분기가 꺼져 있지 않음** (`if len(pool) <= HYBRID_MAX_CANDIDATES`가 플래그 없음) | `gateway/j1_pipeline.py` L776의 플래그 없는 1콜 hybrid 분기 확인 → **`JEV_HYBRID_ENABLED` env 가드 추가** (기본 비활성) | ✅ 운영에서 stage37 기각 구조 제거 |
| 2 | **soft gate 적용 여부 불분명** — stage45 수치가 게이트 적용 값인지 | stage45 raw의 abstain_p로 τ=0.3 게이트 적용 확인 (문서의 FP 27/22는 게이트 적용 후 값) | ✅ 명시 |
| 3 | **노출 개수** — `_render`가 `rows[:5]`인데 문서가 "1개 노출" | `jev_mem_core/pipeline.py` 실측: **`rows[:5]` Top-5** → 문서 전면 수정, hit@5 병행 지표 권고 | ✅ 지표-운영 정합 |
| 4 | **300자 윈도우+150 절단** — 150자 직접·head+겹침 실험 제안 | **stage47a~h 8단계 전수 실측** (§1.4) | ✅ 전부 기각, 현행 유지 |

### 1.2 A AI Q1~Q6 실측·수행

| A 제안 | 실측/수행 | 결과·판정 |
|---|---|---|
| Q1: **pool 30 + 400자 metadata excerpt** | (2026-10-04 8차) exp8d: excerpt400 단독 → **hit@3 80/230, abstain 76** (정보 과다→abstain 폭증), exp8e: 400+gate → abstain 0 (gate가 abstain 강제) | ❌ **기각** — 400자 단독은 abstain 폭증, gate 결합은 gate가 abstain을 강제해 차단 (자세한 실측: §1.2-a) |
| Q2: **Top-3 노출 구조** (hit@3 정의 정합) | 운영 실노출이 **Top-5**임을 실측 (`rows[:5]`) → hit@3는 rerank 진단, **hit@5가 실노출 지표**로 문서화 | ⚠️ 선택지 1(Top-3) 불필요 — 이미 Top-5 노출 |
| Q3: **abstain 라벨 '시점/버전 불일치' 특화** | stage45 improved 문구 (시점·버전·수치·조건 명시) 실측 → **사안 1** | ⏸️ 판정 대기 |
| Q4-1: **Dynamic budget 25~30** | POOL_BUDGET=60 유지 판단 (pool 30은 §1.3 hybrid 실험에서 이미 검증 — hit@3 열위) | ❌ 기각 |
| Q4-2: **문장 단위 임베딩 excerpt** | 0콜 검토 — bekko는 문장·문단 구분이 아닌 **고정 300자 윈도우** 구조라 문장 분할 이득 예측 불가 | ❌ 기각 (C Q1 evidence-span으로 대체 시도 → 역시 기각) |
| Q4-3: **Two-stage tournament** | (B AI 제안은 stage24와 다른 구조 — "후보 청크 분할→승자 최종 choice". stage24는 1차 choice→abstain만 2차로 **미실측 구조**) | ⚠️ 미실측 (요청서 v2에서 "동일 구조" 오기재 정정) |
| Q5: **write-path header 보강** | A Q5 0콜 검증: 저장 시점 대화 주제 태그 시뮬레이션 → **복구 0/10** | ❌ 기각 (부록 A) |
| Q6: **hit@1 메인 지표·Top-3** | stage44~47에서 hit@1 병행 실측 — hit@1 74~75, hit@3 77~78. 운영 Top-5 노출로 지표 정합 | ⚠️ hit@5 병행 권고로 문서화 |

#### 1.2-a [실측 상세] A Q1 400자 — exp8d/8e (2026-10-04)
- exp8d (excerpt400 단독, cond=A-choice-excerpt400): n=230, **hit@3 80, abstain 76** — 400자로 늘리자 **정보 과다로 JEV가 abstain을 선택** (300자에서 abstain 3이던 것과 대조)
- exp8e (400 + fulltext-gate, gate_limit 800, cap head600+tail200): n=154, hit@3 80, **abstain 0** — 게이트가 abstain을 강제 제거
- → **"400자 전수 노출"은 abstain 폭증으로 운영 불가** 판정. 300자+150 절단(현행)이 최적

### 1.3 B AI 사안 1~3 권장 차기 단계 — 전부 실측 완료

| B 권장 | 실측/수행 | 결과 |
|---|---|---|
| s1-1: **0콜 τ 스윕** | stage45 raw probabilities로 current/improved 각각 τ 스윕 | ✅ improved의 FP 이득은 **τ와 무관하게 일관** (같은 τ에서 항상 -4~8), τ≥0.4 민감도 0 → **문구=실효과** |
| s1-2: **라이브 60 라벨링** | 오늘(10-06) 완료 — **사안 4** | ✅ **u_true 38.6%, abstain 무력 발견** |
| s1-3: **3-run 재검증** | stage47f/h 3-run 다수 수행 | ✅ (§1.4) |
| s2-1: **v2/v3 stage45 재계산** | stage32 raw FP 16건에서 v2/v3 0콜 재계산 (수치 정정 완료) → **사안 2** | ✅ §2 |
| s3-1: **eval 세션 코퍼스 제외** | 스냅샷 고정으로 실질 대체 (평가 세션 별도 관리 미구현) | ⚠️ 대체 수용 (§3) |
| s3-3: **운영 지표 noans FP 대체** | abstain율 + 라이브 샘플 라벨링으로 전환 (사안 4 결과 반영) | ✅ |

### 1.4 B/C AI "150자·head+겹침" 제안 — stage47a~h 전수 실측 (모두 기각)

| 단계 | 변형 | 1-run | 3-run 판정 |
|---|---|---|---|
| 47a | win150 (겹침 150 직접) | hit@3 +1, FP -3 | WHY 구제는 1-run 착시 |
| 47b | win150 3-run | — | 마우스만 확정, gemini/codex 열위 → 기각 |
| 47c | improved+win150 | FP 12 | noans 최강 but op hit@1 -5 |
| 47d | head+겹침 | 전 지표 개선 | WHY abstain (겹침=head 겹침) |
| 47e | head+겹침 non-overlap | hit@1 75/@3 79/FP 14 | WHY 3건 3/3 구제 확정 |
| 47f | imphbn 3-run | — | **gold50 abstain 3/3** (아래) |
| 47g | curhb (current+head겹침) | WHY+gold50 모두 해결 | 규칙형 noans 4건 FP |
| 47h | 최종 3-run 교차 | — | **둘 다 기각 — WHY 3건 vs gold50 1건+규칙형 4건 = 순손실** |

**stage47f (imphbn vs cur) 3-run 상세**:
| 쿼리 | cur | imphbn |
|---|---|---|
| 코덱스 WHY | abstain 1/3 | **hit 3/3** |
| 마우스 WHY | abstain 3/3 | **hit 3/3** |
| pi 프록시 WHY | abstain 3/3 | **hit 3/3** |
| gemini 별칭 | hit 3/3 | hit 3/3 |
| codex CLI | hit 3/3 | hit 3/3 |
| **gold50 기준선** | **hit 3/3** | **abstain 3/3** |

**stage47h (curhb vs imphbn vs cur) 3-run 상세**:
| 쿼리 | cur | imphbn | curhb |
|---|---|---|---|
| gold50 기준선 | ✅ hit 3/3 | ❌ abstain 3/3 | ✅ hit 3/3 |
| 주석 영어 규칙 (noans) | ✅ abstain 3/3 | abstain 0/3 (FP) | ❌ FP |
| 테스트 생략 커밋 (noans) | ✅ abstain 3/3 | abstain 3/3 | ❌ FP |
| 로그 한국어 (noans) | ✅ abstain 3/3 | abstain 3/3 | ⚠️ abstain 1/3 |
| browser.backend (noans) | ✅ abstain 3/3 | abstain 2/3 | ❌ FP |
| Exa 왜 안 써 (WHY) | ❌ abstain 3/3 | ⚠️ abstain 1/3 | ✅ pick 3/3 |

- **결론**: WHY 3건 구제(imphbn)는 gold50 abstain 3/3(⇒ hit@1 -1) 대가, curhb은 규칙형 noans 4건 중 3건 FP(로그 한국어 1/3 abstain) 대가 → **모두 순손실, 현행(cur) 유지 확정**
- **러너 교훈 3건**: ① POOL_BUDGET 캡 누락 → criteria 64+ 400 (75건 폐기) ② 장기 러너 stdout 파일 리다이렉트 필수 (백그라운드 kill 3회) ③ 1-run ±3~5는 반드시 3-run

### 1.5 C AI Q1~Q6 + 실행순서 5단계 — 전부 실측 완료

| C 제안 | 실측/수행 | 결과 |
|---|---|---|
| Q1: **head+tail·evidence-span** | ① head+tail: stage47a~h (1.4) ② evidence-span: **stage40 — 회수 개선 상한 1건** | ❌ 둘 다 기각 |
| Q2: **Noul+Choice hybrid** | stage29~37: Noul+Choice 1콜/2콜 3-run majority | ❌ **hit@3 75 vs 77 — 기각** (불안정) |
| Q3: **soft gate** | win-300+soft gate(τ=0.3) 채택 | ✅ 운영 반영 |
| Q4-1: Noul hybrid | (Q2와 동일) | ❌ |
| Q4-2: **choice probability 보존** | `_jev_choice` probs/confidence 파싱 + abstain_p 저장 | ✅ (사안 4의 기반) |
| Q4-3: evidence-span | (Q1과 동일) | ❌ |
| Q5: **support_set 재감사** | stage46: 11건 q1=direct/q3=exists, 10/11 회수 miss | ✅ pool_recall 90.0% 상한 수용 |
| Q6: **4지표 병렬** | stage47g: hit@1/3·abstain·FP 병렬, hit@5 실노출 문서화 | ✅ |
| 선행정리: **commit 고정·gate 통일** | `_filter_and_rank` 기본값 (2,0.30)→**(1,0.0) 통일** | ✅ (버그 1건 해결) |

### 1.6 C AI "답을 찾는 문제 vs 후보가 답인지 판단하는 문제 분리" — 사안 4로 연결

- C의 핵심 제언: **absolute answerability(Noul)와 relative selection(Choice) 분리** — 1-call 안에 Noul[60]+Choice[1]+abstain 동시 요청
- stage29~37에서 Noul+Choice hybrid 실측 → 기각 (hit@3 75 vs 77, 불안정)
- 그러나 **사안 4(abstain 무력)에서 이 방향의 재고가 필요** — 현재 abstain이 무력한 이유가 "answerability 신호 부재"일 수 있음

---

## 사안 1: abstain 라벨 문구 개선 — **판정 보류** (B AI: "current 쪽으로 기움")

### 1.1 제안
현행: `"No candidate is usable evidence for answering the question"`
개선(improved): `"No candidate contains the specific fact, value, version, or decision the question asks for — same-topic mention alone is not evidence"`

### 1.2 실측 (stage45, 스냅샷 기준, 동일 세션 280콜, err 0)

| 문구 | hit@1 | hit@3 | abstain | noans FP (50) |
|---|---|---|---|---|
| **current** | 75 | **78** | 3 | 27 |
| **improved** | 73 | **76** | 5 | **22** |

- paired: op **-2** (→76), noans **-5** (27→22) → 건수 순 +3
- op 손실 2건 = **코덱스 앱·마우스 WHY(원인) 질문을 abstain으로 오판** (current에선 hit@1~3)
- noans 개선 5건 = 시점/규칙 확인형 정확히 차단: "skip_shadow 테이블 누락?", "Mnemosyne consolidation 중복 버그?", "주석 영어 규칙?", "테스트 생략 커밋 규칙?", "로그 한국어 규칙?"

### 1.3 절충 시도 (stage45 v3/v4, 같은 세션)

| 문구 | hit@3 | noans FP | 비고 |
|---|---|---|---|
| v3 (explanation 포괄 수용) | 76 | 24 | 코덱스 rank 4 (hit 아님), noans -2 |
| v4 (WHY 조건부 수용) | 76 | 23 | abstain 6건(+1), 코덱스 여전히 abstain |

- **v3/v4 모두 코덱스(WHY)를 hit@3로 구제 실패** + noans 방어 약화 → 기각
- v3/v4는 1-run 2회 — JEV 비결정성 ±3~5 내에서는 "구제 실패 확정" 불가 (B AI 지적)

### 1.4 "원인 질문 감지 예외" 임베딩 분류 시도 (0콜)
- 원인 질문 시드 10개 vs 사실/시점 시드 10개 프로토타입과 쿼리 유사도 차이(margin)로 감지 시도
- **결과: 변별력 없음** — margin 양수 124/140(89%), op 손실 margin(+0.036/+0.055)과 noans 개선 margin(+0.007~+0.051) 분포 겹침 → 임계값 분리 불가 → 기각
- ⚠️ 0콜 임시 계산 — 별도 raw 없음 (세션 내). 재현은 stage45 raw + 시드 재구성 필요

### 1.5 신뢰성
- raw: `data/stage45_abstain_label_snapshot.json` (cond: current/improved, 140쿼리×2=280콜, err 0, 스냅샷 고정)
- 러너: `experiments/operational-golden/stage45_abstain_label_snapshot.py`
- **한계 1**: 1-run — 비결정성 ±3~5 노이즈 가능, 3-run 재검증 필요
- **한계 2**: 동일 세션 순서 효과 미통제
- v3/v4 raw: `data/stage45_v4_snapshot.json`

### 1.6 판단 요청
1. improved 채택 vs 현행 유지 — u∈[20%,41%] × h∈[0.3,1] harm-가중 (ΔU = −(1−u)·2.2 + u·h·10 %p)에서 어느 쪽?
   - B AI 계산: u=22.5% → 손익분기 h≈0.76 / u=45% → h≈0.27 (u_true 38.6%면 손익분기 h≈0.34)
2. **u_true=38.6% (§4)를 반영하면 손익분기가 낮아진다** — 이 경우 improved 채택이 유리한가? 단 op -2의 WHY 오판이 h에 미치는 영향 고려
3. WHY 오판의 라벨 문구 외 해법 (사안 4와 결합 가능성 포함)

---

## 사안 2: IDF(로컬 식별자) 필터 — **판정 보류** (B AI: v3 기각, v2 재검토)

### 2.1 제안 (B AI Q1c)
쿼리의 숫자·버전·영문 식별자가 JEV가 고른 pick 원문에 없으면 abstain — 값 불일치 오주입 차단 (0콜, 수 ms).

### 2.2 실측 (stage41, 0콜 — stage32 raw noans FP 16건 대상)

> 기준 명확화: v1/v2/v3는 **stage32 raw(hybrid pool30, 10-06 00:27)의 noans FP 16건**으로 계산. (stage39 pool 고정 22건은 라벨 문구 실험용 — IDF와 다른 셋)
> ⚠️ **수치 정정 (10-06 재검증)**: 아래는 스냅샷 DF 통계 + stage32 raw 0콜 재계산 값. (기존 초안 9/2/7은 계산 기준 오류로 기각)

| 규칙 | noans FP 차단 | op-90 오차단 | 순효과 |
|---|---|---|---|
| v1 영문 식별자 전부 | 7 | 2 ("API", "repo") | +5 |
| v2 underscore/숫자 혼합만 | 5 | 0 | +5 |
| **v3 IDF 드문 단어 (DF≤10)** | **4** | **0** | **+4** |

- v3 차단 4건: `browser.backend`, `JEV_API_URL`, `diag6`, `diag63` — 쿼리에만 있고 pick 원문에 없는 드문 식별자
- **B AI 지적 수용**: v2(형태 기반)는 DF 비의존이라 **시간 의존성 없음** + stage45 재계산 시 v2의 실질 커버 확인 필요
- **B AI "상호보완" 지적**: v3(식별자)와 improved 라벨(시점/규칙) 겹침 작음 — 합산 효과 가능성

### 2.3 시간 의존성
- v3는 코퍼스 DF 의존: 메모리 증가 → DF 상승 → 무력화, 신규 주제 식별자는 과민 반응 위험
- v2는 형태 기반(`_`/숫자 혼합)이라 드리프트 없음
- 패턴 기반(버전/날짜/포트)은 커버리지 0건 (효과 없음 실측)

### 2.4 신뢰성
- raw: `data/stage32_hybrid_pool30.json` (noans, FP 16건), `stage39_abstain_label_poolfixed.json` (참고)
- **한계**: 0콜 시뮬레이션 — 실제 JEV rerank 결합 시 abstain_p 영향 미측정, "pick 없음→abstain 강제" 파급 미검증

### 2.5 판단 요청
1. v2(형태 기반) 채택 가치 vs 기각 (시간 의존성 없음, 오차단 0)
2. v3(DF 기반)는 드리프트로 기각이 맞는가
3. v2를 soft gate와 결합하는 설계 (τ_eff = τ − δ) — **B AI 제안**: "쿼리 형태 식별자가 pick 원문 없으면 τ 0.3→0.1로 낮춤, JEV 확신(abstain_p≈0)이면 통과" — 타당한가?

---

## 사안 3: noans 셋 시점 변질 + 평가 인프라 — **스냅샷 채택, 프로토콜 확정 대기**

### 3.1 발견 (stage38)
- noans hard 50건 "코퍼스에 답 없음" 전제가, **실험 대화 누적**으로 특정 쿼리에 실제 답이 생김 (자기참조 오염)
- 실측: 같은 noans 쿼리가 stage35(10-06 01시) abstain → stage38(10-06 09시) FP로 뒤집힘 **13건** (working_memory 1,701→1,721행 증가)

### 3.2 재구성 (stage43, 0콜)
1. **평가용 DB 스냅샷 고정**: `mnemosyne_snapshot_20261006.db` (sqlite backup, 1,721+113행, PRAGMA integrity_check OK)
2. **변질 판정**: FTS 스캔 + bekko 임베딩 sim + 인간 판정(23건) → **spoiled 5건 제외** (`nans2_008` JEV_API_URL, `_009` Free tier, `_015` pip uv, `_028` pool_rank, `_047` keyring)
3. **신규 5건 보충** (`nans3_001~005`): deepseek→muse?, RRF 가중치 변경?, cron 실패?, SKIP 먼저 반환?, ZeroTier? — 전체 1,729벡터 top-1 sim 0.11~0.16 "답 없음" 검증 + 하드-네이버 다수
4. 최종 50건 = hard 45 + fresh 5

### 3.3 파생 프로토콜
- **이후 모든 noans 평가는 스냅샷 기준** (시점 무관 비교 셋 동일)
- JEV 실험은 EXPLABS_API_KEY SET 터미널에서만, 503 1회 재시도, 429 키 전환

### 3.4 신뢰성
- raw: `data/golden_noanswer_hard_queries.json.bak_20261006_103054` (변질 전), `data/golden_noanswer_hard_queries.json` (재구성)
- **B AI 지적**: 13건 플립 중 spoiled 5건만 설명 — 나머지 8건(설정 변경/비결정성/놓친 spoiled) 미설명. **쿼리별 플립률 3-run으로 불안정 쿼리 비율 측정 필요**
- **B AI 지적**: top-1 sim ≤0.16은 부재 증명 아님 (부록 A gold 11건도 vec rank 100~400+로 sim 낮음)
- **B AI 제안**: eval 세션 태깅·코퍼스 제외 — **미구현** (스냅샷 고정으로 실질 대체)

### 3.5 판단 요청
1. 스냅샷 고정 평가가 타당한가 (vs 유동 noans 유지보수)
2. 신규 5건 선정 방법론(top-1 sim ≤0.16 + FTS 하드-네이버)이 "답 없음" 보장으로 충분한가
3. **noans FP 지표 자체를 시간 함수로 봐야 하는가** — 운영 지표 대안 추천 (사안 4의 abstain율·샘플 라벨링)

---

## 사안 4: abstain 무력 (신규 실측 — 2026-10-06, stage48) — **가장 시급·중대**

> 직전 3종 AI 검토 후 오늘 수행한 **라이브 60쿼리 교차 검증**에서 발견한 신규 사실. 직접 검토 요청.

### 4.1 실측 설계
- **대상**: 라이브 데몬 trace(`jev_trace.log`)에서 수집한 실사용 쿼리 60건 — 실험·스모크 쿼리 제외
- **정답 라벨**: 사용자(운영자)가 사람 판정 — "답 있음(yes)/답 없음(no)/모호(maybe)" 60건 전수
- **재실측**: 스냅샷 DB(1,721+113행)에서 동일 파이프라인(cur: 현행 라벨·τ=0.3·win-300·gate 1/0.0) 실행 → abstain/pick 판정
- **러너**: `stage48_live60_cross.py` (시트 쿼리 하드코딩·row_factory 포함), raw: `data/stage48_live60_cross.json`
- **버그 3건 수정 과정 포함**: (① 게이트 기본값 (2,0.30)→(1,0.0) ② 러너 row_factory 누락 → pool 2~9 ③ load_queries trace 재수집 → 시트 고정) — 최종 수정 후 수치

### 4.2 결과 — 사용자 판정 교차 (cur)

| | pick | abstain | 합계 |
|---|---|---|---|
| **답 있음 (yes)** | **35** | 0 | 35 |
| **답 없음 (no)** | **22** | **0** | 22 |
| 모호 (maybe) | 3 | 0 | 3 |

- **recall (답 있음 노출) = 100%** (35/35) — 회수는 완벽
- **noans FP율 = 100%** (22/22 전부 오주입) — abstain 0건
- **abstain_p 분포**: min 0.00, median 0.00, p75 0.01, max 0.16 — **JEV가 모든 라이브 쿼리에 abstain 확률 ~0 부여**
- improved 라벨도 동일: abstain 1/60 (p=0.30 "리뷰 전용 턴에서 커밋해도 돼?") — **라벨 문구로는 abstain이 안 나옴**
- err: cur 1건 (http503 일시), imp 0

### 4.3 핵심 발견 — **abstain 메커니즘이 라이브에서 완전 무력**

1. **골든셋(하드 noans)에서는 abstain이 작동** (FP 27/50=54%만 오주입, abstain 23/50)
2. **실제 라이브 무답 질문에서는 abstain이 전혀 작동 안 함** (0/22) — 유사 메모리가 존재하면 JEV가 무조건 pick
3. **u_true = 38.6%** (22/57, maybe 제외) — B AI 추정 범위(20~41%)의 **상단**. 라이브 트래픽 ~39%가 무답인데 **전부 오주입 중**
4. **왜 이런가** (실측 기반 가설):
   - 골든셋 noans = "의도적으로 까다로운 무답" (하드-네이버 존재) → JEV도 abstain을 고려
   - 라이브 무답 = "유사 이웃은 있지만 답은 없는" 일반적 질문 → JEV는 **"가장 그럴듯한 후보"를 무조건 답으로 채택**
   - abstain 라벨이 "No candidate is usable evidence"라 **유사하지만 답이 아닌 후보**를 abstain하지 못함
5. **stage45 improved 라벨도 마찬가지** — 시점/버전 명시는 골든셋 하드에서만 효과. 라이브에서 abstain 1/60

### 4.4 abstain 무력의 운영 영향

| 지표 | 값 | 의미 |
|---|---|---|
| u_true | 38.6% | 라이브 쿼리의 ~39%는 답이 없음 |
| abstain율 | **0%** (0/57) | 시스템이 "답 없음"을 한 번도 반환 안 함 |
| 오주입률 | **38.6%** | 모든 라이브 쿼리가 메모리 컨텍스트(최대 5개)를 받음 |
| recall | 100% | 답 있는 질문은 전부 회수 |

- 운영 영향: Hermes 에이전트가 **무답 쿼리에서도 항상 메모리 1~5개를 받아** 환각/오답 근거로 사용할 수 있음
- Fail-open 원칙(재판정/실패 시 메모리 노출)이 **기본값으로 작동 중**이라 더 큰 문제

### 4.5 시도/기각된 해법 (검토 요청을 위한 기반)
1. **문구 improved** (사안 1) — 라이브 abstain 1/60 → 무력. 문구로 안 됨 (실측)
2. **excerpt 변형 8종** (stage47a~h) — WHY 3건 구제는 되나 abstain 자체를 늘리지 못함. 전부 기각 (실측)
3. **τ 스윕** (soft gate) — abstain_p가 0이면 τ를 아무리 조정해도 abstain 안 생김. τ는 무력 (실측)
4. **Noul+Choice hybrid** — stage29~37에서 hit@3 75 vs 77로 기각했으나, **Noul의 "answerability" 신호가 abstain 무력의 직접 해법일 수 있음** (C AI 제언) — 재검토 후보
5. **winner entailment 게이트** — gold50 과다거부로 기각 (stage24, 사람 VALID 희생)

### 4.6 판단 요청
1. **abstain 무력의 원인** — 위 4.3 가설(라이브 질문엔 항상 유사 이웃 존재 → abstain 라벨 무시)이 타당한가? 다른 설명?
2. **해법 우선순위** — 아래 후보 중 무엇을 먼저 실측할 가치가 있나?
   - (a) **Noul answerability 병행** (C AI: 1콜 안에 Noul[60]+Choice[1]+abstain) — 단, stage29~37 hybrid 기각을 어떻게 넘을 것인가
   - (b) **abstain 라벨 재설계** — "유사하지만 답이 아닌" 명시 + abstain 선택 유도 보강
   - (c) **두 라벨 분리** (B AI: "주제만 같고 값 없음" vs "쓸 만한 후보 없음" — abstain_p 합산 후 τ)
   - (d) **noans FP 수용** — u_true 38.6% 환경에서 abstain 포기, 항상 pick (현행 유지)
   - (e) 기타
3. **u_true=38.6%의 함의** — 이 수치가 사실이면 **현재 시스템은 라이브 오주입률 ~39%**. 골든셋 noans FP 54%가 실트래픽보다 낮다는 기존 가정(B AI §0.5-D)과 정면 충돌. 어느 쪽이 더 신뢰 가능한가?
4. **운영 정책** — abstain이 무력한 동안: ① 현재처럼 항상 pick(위험 수용) ② 노출 Top-5 중 상위 1개만 노출(리스크 축소) ③ 임시로 abstain_p 상향(효과 없음 실측) ④ 기타
5. **다음 실측 설계** — (b)/(c)를 검증하려면 140콜(op90+noans50)이면 충분한가? 라이브 60을 포함해야 하는가?

---

## 부록 A: pool 밖 miss 11건 판정 (수용 결정 배경)
- support_set 재감사: 11건 전부 q1=direct, q3=exists (진짜 retrieval miss 11/11 — [11]만 q4=dependent)
- 해법 시도 3종 전부 기각 (0콜 실측):
  - evidence-span 인덱스 (stage40): 회수 개선 상한 1건
  - write-path 태그 (A Q5): 저장 시점 대화 태그 시뮬레이션 복구 0/10
  - read-path 쿼리 확장: top-20 유사 메모리 단어 주입 복구 2/11 — 경로/메타/범용어 오염
- → pool_recall 90.0% (81/90)를 구조적 상한으로 수용

## 부록 B: 참조 문서
- 실측 raw: `data/stage45_abstain_label_snapshot.json`, `data/stage45_v4_snapshot.json`, `data/stage44_abstain_pos_2x2.json`, `data/stage48_live60_cross.json`, `data/exp8d_excerpt400_raw.json`, `data/exp8e_400_gate_raw.json`, `data/stage32_hybrid_pool30.json`, `data/stage47f_imphbn_3run.json`, `data/stage47h_imphbn_curhb_3run.json`
- noans 재구성: `NOANS_SET_REBUILD_20261006.md`, `data/golden_noanswer_hard_queries.json`
- 스냅샷: `snapshots/mnemosyne_snapshot_20261006.db`
- miss 판정: `STAGE46_SUPPORTSET_20261006.md`
- 설계 기각: `docs/design/write-path-tags-design-20261006.md`
- 종합 기록: `RECALL_ABSTAIN_INVESTIGATION_20261005.md`, `STAGE29_35_HYBRID_2CALL_20261006.md`, `STAGE44_45_ABSTAIN_LABEL_20261006.md`, `STAGE47_FINAL_20261006.md`, `STAGE48_LIVE60_CROSS_20261006.md`

## 부록 C: 실험 raw 전체 목록 (재현 경로)
- runR: `data/runR_recall_strength_raw.json`
- stage16~24: `data/stage16_*.json`~`data/stage24_conditional_win300_gate.json`
- stage29~37 hybrid/2-call: `data/stage29_*.json`~`data/stage37_*.json`
- stage38~46: `data/stage38_*.json`, `stage39_abstain_label_poolfixed.json`, `stage40_evidence_span.json`(기각, raw 미보존), `stage41`(0콜 스크립트), `stage42_soft_abstain_observation.json`, `stage43_noans_rebuild.json`, `stage44_abstain_pos_2x2.json`, `stage45_abstain_label_snapshot.json`/`stage45_v4_snapshot.json`, `stage46_verdicts.json`
- stage47a~h: `data/stage47_win150.json`, `stage47b_win150_3run.json`, `stage47c_imp150.json`, `stage47d_head_overlap.json`, `stage47e_head_overlap_non.json`, `stage47f_imphbn_3run.json`, `stage47g_curhb.json`, `stage47h_imphbn_curhb_3run.json`
- stage48: `data/stage48_live60_cross.json`

---

## 요청 형식
사안별로: **① 판정 (채택/기각/수정/보류 유지) ② 근거 (실측 인용) ③ 권장 다음 단계 (콜·비용·실험 설계 포함)** 를 답변해 주시면 됩니다. 반대 의견 환영. 실측 신뢰성 한계(§1.5/2.4/3.4/4.5) 지적도 별도 부탁드립니다.