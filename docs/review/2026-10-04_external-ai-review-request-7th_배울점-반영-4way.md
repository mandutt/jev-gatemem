# 외부 AI 검토 요청 — jev-mem 대비 타 메모리 3종에서 "배울 점" 도출 및 반영 검증 (2026-10-04, 7차)

- **작성일**: 2026-10-04
- **요청자**: jev-memory-middleware (개인 운영 시스템) 개발자
- **문서 성격**: **자가완결형 검토 요청서**. 수신 AI는 저장소·논문 접근 권한이 없으므로, jev-mem의 작동 구조와
  비교 대상 3종(Mnemon, Jev-Mem, PerfectRecall)의 공개 정보를 이 문서 안에 모두 기술했습니다.
  **다른 정보 없이 이 문서만으로 검토가 가능합니다.**
- **주의**: **"jev-mem"(본인 프로젝트)과 "Jev-Mem"(Jiang et al., arXiv 2609.23986)은 서로 다른 프로젝트입니다.**
  이름이 비슷하지만 별개이며, 이 문서에서 혼동 없이 지칭합니다.

---

## 0. 이 검토의 목적 — "3종에서 배울 점을 실측으로 검증해 반영"

> 이 검토의 목적은 jev-mem의 강점을 방어/홍보하는 것이 아니라,
> **타 메모리 프로젝트 3종(Mnemon, Jev-Mem, PerfectRecall)에서 배울 점이 있으면
> 우리 프로젝트에 실제로 반영하는 것**입니다.
> 아래 실측은 그 학습·반영 의사결정을 돕는 방향으로 설계되었으며,
> 각 실측이 "우리 시스템의 빈틈"을 드러내면, 그것을 **3종의 어떤 아이디어로 메울 수 있는지**를
> 판단해 주십시오. 겉보기에 좋아 보이는 아이디어라도 우리 데이터로 실측 검증(0원)을 거쳐 채택/기각할 예정입니다.

---

## 1. 환경 및 제약 (평가 시 전제)

| 항목 | 값 |
|---|---|
| OS / 런타임 | Windows 11, Python 3.12 venv (네이티브, **Docker 불가**) |
| 하드웨어 | x86-64 **CPU 전용 (No GPU)**, RAM 15.6GB (메모리 민감) |
| LLM 백엔드 | 로컬 AI 에이전트(Hermes) — 메모리 검색 강화 대상. 답변 생성은 별도 LLM |
| 임베딩 | bekko-embedding-v1-a8m (384차원, int8 양자화, ONNX CPU) |
| Jev | TypeSafe SystemOne API (`api.typesafe.ai/v1/systemone`, `jev-latest`) — 원격 API. **FREE 레인은 크레딧 0원** (시간당 $0.50, 일당 $2.00 무료 할당, org당 240 dispatches/min) |
| 저장소 | SQLite (Mnemosyne 스키마 포크: working_memory / episodic_memory / facts / graph_edges 등) |
| 사용자 언어 | 한국어/영어 혼용 (한국어 운영 데이터 중심) |

**운영 규모(2026-10-03 실측, 라이브 DB)**: working_memory 1,424행 / episodic_memory 113행 / memory_embeddings 1,432건 / facts 24 / graph_edges 26 / memoria_facts 841 / consolidated_facts 19 (DB 24.9MB). 검색은 cross-session. write는 세션당 턴 단위(user 발화 + assistant 응답 각 1건).

---

## 2. jev-mem (본인) 작동 구조 — 코드 수준 상세

### 2.1 전체 아키텍처

jev-mem은 **Hermes(로컬 AI 에이전트)의 메모리 파이프라인 앞단에 붙는 미들웨어**입니다. 두 개의 독립된 Jev 사용 지점:

```
[사용자 턴 발생]
     │
     ▼
┌─────────────────────────────────────────────────────────────┐
│ WRITE PATH (쓰기) — core daemon (127.0.0.1:47821)            │
│                                                             │
│ 1. ledger_receive (durable spool, SQLite ledger)            │
│ 2. JEV write gate (턴당 2회 호출 — user 발화용 1 + assistant용 1) │
│      호출 1건 = store 판정 + type 분류 2질문 배치             │
│      Q1 choice: STORE / NO_STORE                            │
│      Q2 choice: 13종 유형 분류 (fact…artifact, NO_STORE)      │
│ 3. 규칙 기반 KEEP/SKIP 결정 (G-qual / G-AS)                  │
│ 4. KEEP된 발화만 mnemosyne.db에 저장 (writer thread)          │
│ 5. ledger_finish + trace                                   │
└─────────────────────────────────────────────────────────────┘

[사용자 질의 발생 → prefetch]
     │
     ▼
┌─────────────────────────────────────────────────────────────┐
│ READ PATH (읽기) — J1 rerank pipeline                        │
│                                                             │
│ 1. lane pool: FTS(60) + vector(60) + importance(8)          │
│    + graph/fact(10) → RRF(k=30) 병합                         │
│ 2. conservative gate: 어휘 중첩 + source quality 필터         │
│    (vec-rank exemption: vec 상위 2위 + 토큰 1개 이상 통과)    │
│ 3. JEV choice 1콜: "단일 최적 증거 1개 선택"                  │
│    - 후보 excerpt 120자, 최대 40개                            │
│    - abstain 라벨: "No candidate is usable evidence"        │
│ 4. winner lift: Jev 선택을 rank 1로 올림, 나머지 pool 순서 유지 │
│ 5. abstain 시: 빈 컨텍스트 ("메모리 없음" 신호)                │
│                                                             │
│ Fallback 계약: Jev 실패/타임아웃/키 없음 → pool 순서 그대로    │
│ (절대 예외 전파 안 함)                                        │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 WRITE PATH 상세

**2.2.1 Write gate — Jev 질문 2개 (choice 2콜, 발화별)**

발화 1건당 Jev를 2번 호출 (user 발화용 1회 + assistant 응답용 1회, 각각 store 판정 + type 분류를 **하나의 배치 요청**에 넣음):

```
Q1 "store" (choice): "Does this utterance have long-term memory value worth storing?"
    criteria: c0=STORE, c1=NO_STORE
Q2 "classify" (choice): 13종 배타 유형 중 하나
    criteria: c0=fact, c1=preference, c2=decision, c3=commitment, c4=goal,
              c5=event, c6=instruction, c7=relationship, c8=context,
              c9=learning, c10=observation, c11=error, c12=artifact, c13=NO_STORE
```

**2.2.2 KEEP/SKIP 규칙 (규칙 기반, Jev 확률을 임계값으로 처리)**

| 대상 | 규칙 | 근거 (실측) |
|---|---|---|
| user 발화 (G-qual) | SKIP = `store!=STORE` && `type∈{NO_STORE, 미분류}` && `store_conf >= 0.6`<br>KEEP = 그 외 전부 (type-rescue / low-conf 포함) | store recall 0.951 (누락 0), live 142건 검증 |
| assistant 발화 (G-AS) | SKIP = `store==NO_STORE` **\|** (`store==STORE` && `type==context`)<br>KEEP = 그 외 | gold50 precision 0.744 / recall 0.935 / F1 0.829 |
| assistant commitment FP 필터 v4 | 정규식 기반 추가 필터: KNOWLEDGE(지식작업) 있으면 KEEP, TRANSITION(결과→이제/다음)+OPERATION(실행작업)이면 SKIP, INTENT(순진행의지)면 SKIP | gold50 회귀 0, FP 43% 감소 (precision 0.744→0.806, F1 0.829→0.866) |
| 파싱 실패 / Jev 실패 / 타임아웃 / 키 없음 / 킬스위치 | **전부 KEEP** (누락 방지 fail-open) | — |

**2.2.3 저장 내용 (KEEP된 경우만)**

```
저장 행 = "[USER] {원문}" / "[ASSISTANT] {원문}"  (한국어 원문 그대로)
  - user:      importance=0.5, source="conversation", scope=session
  - assistant: importance=0.15, source="conversation", scope=session
  - metadata: {source_agent, session_key, idem_key, turn_id,
               (fail_open이면) gate=fail_open:<reason>, incident_id}
  - 저장 전 redaction: format-based 고정밀 패턴만 (비밀키 등) — 게이트 판정은 원문 기준
```

**2.2.4 장애 대응 (fail-open + quarantine + 재판정)**

- Jev API 지속 실패(401/402/403/429/5xx/네트워크) 시: 게이트 판정 불가 → **KEEP + quarantine 마커**로 저장 (`gate: "fail_open:http-402"` 등), `incident_id` 부여
- 장애 구간(incident) 단위로 기록 → 이후 배치 재판정(rejudge)으로 keep/skip 재결정 가능
- 서킷 브레이커: 연속 5회 실패 → open (30s 후 half-open probe)
- spool: core daemon이 죽어 있어도 어댑터 쪽에서 원문을 JSONL spool에 보존 (50MiB/agent, 재기동 시 replay)
- transient(5xx/타임아웃)은 `pending_gate`로 두고 재시도

**2.2.5 중요 한계 (자기 고백)**

- **SKIP된 발화는 그 순간 mnemosyne.db에 저장되지 않습니다.** 원문은 ledger(payload, durable)에는 남지만, **검색 가능한 저장소에는 들어가지 않습니다.** 즉 "그때는 잡담이라고 판단했지만 나중 질문에 필요해지는 정보"는 의도적으로 버려집니다 (ledger에서 수동 복구 외 경로 없음).
- 게이트는 발화 단위 분류 — 대화 문맥(직전 턴들)을 보지 않음 (발화 원문 + 1500자 컷만).

### 2.3 READ PATH 상세 (J1 rerank)

**2.3.1 Lane pool (4개 lane → RRF k=30)**

| lane | 소스 | 폭 | 내용 |
|---|---|---|---|
| FTS | `_fts_search_working` (SQLite FTS) | 60 | BM25 계열 어휘 검색 |
| vector | `_wm_vec_search` (sqlite-vec, bekko-a8m 임베딩) | 60 | 코사인 유사도 |
| importance | `importance >= 0.85` 최신순 | 8 | CJK LIKE 한계 보완 (고신뢰 메모리) |
| graph/fact | facts.subject/object 매치, graph_edges(gist ctx), memoria_facts | 10 | 관계·속성 기반 (관련성 게이트 후) |

→ RRF 점수 = Σ 1/(30 + rank_lane), 전체 pool 반환 (실측: gold-in-pool 79~100%)

**2.3.2 Conservative gate (어휘 + 품질 필터)**

- 쿼리 토큰 (ASCII 단어 3자+ / 한글 2자+)과 후보 content 토큰의 중첩 검사: `min_distinctive >= 2` && `coverage >= 0.30`
- **vec-rank exemption**: 벡터 lane 상위 2위 이내 + 토큰 1개 이상 겹치면 통과 (짧은 구어체 쿼리 구제 — Run I/J 실측으로 추가)
- source quality 곱: conversation×0.72, [USER] 접두×0.68, [IDENTITY]×0.80
- adjusted score = (score×0.65 + signal×0.35 + importance×0.05) × quality

**2.3.3 Jev choice (1콜)**

- 후보 최대 40개, 각 excerpt 120자 (env `JEV_EXCERPT_LIMIT`), id 12자/type/scope/importance/source 메타데이터 헤더
- 질문: "Which candidate memory is the single best evidence for answering the question? Pick exactly one."
- **abstain 라벨** (Run O, 2026-10-03 채택): "No candidate is usable evidence..." 추가 → 무답 쿼리 오주입 10/10→0/10, gold 59/59 보존
- 타임아웃 5s (read), 실측 latency ~228ms

**2.3.4 결과 처리**

- non-abstain: Jev 선택 idx를 rank 1로 lift (`[pool[idx]] + 나머지 pool 순서`)
- abstain: 빈 리스트 반환 → prefetch가 "메모리 없음" 렌더
- Jev 실패: pool-only 순서 (spec §19 fallback — shape 동일, 예외 미전파)

### 2.4 인프라 (core daemon)

- aiohttp 서버 127.0.0.1:47821, Bearer auth, endpoint: `/v1/health`, `/v1/prefetch`, `/v1/turns`, `/v1/status`, `/v1/admin/shutdown`
- SingleWriter 패턴: DB 쓰기 전용 스레드 1개 + queue (max 500) — 4-way gate 분기 저장
- ReaderPool: 읽기 전용 스레드 2개 (thread-local RO sqlite)
- CircuitBreaker (5회 연속 실패 → open 30s → half-open probe)
- spool replay: 10분 주기 스캔, 원자적 rename → process_turn 재생 (idempotency dedupe)
- trace: ring buffer 512KB (pool/gate/jev/lift/abstain/write-gate 이벤트)
- 어댑터: Hermes 플러그인, Codex, opencode, pi (4개 에이전트 런타임)

### 2.5 검증 자산 (실측 수치)

| 항목 | 수치 | 상태 |
|---|---|---|
| read: 운영 골든셋 90쿼리 (한국어) | Acc@1 = 90.0% (bekko-a8m) | 실측 |
| read: 합성 180쿼리 | Acc@1 0.539 (gate 완화 + Jev choice) | 실측 |
| read: Jev choice 기여 | 0.467→0.489 (현행 gate) / 0.467→0.539 (gate 완화) | 실측 |
| read: lane pool gold 커버 | 80.6% (커버 145/180) | 실측 |
| write: store recall | 0.951 (user) / F1 0.829→0.866 (assistant, FP필터 후) | 실측 |
| write: abstain 정화 | 무답 오주입 10/10 → 0/10 | 실측 |
| fallback: 4장애 모드 | pool 순서 보존, 예외 미전파 | 실측 |
| 임베딩: a8m vs q4f16 vs int8 | 90.0% > 88.9% > 87.8% | 실측 |

**검증된 격차**: 합성 벤치 180에서 PerfectRecall(full-scan) 0.806 vs jev-mem 0.539 (단, 이 벤치는 kodialog/kosgd가 100문항(55%)을 차지하는 합성 세트이며, jev-mem의 미스 35건이 100% kodialog/kosgd 단답 대화였음 — 아래 §3.3 참조).

---

## 3. 비교 대상 (외부 시스템, 문서 기반 사실)

### 3.1 Mnemon (arXiv 2609.36059, github.com/Grivn/mnemon-memory-agent)

> **"Raw Records, Fast Judgments, Slow Thoughts"** — frozen research snapshot (2026-09-29, commit 50a6831d), dsh-mnemon v0.5.13 기반.

- **write-time Jev: 0회.** 원문을 raw record로 저장하고 임베딩만. 스키마·추출·분류 없음.
- **read-time**: System 2 LLM(gpt-4.1-mini)이 질문당 검색 쿼리 작성 (2콜 병렬) → hybrid search → Jev(System 1)가 회수 record를 검사 (질문당 5~10콜, 4~7 sequential waves, ~0.34s/wave, 총 1.4~2.4s) → 각 record에 대해 소규모 yes/no 판정 (관련성/유효성/시간 조건 등) → 답변 LLM에 ~3.8k tokens만 전달. System 1이 질문당 35~73k tokens의 record를 판독함.
- **배경 consolidation**: topic timelines/value histories 등 인덱스 오버레이 (raw를 rewrite하지 않고 그 위에 얹음).
- **결과 (자체 보고 + OmniMemEval 재평가)**: LoCoMo 91.7% (15개 시스템 중 1위), LongMemEval-S 83.8% (2/13), ECI 0.259 (최저). 전부 gpt-4.1-mini 답변. BEAM-100K→10M (80배 record)에서 질문 비용 1.11배 (검색만 248ms로 증가).
- **System 1 vs LLM 판정 실측**: 같은 14,359 record에서 Jev AUC 0.942 vs DeepSeek 0.900 vs gpt-4.1-mini 0.853 (LLM 대비 3~11x 빠름).
- **Jev-Mem(별개 논문)과의 대조 실험**: write-time 그래프 계열(Jev-Mem released code)이 **LoCoMo 84.4% vs Mnemon 91.7%** (7.3pp, CI 5.5-9.2). multi-hop 77.7 vs 91.8, temporal 82.9 vs 91.3.
- **한계**: 영어 벤치만. 한국어/다국어 미검증. 연구 스냅샷 (제품화 예정은 별도 mnemon/dsh-mnemon). gpt-4.1-mini/DeepSeek API 의존.

### 3.2 Jev-Mem (arXiv 2609.23986, Jiang/Li/Li @ UT Dallas, github.com/libingzheren/Jev-Mem)

> **⚠️ 주의: "개인 jev-mem"과 이름만 비슷한 별개 프로젝트.** "System-One-Controlled Agentic Memory" (2026-09-21).

- **write-time Jev: 대량.** 관찰(observation)마다:
  - **admission OFF** — 저장 여부 결정 안 함 (전부 보존). 명시적 문구: *"preserves observations rather than making an irreversible learned store-or-discard decision at ingestion time"*.
  - 4종 독립 Noul (episodic/semantic/procedural/preference) — 저장을 결정하지 않는 **annotation**만.
  - 후보 ≤10개 결정적 탐색 (vector/lexical/entity/timestamp) → Jev가 쌍별 관계 판정: semantic / causal (양방향) / same-episode / entity-alias. score ≥ 0.60 → typed edge 생성.
  - 주기 consolidation (Jev 20회 write마다): redundancy/contradiction/obsolescence/link usefulness 4 Noul + representation choice (keep_separate/merge/promote/uncertain). merge/promote 선택 시 확률 ≥0.85일 때만 System 2가 요약 생성.
- **read-time Jev: 적응형 폐루프 (최대 16콜).**
  - routing 6 Noul: semantic/temporal/causal/entity 필요도 + multi_hop_need + recency_importance → 그래프별 확장 예산 분배 (총 80).
  - anchor: vector+keyword RRF → 그래프 탐색 시작.
  - traversal: 후보별 4 Noul (relevance/relation_usefulness/new_information/supports_current_evidence) + cosine + edge prob 결합, beam 10.
  - **evidence-based stopping**: evidence_sufficient ≥0.95 && missing_evidence/contradiction <0.15 → 정지. continue_useful <0.15 → 정지. 하드 리밋: depth 8 / visited 60 / edges 2400 / Jev 16콜 / 15s.
- **결과 (자체 보고, gpt-4o-mini LLM-as-Judge)**: LoCoMo 0.777 overall (baseline 대비 +11.0% relative). Adversarial 0.962 (baseline 0.742). build 158s (baseline 1044s, 6.6x speedup), query latency 0.93s (baseline 1.47s).
- **중요 맥락**: Mnemon 측이 Jev-Mem released code를 **동일 프로토콜(gpt-4.1-mini, 1회 답변 — Jev-Mem 기본 best-of-3 끔)로 재실행**한 결과는 84.4% (vs 자체 보고 프로토콜에서 나타나는 더 높은 수치). 자기 보고 수치의 프로토콜 의존성 사례.
- **모델·런타임**: Jev = TypeSafe SystemOne (`TypeSafeClient.system_one`에 배치 호출 — state + typed questions 묶음).

### 3.3 PerfectRecall (github.com/arslanr-com/perfectrecall)

- **임베딩 없음**: 벡터/임베딩 인덱스 자체가 없음.
- **회수 방식**: SQLite 전체 행 스트리밍 스캔 → **모든 후보 span을 Jev relevance 배치로 평가** → 임계값 0.5 이상만 반환. (180쿼리 실측에서 Jev 1,800콜 = 쿼리당 10콜)
- **write gate**: 없음 (무조건 저장).
- **실측 (동일 스크래치 DB 419 span, 180쿼리, seed 42)**: Acc@1 0.806 / MRR 0.849 / 지연 0.38s/쿼리 / 프로세스 메모리 12MB.
- **한계**: 코퍼스 전체 스캔 → 코퍼스 성장 시 비용 선형 증가. 임베딩 없음 → 의미 기반 회수 불가(어휘/LLM 판정 의존). jev-mem 쪽 실측에서 미스가 100% 단답 대화(kodialog/kosgd)였고 PerfectRecall은 그 영역에서 강함.

---

## 4. 7차 실측 (2026-10-04, 전부 FREE 레인 0원)

> 코퍼스: 라이브 DB 스냅샷 해시 `1cd0a33f0f98c4f9` (1,351행). 같은 쿼리 세트를 조건별로 재실행해 비교했습니다.
> **핵심 발견: 6차까지의 "C+τ=0.65 검증"은 쉬운 noanswer 세트의 인공물이었고, 실측으로 철회됐습니다.**

### 4.1 A(choice) 동일 90쿼리 재실행 — 레인/캡/스냅샷 효과 분리

| | 5차 A | 7차 A 재실행 |
|---|---|---|
| hit@1 | 82.2% (74/90) | **77.8%** (70/90) |
| hit@3 | 85.6% (77/90) | **80.0%** (72/90) |
| abstain | 7 (7.8%) | **10 (11.1%)** |
| 코퍼스 | 1,319행 (해시 `1d60bce8`) | **1,351행 (해시 `1cd0a33f`)** |
| lane | 레인 혼합 | **FREE 전부** |

hit@3 변동 4건 (5차 hit → 7차 miss): `b2ed9f4d` (camelAI 라우팅 rank 1→5), `5e8516d6` (18080 프록시 rank 1→20), `7de2c1df`/`498bb204` (rank 1→abstain).

**해석**: -5.6pp는 abstain 증가(-2건) + 순위 하락(-2건)의 조합. 코퍼스 32행 증가(+2.4%)가 원인인지, 노이즈인지는 단일 실행으로 확정 불가 — **5차 85.6%와 7차 80.0% 모두 Wilson 구간 [76.4~91.3%] / [70.3~87.2%]로 중첩**.

### 4.2 leave-gold-out (정답 제거 시 오주입)

op 90건에서 gold 행을 코퍼스에서 제거하고 오주입률 측정 (B #3 대응):

| 조건 | 오주입 | 비고 |
|---|---|---|
| **C(pointwise τ=0.65)** | **45.6%** (41/90) | mean 0.596, max 0.920 |
| C(pointwise τ=0.5) | 68.9% (62/90) | |
| **A(choice)** | **41.1%** (37/90) | abstain 53 (58.9%) |

**해석**: 기존 noans 50건(2.0%/0.0%)은 명백히 쉬운 세트 — gold 제거만으로 오주입이 20배 폭증. A(choice)가 C(τ=0.65)보다 4.5pp 방어적이나 **둘 다 5% 가드레일을 크게 위반**.

### 4.3 gold44의 정체: 자동 생성 질문 (소스 코드로 확정)

`experiments/operational-golden/build_new_queries.py` (2026-10-01):
- 라이브 DB working_memory에서 fact/error/preference/instruction/artifact 유형, 100자 이상, 기존 gold 미포함 400행 추출
- 각 행 첫 문장에서 키워드 1개 추출 → **템플릿 12개 중 랜덤 1개에 삽입**해 질문 생성
- `"auto": true` 필드로 자동 생성 기록
- **결과**: 44건 전부 자동 생성. **사용자가 실제로 한 질문 아님.**

**벤치 부적격 실측 근거 3건**:
1. **hit@3 = 0.0%** (A/B/C/D 전 조건) — 자동 생성 질문은 어색·부분적이라 gold가 pool에 아예 안 들어감
2. **gold_score mean 0.328** (0.5 초과 5건뿐) — gold 라벨이 query의 답을 직접 담지 않음
3. **12건 샘플 육안 판정** ([7차 §3]):
   - `[01]` "다른 구성을 바꾼 적이 있어?" → gold: "다른 ai에게서 이런 답변이 나왔어" (**무관**)
   - `[02]` "IMPORTANT 선호 방식?" → gold: background process 로그 (부분)
   - `[03]` "url 관련 설정?" → gold: github URL 공유 (부분)
   - `[05]` "원인 관련 에러?" → gold: /v1/status 모델 필드 설명 (부분)
   - `[10]` "S4 작업 중 문제?" → gold: S4 리허설 보고 (**관련**)

**사용자 결정**: gold44 human 판정 44건 전체 생략 — "자동 생성 질문인데 사람이 판정할 의미가 없다". gold44는 **벤치에서 제외**, op 90건(사람 큐레이션)은 유일 기준선으로 유지.

### 4.4 C′ 문구 대조 (gold 0.328 원인 분리 — B #6 + C Q3 대응)

같은 (query, gold) 44쌍에 기존 문구 vs 개선 문구(직접 답 1.0/부분 0.5/무관 0.0)를 동일 모델로 비교 (44쌍 × 2 = 88콜, FREE):

| 문구 | mean | >0.5 | 분포 |
|---|---|---|---|
| 기존 (점수식) | **0.384** | 10건 | — |
| 개선 (직접답 기준) | 0.290 | 7건 | 상승 0 / 하락 29 / 동일 15 |
| Δ | **-0.095** | -3건 | |

**해석**: 개선 문구(외부 AI 3종 공동 제안 방향)는 오히려 gold 점수를 체계적으로 하락. 원인: "직접 답 1.0" 기준이 이미 약한 gold 라벨(§4.3)에 더 엄격하게 작동. **C′는 gold 라벨이 정상일 때만 의미 있음.**

### 4.5 fresh noans 하드셋 (τ=0.65의 진짜 오주입률)

코퍼스 이웃 주제 noanswer 50건(자동 생성, `golden_noanswer_hard_queries.json`) (50건, A choice + C pointwise 병행 = 121콜, FREE):

| 조건 | fresh noans (하드) | 기존 noans (쉬운) |
|---|---|---|
| **A (choice)** | **12.0%** (6/50) | 2.0% (1/50) |
| **C (τ=0.65)** | **16.0%** (8/50) | 0.0% (0/50) |
| C (τ=0.5) | 38.0% (19/50) | 10.0% (5/50) |
| max_score 분포 | mean 0.448, max 0.880 | mean 0.161, max 0.600 |

**해석**: τ=0.65의 "0.0% noans FPR"은 쉬운 세트의 인공물 — 하드 세트에서 16.0%로 폭증. A(choice)도 12.0%. **5% 가드레일은 어떤 조건도 충족하지 못함.** C의 max_score 분포(mean 0.448)와 op의 저신뢰 답안(0.54~0.60)이 본격 중첩 — τ로 분리 불가능함을 직접 시연.

### 4.6 abstain 문구 강화 (사용자 요청)

leave-gold-out에서 choice의 abstain 문구를 강화하면 오주입이 줄어드는가 (30×3, seed=42):

| 문구 | abstain(안전) | 오주입 |
|---|---|---|
| BASE (현행) | 76.7% (23/30) | 23.3% (7/30) |
| STRICT | 73.3% (22/30) | 26.7% (8/30) |
| **GATE** | **80.0%** (24/30) | **20.0%** (6/30) |

**해석**: GATE가 3.3pp 개선 (n=30, 통계적 미유의). **프롬프트 강화만으로 근접 오답 오주입(20%)을 5%로 낮추는 것은 불가능** — "이웃 주제지만 답 없음"을 Jev가 abstain하도록 하는 데는 구조적 한계. STRICT는 오히려 악화.

### 4.7 종합 판정 (6차 철회 + 유지)

**6차 "검증 확정" 표현의 철회**:
| 6차 주장 | 7차 실측 | 판정 |
|---|---|---|
| "C+τ=0.65 noans 0.0% 가드레일 통과" | 하드 세트 16.0% | ❌ **철회** (쉬운 세트 인공물) |
| "A 2.0% 방어" | 하드 세트 12.0% | ❌ **철회** |
| "new gold 0.328 = 의역·신조어" | gold 라벨 자체가 약함 | ❌ **철회** (데이터 품질 문제) |
| "개선 문구가 gold 점수 개선" | Δ=-0.095 (악화) | ❌ **철회** |

**유지되는 판정**:
- **A 유지 (read path 기본)**: A가 C보다 일관되게 우월 (op 80.0% vs C τ적용 후 74/90, 하드 noans 12.0% vs 16.0%) — 그러나 둘 다 90% 목표 미달 + 가드레일 위반
- **leave-gold-out/fresh noans가 새 기준선**: 향후 모든 read 실험은 이 두 세트를 가드레일로 사용
- **5차 85.6% vs 7차 80.0% = 노이즈 구간** (Wilson 중첩)

**새로 열린 문제**:
1. **gold 라벨 품질**: new 44건(그리고 op 90건 일부)의 gold가 query의 직접 답이 아닐 가능성
2. **근접 오답 방어 부재**: choice/pointwise 모두 "이웃 주제 답 없음"에서 Abstain 실패 — 새 메커니즘 필요
3. **gold1 기준의 의미**: gold 라벨이 약하면 hit@3 80%도 과대평가일 수 있음

---

## 5. 검토 요청 (Q1~Q7)

### Q1. gold44 벤치 제외 판정의 타당성

**(a)** 제외가 타당 — 자동 생성 질문은 사용자 분포와 무관 (라벨 결함 → 시스템 성능 오해)
**(b)** 보류가 타당 — "auto-gen 스트레스셋"으로 보존해 회귀 측정에 활용
**(c)** 재큐레이션이 타당 — 템플릿을 사람이 직접 다시 설계

→ §4.3 실측을 근거로 선택 + 근거 제시.

### Q2. "A 유지"의 최종 확정 기준 (op 80.0% / LGO 41.1% / noans 12.0%)

A hit@3 80.0% (5차 85.6% -5.6pp, Wilson 중첩), leave-gold-out 41.1%, fresh noans 12.0%.

**(a)** A 유지 — op hit@3 최고 + abstain이 유일한 방어선. 5% 가드레일은 모든 조건이 위반하므로 상대 비교만 유효
**(b)** 레인/캡/스냅샷 정리 후 **3회 반복 재측정**이 선행 — 단일 실행은 노이즈 구간
**(c)** A 대 C를 같은 조건·같은 날·3회 반복 **paired 비교** 후 결정

→ op 90/LGO 90/noans 50의 오주입 방어와 hit@3 트레이드오프를 함께 평가.

### Q3. C′ 실험 결과 해석 (Δ=-0.095)

**(a)** gold 0.328이 라벨 문제임을 확정 (문구를 바꿔도 라벨이 답을 안 담고 있으면 score 불가)
**(b)** C′ 문구가 실제로 나쁜 것 ("직접 답 1.0" 기준이 부분적 gold를 더 가혹하게 penalize)
**(c)** 둘 다

→ §4.3(12건 샘플) + §4.4(분포)와 함께 해석.

### Q4. fresh noans 하드셋 12~16%의 운영 의미

**(a)** 실제 운영 리스크 — 코퍼스와 이웃한 유사 주제 질문에 그럴듯한 오답 제시
**(b)** 하드셋이 과도 — 실제 사용자는 코퍼스와 이렇게 비슷한 질문을 하지 않음
**(c)** A의 abstain이 여전히 방어선 — 58.9% abstain은 과방어지만 오주입 절반 이하로 감소

### Q5. [핵심] 3종에서 "배울 점" — 실측 빈틈을 메울 아이디어

7차 실측이 드러낸 우리의 빈틈은 **"정답이 없는데 그럴듯한 오답(이웃 주제)이 있을 때 기권하지 못함"**입니다 (LGO 41.1%, fresh noans 12.0%).

이 빈틈을 메우기 위해 **3종(Mnemon / Jev-Mem / PerfectRecall)의 각 설계가 주는 직접적 교훈**을, **우리 제약(CPU 전용, RAM 15.6GB, FREE 레인 0원, 한국어 운영 데이터, 4개 어댑터)** 안에서 **도입 가능한 것만** 구체적으로 제시해 주십시오. 각 아이디어에 대해:
- **어느 실측 빈틈을 메우는지** (LGO / fresh noans / gold 라벨 / 기타)
- **도입 난이도** (저/중/고)와 **예상 실측 검증 방법** (0원으로 우리 데이터에서 확인 가능한지)
- **채택 시 기대 효과**와 **리스크**

### Q6. 다음 실험 1개 제안 (0원·2분 이내, 의사결정 최대 영향)

**(a)** 3회 반복 A 측정 (op 90×3=270콜) — 80.0% vs 85.6% 노이즈 해소
**(b)** op 90 + LGO 90 + fresh noans 50 통합 **파레토** — 기존 점수로 오프라인 계산 (0콜)
**(c)** op 90건 사람 재큐레이션 — gold44 제외 후 남은 90건 라벨 품질 재검증
**(d)** 여기서 종료 — A 유지 + gold44 제외 후 7차 결과 동결
**(e)** Q5에서 제안한 아이디어 중 하나의 **파일럿 실측**

→ "다른 정보 없이 이 문서만으로" 판단 가능한 것 중 의사결정에 가장 큰 영향을 주는 것을 골라 주세요.

### Q7. 문서로 판단 불가능한 부분 목록

이 문서만으로 판단할 수 없는 부분(예: 3종의 내부 구현 세부, 한국어 데이터에서의 3종 성능,
FREE 레인과 크레딧 레인의 모델 동일성 등)을 명시해 주십시오. **불확실한 부분은 불확실하다고** 밝혀 주세요.

---

## 6. 검토 결과 형식 (수신 AI용 가이드)

1. **핵심 판정 3줄 요약**
2. **Q1~Q7 각각: 선택 + 근거 (실측 수치 인용)**
3. **5. Q5에서 제안한 "배울 점" 아이디어 표**: 빈틈 매핑 / 난이도 / 검증 방법 / 기대 효과 / 리스크
4. **가장 시급한 개선 Top 3** (실행 가능한 수준으로, 0원 검증 우선)
5. **불확실성 목록** (이 문서만으로 판단할 수 없는 부분)

---

## 7. 참조 문서

- `docs/review/2026-10-03_external-ai-review-request_4way-comparison.md` (4-way 구조 비교 원본)
- `docs/review/2026-10-04_7차-후속실험-종합보고서.md` (7차 실측 원본, 커밋 `a66500f`)
- `docs/review/2026-10-04_external-ai-review-request-6th_τ0.65-검증확정.md` (6차 요청서)
- `experiments/operational-golden/build_new_queries.py` (gold44 생성 소스)
- `experiments/operational-golden/data/gold44_items.json` (44건 원본)

---

*이 문서는 2026-10-04 기준 jev-memory-middleware 구현(코드 실측)과 각 외부 시스템의 공개 문서/논문 및 동일 스크래치 DB 실측을 근거로 작성되었습니다. 수치 중 "자체 보고"로 표기된 것은 해당 프로젝트가 공개한 값을 인용한 것이며, 본인이 재현한 것이 아닙니다.*