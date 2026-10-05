# JEV 메모리 시스템 검토 요청서 — hippo-memory 비교 후속 실측 9건 + excerpt 확장 기각 (2026-10-05)

> **이름 충돌 경고**: 본 요청서의 "jev-mem"(로컬 Hermes 메모리 미들웨어)은 학술 프로젝트 "Jev-Mem"(arXiv 2609.23986)과 **이름만 유사한 전혀 다른 프로젝트**다. 아래 시스템은 Hermes 에이전트 위에서 동작하는 JEV(SystemOne API) 게이트 + SQLite 래퍼로, 학술 Jev-Mem·Mnemon·PerfectRecall과 무관하다. 검토 시 동일체로 오해하지 말 것.

---

## §0. 검토 목적과 답변 형식

**목적**: 우리 시스템의 회수 파이프라인(read path)에서 실측으로 확정한 병목 2가지(①abstain 8건 ②rerank-miss 11건)를 해결하기 위한 **개선안을 찾는 것**. 우리가 시도한 5가지 접근이 전부 기각됐고, **우리가 놓친 개선안이 있는지**가 핵심 질문이다. "우리 강점 방어"가 아니라 "빈틈을 메울 아이디어"를 원한다.

**답변 형식 (Q1~Q6 각각)**:
- ① 동의 / 반박 / 대안 (택1)
- ② 근거 (본문 실측 수치를 인용)
- ③ 실측 가능한 구체 제안 (설계 + 예상 JEV 콜 수 + 0원 검증법)
- 실측 vs 추측을 명시적으로 구분할 것.

---

## §A. 실측 확정 사실 (재의심 불필요 — 이 표는 검증 완료)

### A1. 시스템 개요

- **저장(write)**: Hermes 턴 → JEV SystemOne 게이트(G-qual: user 1콜, assistant 옵트인 시 +1콜) → KEEP이면 Mnemosyne SQLite 저장. fail-open(KEEP 방향).
- **회수(read)**: 4-lane 풀(FTS + 벡터(bekko-a8m) + importance + graph) → `_filter_and_rank` 게이트(어휘) → **POOL_BUDGET=60** 컷 → **JEV choice 1콜**(후보 60개 중 "가장 직접적인 증거" 1개 선택, abstain 라벨 포함) → rank 1 lift. abstain이면 빈 컨텍스트.
- **excerpt 규칙**: choice 라벨은 800자 초과 행만 "쿼리 단어 기준 300자 윈도우", 그 외 **head-100**.
- **환경**: Windows 로컬, 라이브 DB 1,683 working_memory 행, 임베딩 전수 bekko-a8m(384d, unit, 10-01 백필). **JEV = Experiential Labs SystemOne, free lane(분당 240 콜 조직 한도)**.
- **금지 원칙**: 메모리 경로에 일반 LLM(chat/completion API) 사용 금지 — JEV(SystemOne decision: choice/noul만 지원, text 생성 불가)와 로컬 임베딩만 허용. (이번 조사에서 9router 사용 Doc2Query를 원칙 위반으로 폐기함)

### A2. 방법론 교훈 (이번 조사에서 발견된 오염)

- 실험 러너를 프로젝트 `.venv`(fastembed가 bekko-a8m 미지원)로 실행 → **vec lane 0건** 상태로 Run R/stage16~18이 전부 오염. 데몬 venv로 재실행 → hit@3 61.1% → 77.8%, abstain 27 → 8.
- **이 문서의 모든 수치는 데몬 venv 재실행분만 유효.**

### A3. 운영 벤치마크 실측 (op 골든셋 90건, 사람 큐레이션)

| 지표 | 값 |
|---|---|
| hit@3 | **70/90 (77.8%)** |
| abstain | **8** (gold가 pool에 있는데도 abstain 3건: upstream 404 pos3, gold50 pos5, S8 pos2) |
| miss (비-abstain, gold pool 내) | 6건 — gold_pos=3인데 gold_rank=4 (3건), gold_pos=4/6/16 → rank 5/7/17 |
| miss (gold pool 밖) | 5건 |
| noans hard 50건 오주입 | **13/50 (26.0%)**, abstain 37 |
| JEV 콜 | choice 1콜/쿼리 (free lane 0원) |

- abstain 8건 상세: pool=40인데 abstain 6건, pool=4(Exa) 1건, pool=32(upstream) 1건. gold pool 내 abstain 3건의 gold_len 329/402/436자 (모두 head-100 excerpt 적용 대상).
- rerank-miss 6건: JEV가 gold(pos 3~16)를 1위로 안 고르고 다른 후보를 선택. 단, 골드 3건(데스크톱-텔레그램, X1, webdriver)은 gold_pos=3인데 4위로 밀림.

### A4. 시도 후 기각된 접근 (전부 실측)

| # | 접근 | 실측 결과 | 기각 사유 |
|---|---|---|---|
| 1 | retrieval strengthening (recall_count 가중) | 풀 순서 변경 79/90, hit@3 Δ0 (improved 0) | JEV choice는 후보 텍스트만 보므로 순서 조작 무효 |
| 2 | POOL_BUDGET 40→60/100 | stage15: cut 60은 1/6 lift, cut 80/100 abstain 폭증. abstain 8건 gold 위치 스캔: rank 41~60 사이 gold 0건 | 상향 대비 abstain 회복 0 |
| 3 | Doc2Query (일반 LLM) | 9router로 재표현 23건 → gold top-40 20/23 | **원칙 위반**(일반 LLM 간섭) + JEV 생성 불가(400) → 폐기 |
| 4 | excerpt 확장 (head-100 → 쿼리 윈도우 300) | op hit@3 70→76 (+6, abstain 3→0) **vs noans 오주입 13→20 (+7)** | **순효과 0 이하** |
| 5 | 조건부 2콜 (1차 head-100 → abstain만 300자 + winner entailment 게이트) | noans 18 (게이트 3건 차단), gold 회복 2건, gold50은 게이트가 정답 차단 | 게이트 과다거부(사람 VALID 희생) + noans 여전히 head-100 대비 +5 |

### A5. excerpt 확장의 원인 분석 (stage23, 사람 판정)

- win-300으로 오주입된 10건은 **전부 "과거 이력/시점 확인" 질문** ("~했던 적이 있어?", "~이던 시절", "~시점 성능") — 코퍼스에 주제가 겹치는 메모리는 있지만 그 특정 사실(버전·날짜)의 답은 없는 hard-neighbor.
- head-100은 정보 부족으로 정직하게 abstain, win-300은 300자 텍스트에서 주제 근접성을 보고 "답"으로 유추 → 오주입. 선택된 메모리 대부분 PLAUS(주제 근접), 일부 IRREL.
- **결론: excerpt 정보량 증가 = gold 회복과 noans 방어가 동일 축에서 충돌. 이 메커니즘을 깨는(두 목표를 분리하는) 방법이 필요한데 우리는 못 찾았다.**

---

## §B. 작업 가설 (반박 환영)

1. abstain 8건·miss 11건의 근본 원인은 "**JEV choice가 후보 60개의 head-100 excerpt만 보고 판정**"해서, ①답이 뒤에 잘린 gold를 abstain/오선택하고 ②주제 근접 미끼를 걸러내지 못한다는 것.
2. "**1위 선택**" 구조 자체가 문제일 수 있음 — hit@3의 miss 6건은 gold가 pool 3위인데 4위로 밀리는 "경계 오차"라서, choice(1개 뽑기) 대신 **top-k 선택**(예: 3개 뽑기) 또는 **점수화(noul)** 로 바꾸면 회복될 가능성.
3. noans 방어는 "abstain 라벨 + 헤드-100" 조합이 이미 26% 오주입을 만들고 있는데, 이걸 더 낮출 방법이 있을 것.

---

## §C. 검토 질문

### Q1. gold pool 내 abstain 3건 + rerank-miss 6건 — "답이 뒤에 잘린" 문제의 해법?

실측: gold 6건이 pool 안에 있고 pos 2~16인데 JEV가 abstain/오선택. excerpt 300자로 바꾸면 이 6건이 전부 gold 1위로 회복됐다 (stage20/21). **단 noans 오주입이 +7 증가.**

- (a) "쿼리 단어 위치 기반 윈도우"가 아니라 **"문서 구조 기반 발췌"**(예: 앞 100자 + 마지막 100자(head+tail), 중요 표/헤더 포함) — noans 오주입을 유발하지 않으면서 답이 뒤에 있는 gold를 살리는가?
- (b) excerpt를 **질문 유형에 따라 조건부 선택** (예: "과거 이력/시점" 질문 패턴이 감지되면 head-100 유지, 사실/원인 질문이면 300자) — 이 규칙은 noans hard 셋에 과적합인가?
- (c) gold 6건만 살리는 **다른 메커니즘** 제안.

근거에 "왜 noans 오주입이 늘지 않을 것 같은가"를 반드시 포함. (추측 vs 실측 구분)

### Q2. choice(1개 선택) → top-k(3개 선택) 또는 점수화(noul) 전환?

실측: miss 6건 중 3건은 gold_pos=3인데 JEV가 abstain이 아닌 다른 후보를 1위로 골라 gold가 4위로 밀림. choice는 "1개만 뽑는다"는 강제로 경계 오차에 취약. **JEV는 noul(후보별 0~1 점수)도 지원**하며, 우리는 pointwise 실측에서 "choice 98% vs pointwise τ=0.65 0% noans FPR" 차이를 이미 확인했다(A 유지 확정).

- (a) **top-3 선택**(choice questions에 criteria 3개 뽑기) — JEV 1콜 유지, gold가 3위 안에 들 확률 상승? noans 오주입 영향?
- (b) **noul 점수화로 전환**: hit@3 자체가 "3위 안" 정의라 점수화가 hit@3과 더 정합적인가? noans 방어는 τ로?
- (c) choice 유지 + **2~3위 후보까지 컨텍스트에 포함** (현재는 1위만 lift) — 이게 hit@3의 의미론(system이 3개를 보여주는가?)과 맞는가?

우리 시스템은 현재 "1위 1개"만 컨텍스트로 반환한다(상위 3개가 아니라). hit@3 지표와 실제 노출 구조가 어긋나있을 수 있다는 지적도 검토해 달라.

### Q3. noans 방어 26% → 더 낮출 방법?

실측: hard noans 50건(코퍼스 이웃 무답: "없던 옵션/반대 규칙/다른 시기" 질문)에서 오주입 26%. abstain 라벨이 이미 있고, 단순 임계(τ) 게이트는 op hit@3를 깎아 기각됐다.

- (a) **winner entailment 게이트**(1위 후보에 "직접 답인가" 1콜)를 **noans 전용**으로만 적용 (op에는 적용 안 함) — op 손실 0, noans만 추가 방어? (우리는 gold50에서 게이트가 정답을 NO로 차단하는 과다거부를 봤다. 게이트를 "NO이면 abstain"이 아니라 "낮은 신뢰 신호"로 쓰는 방법?)
- (b) abstain **라벨 문구**를 "이력/시점 질문" 방어에 특화 (기존 exp7 시리즈에서 문구 민감도 실측 이력 있음)
- (c) 2차 판정 없이 풀 조립 단계에서 noans 후보를 줄이는 방법 (예: vec 유사도 하한)

### Q4. 우리가 놓친 개선안 — 리스트업

우리는 다음을 시도했다: recall 가중 ❌ / POOL_BUDGET ❌ / Doc2Query(일반 LLM) ❌ / excerpt 확장 ❌ / 조건부 2콜+게이트 ❌.

위 5가지를 제외하고, **이 데이터(초기 77.8% / noans 26% / gold 8건 abstain / JEV choice 1콜 제약)에서 다음으로 실측할 가치가 가장 높은 개선안 Top 3**를 제안해 달라. 각각: ①설계(파이프라인 어느 단계) ②예상 JEV 콜 수 변화 ③0원 오프라인 검증법 ④실패 시 판정 기준.

**제약을 반드시 존중**: 일반 LLM 금지 / JEV는 choice·noul만 / free lane 240콜 분당 / 라이브 DB read-only(스크래치 복제 사용) / Windows 로컬.

### Q5. gold pool 밖 5건 — lane 커버리지 vs 지표 정의?

실측: miss 11건 중 5건은 gold가 pool 60 안에 아예 없음 (vec rank 100~400+). stage19에서 gold 21/23이 vec rank≤40임을 확인했지만, 이 5건은 lanebudget으로도 안 들어온다.

- (a) 이 5건을 **지표에서 제외**할 근거(골든셋 라벨 품질 재감사)가 있는가, 아니면 lane 확대(무료)로 잡는 게 맞는가? (vec lane k 확대는 과거 "top-40 recall 0.783 고정"으로 기각 이력 있음)
- (b) **쿼리 자체가 의역**이라 임베딩 유사도가 낮은 경우(예: "전환 전 어떤 문제 있었지?" ↔ "supermemory 미사용 실측..."), 이걸 검색 문제로 볼지 라벨 문제로 볼지 — 판정 기준.

### Q6. hit@3 지표 자체의 타당성

우리 벤치마크는 "JEV choice가 고른 1위에서 gold까지의 거리 ≤3"을 hit@3으로 정의한다. 그러나 시스템은 컨텍스트에 **1위 1개만** 반환한다.

- (a) 이 지표 정의가 실사용(에이전트가 컨텍스트를 받아 답하는 성능)과 정합적인가? 아니면 **@1**(1위만) 또는 **컨텍스트 3개 노출**(구조 변경)이 더 정합적인가?
- (b) 골든셋 90건이 "사람이 큐레이션한 실제 질문"인데, hit@3 77.8%가 이 시스템의 실사용 만족도와 어떤 관계인지 — 상한/하한 관점에서 평가.

---

## 부록: 참조

- 실험 기록: `experiments/operational-golden/RECALL_ABSTAIN_INVESTIGATION_20261005.md`
- 러너: `run_r_recall_strength.py`(180콜, 데몬 재실행), `stage19_gold_vec_rank.py`(0콜), `stage20~24`(excerpt/게이트)
- raw: `data/runR_recall_strength_raw.json`(데몬분), `data/stage21_excerpt300_op90.json`, `data/stage22_noans_excerpt300.json`, `data/stage24_conditional_win300_gate.json`
- 골든셋: `data/golden_eval_v2.json`(op 90, 사람 큐레이션), `data/golden_noanswer_hard_queries.json`(hard noans 50, 자동 생성)
- 판정 시트(모바일 HTML): `data/stage16_poolout_23_review.html` (출력은 `{"judged_at", "verdicts"}` JSON 다운로드)
- 시스템 코드: `gateway/j1_pipeline.py`(choice rerank, POOL_BUDGET=60, excerpt 규칙), `jev_mem_core/pipeline.py`(abstain→빈 컨텍스트)
- 금지/허용 자원: JEV choice·noul만 / 로컬 임베딩(bekko-a8m) / **일반 LLM 금지** / free lane 분당 240콜