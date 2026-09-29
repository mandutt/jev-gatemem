# JEV-Mnemosyne Middleware — 멀티 에이전트 전환 설계 브리프 (외부 검토용)

> **이 문서는 자기완결적(self-contained)입니다.** 저장소 접근이나 추가 질문 없이
> 이 문서만으로 구조를 파악하고 독립적 의견(권고/리스크/대안)을 낼 수 있도록 작성되었습니다.
> 상태: **검토 요청 전 — 아키텍처 미확정** · 2026-09-29

---

## 0. 이 문서의 목적

현재 **"Hermes 전용 임베디드 구조"** 를 **"여러 에이전트(Hermes·pi·Codex·opencode)가
하나의 메모리 DB를 공유하는 구조"** 로 전환하려 합니다. 아래에 (1) 현재 구조의 정확한
구현 내용, (2) 제안하는 중앙 집중형 구조, (3) 검토해 기각한 대안, (4) 독립적 판단이
필요한 질문을 기술합니다. **특히 "다중 에이전트 동시 실행 시 DB 쓰기 충돌을 어떻게
근본적으로 해결할 것인가"** 가 핵심 검토 대상입니다.

---

## 1. 시스템 배경 — 무엇을 하는 시스템인가

LLM 코딩/채팅 에이전트의 **로컬 메모리 계층**으로, 두 가지 역할을 합니다.

### 역할 1: 읽기 — J1 재순위화 검색 (prefetch)
- 에이전트가 턴을 시작할 때 과거 대화·선호·작업 이력을 **메모리 DB에서 검색**해
  시스템 프롬프트에 주입합니다.
- 단순 검색이 아니라 **JEV**(TypeSafe 사의 폐쇄형 reranking LLM API)로 후보를
  재순위화합니다.
- 실측 효과: recall@1 0.500 → **0.712** (baseline 대비), MRR 0.599 → 0.747.
- 최종 출력은 `## Mnemosyne Context` 블록(마크다운) — 에이전트 모델이 보는 유일한 계약.

### 역할 2: 쓰기 — LLM 기반 쓰기 게이트 (write gate)
- 대화 턴이 끝나면 `sync_turn(user_content, assistant_content)`으로 저장 여부를 판정합니다.
- **G-qual (user 발화)**: `store==NO_STORE && type==NO_STORE && conf>=0.6 → SKIP`
  (예: "좋아 진행해줘" 같은 무의미 발화를 저장하지 않음).
- **G-AS (assistant 발화)**: `store==NO_STORE | (store==STORE && type==context) → SKIP`.
  실측: precision 0.744 / recall 0.935 / F1 0.829 (gold50 인간 판정).
- 판정은 **JEV API 호출**로 얻은 구조화 JSON 기반. 모든 판정은 trace 로그에 기록.
- 저장 형식: `[USER] <발화>` / `[ASSISTANT] <발화>` prefix + importance + scope.

### 핵심 외부 의존성
| 의존 | 용도 |
|---|---|
| **mnemosyne** (pip 패키지) | SQLite DB + fastembed 임베딩 모델 + FTS5 + vector 검색. `BeamMemory` 클래스가 DB 연결·쓰기 담당 |
| **MNEMOSYNE DB** | SQLite 파일 1개 (`mnemosyne.db`). 모든 에이전트가 공유 대상 |
| **TypeSafe Jev API** | 재순위화·게이트 판정용 LLM (HTTP, 키 필요) |
| **Hermes** | 현재는 "호스트 런타임" — 플러그인으로 로드됨 |

---

## 2. 현재 구조 (As-Is, v0.1.0 릴리즈 + P1 반영)

### 2.1 레이어 구성 (Python)

```
gateway/                      # Hermes 무관 — 순수 로직
  j1_pipeline.py              # 4개 검색 lane(FTS/vector/importance/graph) → RRF 병합
                              # → 보수적 필터 → JEV choice 재순위화. 상태: 순수 함수들
  write_gate.py               # evaluate()(G-qual) / evaluate_assistant()(G-AS)
                              # JEV 호출 + 1500자 truncation + 5xx/타임아웃 1회 재시도
  trace.py                    # ring buffer trace 로그 (jev_trace.log)
core/                         # 신설 (P1 완료) — Hermes import 0
  j1_engine.py                # run(beam, query, pipeline, client) → Context 블록
                              # pipeline 모듈은 "인자로 주입" (섀도잉 우회)
backends/
  mnemosyne.py                # DB 접근 추상화
harnesses/
  hermes_j1.py                # Hermes 전용 어댑터 (아래)
  j1_access.py / wg_access.py # Hermes의 gateway 패키지 섀도잉 우회 accessor
```

### 2.2 Hermes 어댑터 (`harnesses/hermes_j1.py`)

```python
class JevRerankProvider(MnemosyneMemoryProvider):   # Hermes 패키지 상속
    def prefetch(self, query, *, session_id="") -> str:
        # core.j1_engine.run(beam, query, pipeline=..., client=...) 호출
        # → "## Mnemosyne Context" 블록 반환. 실패 시 base prefetch로 fallback
    def sync_turn(self, user_content, assistant_content, *, session_id="", messages=None):
        # G-qual(user) / G-AS(assistant) 평가
        # 4-way 분기: both KEEP→base 저장 / user SKIP→assistant만 /
        #             asst SKIP→user만 / both SKIP→저장 안 함
```

### 2.3 현재 데이터 흐름

```
읽기: Hermes 턴 시작 → prefetch() → core.j1_engine.run() → lane pool 검색(직접 DB)
     → Jev rerank → Context 블록 → 시스템 프롬프트 주입
쓰기: Hermes 턴 종료 → sync_turn() → write_gate 평가 → BeamMemory.remember() [직접 DB 쓰기]
```

**핵심 특성: DB writer = Hermes 프로세스 1개 (플러그인 임베디드).**
에이전트가 1개일 때는 단일 writer가 "구조적으로 보장"됩니다. **에이전트가 2개가 되는
순간 이 보장이 깨집니다** — 각 에이전트가 자기 어댑터를 들고 같은 DB에 직접 쓰기
시도 → 동시 쓰기 경합 발생.

---

## 3. 목표 — 멀티 에이전트 환경

### 3.1 미래 시나리오 (사용자 요구)

| 에이전트 | 연결 방식 |
|---|---|
| Hermes (데스크톱, 상시 실행) | 플러그인 (현재) |
| pi (코딩 에이전트 0.87.x) | TS 확장 (`~/.pi/agent/extensions/`) |
| Codex CLI | config hooks (UserPromptSubmit→recall, Stop→record) |
| opencode | TS 플러그인 |

- **하나의 통합 메모리 (mnemosyne.db 1개)** 를 모든 에이전트가 공유.
- 동시 실행(예: Hermes + pi 동시, 또는 Hermes 없이 codex + pi)에서도
  **손상·중복·충돌 없이** 읽고 쓰기.
- 에이전트가 5개, 10개로 늘어도 구조가 유지될 것.

### 3.2 핵심 설계 문제

**"여러 프로세스가 같은 SQLite DB에 동시에 쓴다"** — SQLite는 단일 writer
아키텍처이므로 동시 쓰기는 물리적으로 불가능합니다. 따라서:
- "동시 쓰기를 가능하게" 하는 설정은 존재하지 않고,
- **쓰기 경합 자체가 발생하지 않는 구조**를 만들어야 합니다.

---

## 4. 검토 후 기각한 대안

### 대안 A: SQLite WAL + busy_timeout(30s) — 각 에이전트가 직접 DB 쓰기
- **내용**: 모든 에이전트가 직접 `mnemosyne.db`에 쓰기. WAL 모드 + 30초 busy_timeout으로
  잠금 경합 시 대기.
- **기각 사유**: 동시 쓰기를 해결하는 게 아니라 **직렬화 대기로 회피**할 뿐.
  두 에이전트가 동시에 쓰면 한쪽이 블로킹되고, 대량 쓰기 시 30초 초과 실패 가능.
  "회피"에 불과.

### 대안 B: 파일 인박스 위임 — "Hermes 실행 중이면 Hermes만 writer"
- **내용**: Hermes가 실행 중일 때 pi·codex는 DB를 직접 안 쓰고 파일 인박스에 턴을
  append → 우리 Hermes 플러그인이 폴링해 대신 저장. Hermes가 꺼져 있으면 pi가 직접 쓰기.
- **기각 사유**: **Hermes가 없는 조합에서는 무력화**. 예: Hermes를 아예 쓰지 않고
  codex + pi만 쓰는 사용자 환경 → writer가 둘이 되어 다시 경합.
  "다양한 환경" 요구(에이전트 조합이 자유로워야 함)를 만족 못 함.

### 대안 C: 에이전트별 분리 DB + 주기 병합
- **내용**: 에이전트마다 자체 DB를 두고 주기적으로 중앙 DB에 병합.
- **기각 사유**: 메모리가 분리되면 prefetch 품질이 저하(에이전트 A가 B의 메모리를
  즉시 못 봄), 병합 로직(중복·시계열·삭제 처리)이 복잡해지고 오류 표면이 넓어짐.

---

## 5. 제안 구조 — 중앙 집중형 "Core-as-Writer"

### 5.1 개념

```
                    ┌──────────────────────────────┐
   Hermes ──────────┤                              │
   pi      ─────────┤    jev-mem-core (Python)     │
   Codex   ─────────┤    - 상시 장수 프로세스 1개    │
   opencode ────────┤    - mnemosyne.db 유일 writer │
                    │    - prefetch / sync_turn     │
                    │    - 단일 스레드 요청 직렬화   │
                    └──────────────┬───────────────┘
                                   ▼
                            mnemosyne.db
```

- **jev-mem-core**: Python 장수 프로세스 1개가 항상 실행.
- **모든 에이전트 어댑터는 "얇은 RPC 클라이언트"** — 비즈니스 로직 없음.
  JSON-RPC로 core에 요청:
  - `prefetch(query, session_id, agent)` → `## Mnemosyne Context` 블록
  - `sync_turn(user, assistant, session_id, agent, messages)` → 게이트 판정·저장 결과
- **DB 읽기·쓰기·임베딩 로드는 core만 수행.**

### 5.2 동시성 해결 원리

- core 내부는 **단일 스레드(직렬 처리)로 모든 요청을 순차 실행** →
  **DB 쓰기 경합이 구조적으로 불가능** (여러 에이전트의 동시 요청도 core가 순서대로 처리).
- busy_timeout, WAL 튜닝 등 "회피" 불필요.
- **세션 격리**: core가 에이전트 ID(`hermes` / `pi` / `codex` …)를 받아
  세션 접두사 부여 → 같은 DB에 쌓여도 에이전트·세션 단위 분리.

### 5.3 트랜스포트 선택지 (판단 필요)

| 방식 | 장점 | 단점 |
|---|---|---|
| **TCP localhost** (127.0.0.1:포트) | Windows 포함 전 플랫폼, 언어 중립(TS/Python/Go 모두), 다중 클라이언트 자연 지원 | 포트 관리·보안(로컬 바인딩) |
| Unix domain socket | 저오버헤드 | **Windows 미지원** (이 환경은 Windows 11) |
| stdio (core를 각 에이전트가 자식으로) | 구현 단순 | 에이전트별로 core가 또 뜸 → **다시 멀티 writer**, 상주 프로세스 증가 |
| HTTP (localhost) | 디버깅 쉬움(브라우저/curl) | 약간의 오버헤드 |

→ 현재 유력 후보는 **TCP localhost (JSON-RPC over socket)** 또는 로컬 HTTP.

### 5.4 Hermes 플러그인 변경 (기존 구조와의 차이)

- **기존**: Hermes 프로세스 내 임베디드 — `prefetch()`/`sync_turn()`이 프로세스 안에서
  직접 DB 접근.
- **제안**: 플러그인은 core로 RPC 요청하는 **클라이언트**로 교체.
- **외부 계약 불변**: `## Mnemosyne Context` 블록 형식, `sync_turn` 시그니처,
  fallback 계약(실패 시 빈 블록) — 모델이 보는 세계는 동일.
- **위험**: Hermes 런타임 회귀 가능성 (완화: v0.1.0 태그가 롤백 지점, smoke 7/7 테스트).

### 5.5 고장 모드 (core 다운 시)

- core 미실행/응답 없음 → 어댑터는 현재와 동일한 fallback:
  - prefetch: 빈 블록 반환 (메모리 없이 동작 — 기능 저하만)
  - sync_turn: 저장 스킵 + 로그 (데이터 손실은 게이트 판정 못 받은 발화의 저장 누락뿐)
- core 재기동 시 어댑터가 자동 재연결 시도.
- core 프로세스 관리: 사용자 환경(Windows)에서는 스케줄러/Startup 스크립트로
  상시 실행 예정 (Docker 비선호 — 네이티브 프로세스).

---

## 6. 환경 제약 (권고 시 반드시 반영)

| 제약 | 내용 |
|---|---|
| OS | Windows 11 |
| RAM | **15.6GB, 메모리 민감** — 상주 프로세스 수 최소화, fastembed(임베딩 모델, ~수백 MB) **중복 로드 금지** → core 1곳에서만 로드 |
| 배포 | **Docker 비선호** (강제 종료 시 복구 곤란) → 네이티브 Python 프로세스 |
| Hermes | **코어 수정 금지** (업데이트가 덮어씀) — 플러그인/외부 스크립트로만 |
| 기존 자산 | `core/j1_engine.py`(P1, Hermes 무관)와 `gateway/*`(순수 로직)는 **그대로 재사용** — core 서버는 이들을 import하는 얇은 래퍼 |
| pi 확장 | TypeScript (`@earendil-works/pi-coding-agent` ExtensionAPI) — Python 헬퍼 spawn 가능 |

---

## 7. 검토 요청 — 독립적 판단이 필요한 질문

1. **중앙 집중형 Core-as-Writer의 타당성**: 다중 에이전트가 하나의 SQLite를 공유할 때
   "단일 writer 프로세스 + RPC 클라이언트"가 옳은 방향인가? 더 나은 대안(다른 DB 엔진으로
   이전, 파일 기반 append-only 로그 + 별도 인덱서, 외부 메모리 서버 도입 등)은?
2. **트랜스포트 선택**: TCP localhost vs 로컬 HTTP vs 기타 — Windows 멀티 프로세스
   환경에서 무엇이 적절한가? (JSON-RPC over TCP의 함정·대안 포함)
3. **단일 스레드 직렬화 vs asyncio/스레드풀**: 동시성 해결 목적(단일 writer 보장)을
   유지하면서 읽기(prefetch)는 병렬로 처리할 수 있는 절충안이 있는가?
4. **Hermes 플러그인 임베디드→RPC 전환 리스크**: 검증된 임베디드 경로를 RPC로
   바꿀 때 회귀를 최소화하는 방법 (예: core 미실행 시 임베디드 모드로 fallback하는
   듀얼 모드는 합리적인가, 아니면 단순화가 우선인가)?
5. **놓친 고장 모드**: core 다운·재시작·에이전트 비정상 종료·Jev API 장애·DB 파일
   잠금 등에서 빠뜨린 시나리오가 있는가?
6. **확장 한계**: 에이전트 10+개, 초당 요청이 많아질 때 이 구조의 병목은 어디이고,
   언제 재설계가 필요한가?

---

## 8. 참고 — 현재 실측 수치

| 항목 | 값 |
|---|---|
| JEV API 호출 지연 | ~275ms (prefetch 1회) |
| J1 rerank 효과 | recall@1 0.500→0.712, MRR 0.599→0.747 |
| G-AS 판정 품질 | precision 0.744 / recall 0.935 / F1 0.829 (gold50) |
| 게이트 trace | write-gate / write-gate-as 이벤트, KEEP/SKIP 모두 기록 |
| 스모크 테스트 | smoke_write_gate 7/7 PASS (Hermes 런타임 venv) |
| Hermes 전용 세션 접두사 | `hermes_<session_id>` (예: `hermes_20260929_104012_df1103`) |