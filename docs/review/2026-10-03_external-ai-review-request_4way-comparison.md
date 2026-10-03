# 외부 AI 검토 요청 — jev-mem 아키텍처 비교 검토 (Mnemon / Jev-Mem / PerfectRecall)

- **작성일**: 2026-10-03
- **요청자**: jev-memory-middleware (개인 운영 시스템) 개발자
- **문서 성격**: **자가완결형 검토 요청서**. 수신 AI는 아래 첨부된 저장소·논문에 대한 접근 권한이 없으므로, jev-mem의 작동 구조를 이 문서 안에 코드 수준으로 기술했습니다. **추가 정보 요청 없이** 이 문서만으로 검토를 수행할 수 있도록 작성되었습니다.
- **검토 대상**: jev-mem(본인) + 3개 비교 시스템 (Mnemon, Jev-Mem, PerfectRecall)
- **주의**: **"jev-mem"(본인 프로젝트)과 "Jev-Mem"(Jiang et al., arXiv 2609.23986)은 서로 다른 프로젝트입니다.** 이름이 비슷하지만 별개이며, 이 문서에서 혼동 없이 지칭합니다.

---

## 0. 검토 요청 사항 (수신 AI에게)

다음을 검토해 주십시오:

1. **구조적 타당성**: jev-mem의 설계(§2)가 비교 대상 3개 시스템 대비 어떤 위치에 있는지, 각 설계 결정의 리스크와 이점
2. **가장 시급한 개선점 Top 3**: 근거(인용·수치)와 함께 우선순위 제시
3. **설계 결함 / 반증**: jev-mem의 가정 중 외부 증거로 반증되는 것, 내부 테스트로 검증되지 않은 채 남아 있는 리스크
4. **비교 대상이 없는 강점**: jev-mem만의 차별화 요소가 실제로 방어 가능한지(defensible) 판정
5. **다음 실험 제안**: 비용 대비 정보가치가 가장 높은 단일 실험 1개 (구체적 프로토콜 포함)

각 판정에는 **근거를 명시**하고, 불확실한 부분은 불확실하다고 밝혀 주십시오. 이 시스템은 개인용·비상업 시스템이며, Docker 불가/CPU 전용(No GPU)/RAM 16GB 제약에서 운영됩니다.

---

## 1. 환경 및 제약 (평가 시 전제)

| 항목 | 값 |
|---|---|
| OS / 런타임 | Windows 11, Python 3.12 venv (네이티브, Docker 불가) |
| 하드웨어 | x86-64 CPU 전용 (No GPU), RAM 15.6GB (메모리 민감) |
| LLM 백엔드 | 로컬 AI 에이전트(Hermes) — 메모리 검색 강화 대상. 답변 생성은 별도 LLM |
| 임베딩 | bekko-embedding-v1-a8m (384차원, int8 양자화, ONNX CPU) — warm commit 618MB, p50 1.31ms |
| Jev | TypeSafe SystemOne API (`api.typesafe.ai/v1/systemone`, `jev-latest`) — 원격 API |
| 저장소 | SQLite (Mnemosyne 스키마 포크: working_memory / episodic_memory / facts / graph_edges 등) |
| 사용자 언어 | 한국어/영어 혼용 (한국어 운영 데이터 중심) |

**운영 규모(2026-10-03 실측, 라이브 DB)**: working_memory 1,424행 / episodic_memory 113행 / memory_embeddings 1,432건 / facts 24 / graph_edges 26 / memoria_facts 841 / consolidated_facts 19 (DB 24.9MB). 검색은 cross-session. write는 세션당 턴 단위(user 발화 + assistant 응답 각 1건).

---

## 2. jev-mem 작동 구조 (코드 수준 상세)

### 2.1 전체 아키텍처

jev-mem은 **Hermes(로컬 AI 에이전트)의 메모리 파이프라인 앞단에 붙는 미들웨어**입니다. 두 개의 독립된 Jev 사용 지점을 가집니다:

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

발화 1건당 Jev를 2번 호출합니다 (user 발화용 1회 + assistant 응답용 1회, 각각 내부적으로 store 판정 + type 분류를 **하나의 배치 요청**에 넣음):

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
| read: 합성 180쿼리 (kodialog/koalpaca/kosgd/기계독해) | Acc@1 0.539 (gate 완화 + Jev choice) | 실측 |
| read: Jev choice 기여 | 0.467→0.489 (현행 gate) / 0.467→0.539 (gate 완화) | 실측 |
| read: lane pool gold 커버 | 80.6% (커버 145/180) | 실측 |
| write: store recall | 0.951 (user) / F1 0.829→0.866 (assistant, FP필터 후) | 실측 |
| write: abstain 정화 | 무답 오주입 10/10 → 0/10 | 실측 |
| fallback: 4장애 모드 (timeout/5xx/network/auth) | pool 순서 보존, 예외 미전파 | 실측 |
| 임베딩: a8m vs q4f16 vs int8 | 90.0% > 88.9% > 87.8% | 실측 (운영 골든셋) |

**검증된 격차**: 합성 벤치 180에서 PerfectRecall(full-scan) 0.806 vs jev-mem 0.539 (단, 이 벤치는 kodialog/kosgd가 100문항(55%)을 차지하는 합성 세트이며, jev-mem의 미스 35건이 100% kodialog/kosgd 단답 대화였음 — 아래 §4 PerfectRecall 참조).

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

## 4. 기존 실측 비교 (참고 — jev-mem vs PerfectRecall)

동일 스크래치 DB (419 span: kodialog 300 + koalpaca 40 + kosgd 40 + 기계독해 40), 180쿼리, seed 42:

| 지표 | jev-mem (lane pool + gate + Jev choice) | jev-mem (gate 완화 + choice) | PerfectRecall (full-scan) |
|---|---|---|---|
| Acc@1 | 0.489 | 0.539 | **0.806** |
| MRR | 0.556 | 0.584 | **0.849** |
| 지연/쿼리 | 0.23s | 0.28s | 0.38s |
| Jev 호출/180쿼리 | 179 | 180 | **1,800** |
| 메모리 | 615MB | 615MB | **12MB** |

- jev-mem의 단계별 손실: 임베딩 단독 0.672 → lane pool 0.467 (gold 커버 80.6%) → gate (49.4% 커버 — 게이트가 56개 gold 추가 탈락) → choice +0.028~0.072.
- 데이터셋별 (gate 완화 + choice): koalpaca 0.975 / 기계독해 1.000 / **kodialog 0.100** / **kosgd 0.300**.
- 분석: 미스는 100% 단답 대화 응답 선택 (kodialog/kosgd) — 일반 Bi-Encoder의 구조적 한계 (의미 유사도 vs 함의 단절)로 판정, "코딩 에이전트 기억 시스템에 무관한 데이터셋" 가설.

## 5. 외부 3자 비교 (참고 — 프로토콜 주의)

| 시스템 | 프로토콜 | LoCoMo | LongMemEval-S |
|---|---|---|---|
| Mnemon | gpt-4.1-mini 1회 답변 (OmniMemEval 재평가) | 91.7 | 83.8 |
| Jev-Mem (재실행) | 위와 동일 프로토콜 | 84.4 | — |
| Jev-Mem (자체 보고) | gpt-4o-mini LLM-as-Judge | 0.777 (0-1 스케일) | — |
| jev-mem (본인) | 한국어 골든셋 90쿼리 (자체) | — | — |

**주의**: 세 수치는 프로토콜이 달라 직접 비교 불가. jev-mem은 LoCoMo/LongMemEval를 아직 돌리지 않음 (한국어 운영 데이터만).

---

## 6. jev-mem의 자기 진단 (검토 시 반증 대상)

다음은 본인이 이미 인지한 약점/가설입니다. 이에 대한 반증 또는 보강 의견을 주십시오:

1. **"write-time 조기 폐기" 리스크**: SKIP된 발화는 검색 가능 저장소에 없음. Mnemon·Jev-Mem 둘 다 이 결정을 회피(보존) 방향으로 설계했다는 사실이 외부 증거. 다만 jev-mem은 운영 저장소의 품질 제어(대화 덤프 억제)가 목적이므로 완전 보존은 다른 문제를 낳음 — 절충점(예: SKIP 발화도 보존하되 recall 제외 마킹)이 합리적인지?
2. **read-time 판정 폭**: choice 1콜은 "최적 1개 + abstain"의 1비트. Mnemon은 질문당 5~10콜의 다중 yes/no, Jev-Mem은 최대 16콜의 적응형 폐루프. jev-mem의 얇은 판정이 어느 질문 유형에서 실제로 손실을 만드는지 (합성 벤치에서 못 잡는 유형은?)
3. **gate의 어휘 의존**: conservative gate가 어휘 중첩 기반 → 벡터 단독으로 맞는 케이스를 vec-rank exemption으로 부분 구제했지만, 여전히 어휘 편향. PerfectRecall이 gate 없이 0.806을 찍은 것과 대조.
4. **graph lane의 O(N) 스캔**: `facts` 전체 스캔 + 토큰 매치 → 스토리지 성장 시 이 lane만 비례 비용.
5. **단일 저장소 의존**: Mnemosyne 스키마 의존 (facts/graph_edges 테이블 포맷 등). Jev-Mem은 "search route만 있으면 어디든" 독립 지향.

---

## 7. 검토 결과 형식 (수신 AI용 가이드)

다음 형식으로 답변해 주시면 감사하겠습니다:

1. **핵심 판정 3줄 요약**
2. **§2 구조의 타당성 분석** (각 설계 결정별: 유지/수정/폐기 + 근거)
3. **§6 자기 진단 항목별 판정** (동의/반증/보류 + 근거)
4. **가장 시급한 개선 Top 3** (실행 가능한 수준으로)
5. **비교 대상 3개가 jev-mem에 주는 직접 교훈** (Mnemon / Jev-Mem / PerfectRecall 각각)
6. **다음 실험 1개 제안** (프로토콜 포함 — 비용, 측정 지표, 판정 기준)
7. **불확실성 목록** (이 문서만으로 판단할 수 없는 부분)

---

*이 문서는 2026-10-03 기준 jev-memory-middleware v0.2.0 구현(코드 실측)과 각 외부 시스템의 공개 문서/논문을 근거로 작성되었습니다. 수치 중 "자체 보고"로 표기된 것은 해당 프로젝트가 공개한 값을 인용한 것이며, 본인이 재현한 것이 아닙니다.*
