# jev-mem-core 멀티 에이전트 전환 — 설계 검토 결과 및 구현 명세

| 항목 | 내용 |
|---|---|
| 대상 독자 | 구현 담당 (Hermes) |
| 작성일 | 2026-09-29 |
| 입력 문서 | `multi-agent-architecture-brief.md` (외부 검토용 브리프) |
| 상태 | 구조 확정: **Core-as-Writer + 로컬 HTTP**. 세부 사항은 §12 "확인 필요" 항목을 코드로 검증한 뒤 확정 |

---

## 0. 읽는 법

각 항목에 아래 표기를 붙였습니다.

- **[확정]** 그대로 구현합니다.
- **[권장]** 근거가 있으면 조정해도 되며, 조정 시 사유를 보고합니다.
- **[확인 필요]** 코드를 확인해 결정하고, 결과를 보고합니다.

이 문서는 두 부분으로 구성됩니다.

- **Part A (§1~2)**: 브리프에 대한 설계 검토 결과 (왜 이 구조인가).
- **Part B (§3~16)**: 구현 명세 (무엇을 어떻게 만드는가).

---

## 1. 요약

### 1.1 결정 사항

| # | 결정 | 표기 |
|---|---|---|
| D1 | `jev-mem-core` 장수 프로세스 1개가 `mnemosyne.db`의 **유일한 writer**이며 임베딩 모델(fastembed)도 여기서만 로드 | [확정] |
| D2 | 트랜스포트는 **로컬 HTTP** (`127.0.0.1`, JSON). raw TCP JSON-RPC는 채택하지 않음 | [확정] |
| D3 | 직렬화 범위는 **DB commit만**. I/O(HTTP, Jev)는 asyncio, 임베딩은 소형 스레드풀, 읽기는 read-only 커넥션 풀, 쓰기는 전담 writer 스레드 | [확정] |
| D4 | **런타임 듀얼 모드(임베디드 write fallback) 금지.** core 부재 시 어댑터가 core를 자동 기동하고, 그래도 안 되면 스풀에 적재 | [확정] |
| D5 | 모든 쓰기 요청에 **멱등성 키**를 적용 (`/v1/turns`) | [확정] |
| D6 | core 다운 시 어댑터는 **로컬 스풀(JSONL)**에 원문 턴을 적재하고, core가 기동 시 replay | [확정] |
| D7 | Jev 장애 시 prefetch는 **RRF-only(degraded)**, write gate는 **pending_gate 큐**에 보관 후 복구 시 재판정 | [확정] |
| D8 | 메모리 공유는 **격리가 아니라 `source_agent` 태깅**. prefetch는 기본적으로 에이전트 필터 없음 | [확정] |
| D9 | 도입 순서: **core → pi 어댑터 → Codex → opencode → Hermes(마지막, 플래그 뒤)** | [확정] |

### 1.2 브리프 대비 정정 사항

1. 브리프는 "SQLite는 동시 쓰기가 물리적으로 불가능"이라는 프레임으로 대안 A(WAL + busy_timeout)를 기각했습니다. 그러나 WAL에서는 reader가 writer를 막지 않고, write 트랜잭션은 ms 단위입니다. 사람 속도로 쓰는 에이전트 몇 개 수준에서는 락 경합이 실질 문제가 아닙니다. **기각의 진짜 근거는 다음 셋입니다.**
   - **(a)** 에이전트마다 fastembed를 로드하면 RAM이 수백 MB씩 늘어납니다 (15.6GB 환경에서 결정적).
   - **(b)** TS 어댑터마다 Jev 호출과 게이트 규칙을 재구현해야 합니다.
   - **(c)** 중복 제거와 스키마 마이그레이션의 주체가 흩어집니다.
   - `busy_timeout`은 제거하지 않고, 외부 도구(DB 브라우저, 정비 스크립트)가 파일을 열 때의 다층 방어로 유지합니다 (§13).
2. "얇은 클라이언트" 원칙과 달리, 현재 Hermes 어댑터의 `sync_turn` **4-way 분기**는 비즈니스 로직입니다. core로 이동합니다 (§11.2).
3. RPC 실패 시 base `MnemosyneMemoryProvider`로 fallback하면 Hermes 프로세스 안에서 임베딩을 다시 로드해 RAM 원칙과 충돌합니다. **금지**하고 빈 블록을 반환합니다.
4. §5.2의 "세션 격리"는 D8에 따라 **태깅**으로 재정의합니다.

### 1.3 불변 제약 [확정]

| 제약 | 내용 |
|---|---|
| OS | Windows 11 |
| RAM | 15.6GB, 상주 프로세스 최소화. **fastembed는 core 1곳에서만 로드** |
| 배포 | Docker 비선호. 네이티브 Python 프로세스 |
| Hermes | **코어 수정 금지.** 플러그인/외부 스크립트로만 변경 |
| 재사용 | `core/j1_engine.py`, `gateway/*`는 로직 유지 (§12의 소규모 시그니처 변경은 예외) |
| 사용자 | 단일 사용자. 멀티 유저/원격 접근은 비목표 |

---

## 2. Part A — 설계 검토 결과

### 2.1 Core-as-Writer의 타당성

방향은 맞습니다 (근거는 §1.2-1). 다른 DB 엔진(Postgres 등)은 Docker 비선호와 RAM 제약에 맞지 않고 이득도 없습니다. DuckDB 역시 단일 writer입니다. 외부 메모리 서버(Mem0 등)는 Jev 재순위화 파이프라인을 잃습니다. MCP 서버는 명시적 recall 도구용 보조 수단으로만 가치가 있습니다 (자동 recall/record는 hook이 필요).

### 2.2 대안 평가

| 대안 | 평가 |
|---|---|
| A. WAL + busy_timeout, 각자 직접 쓰기 | 락 경합보다 **RAM 중복 로드와 로직 중복** 때문에 기각. busy_timeout은 방어선으로 유지 |
| B. 파일 인박스 위임 | 기각 사유는 "Hermes 플러그인이 폴러"라는 점이었지 인박스 자체가 아님. **폴러가 core라면 Hermes 유무와 무관**하므로 스풀(§9)로 채택 |
| C. 에이전트별 분리 DB + 병합 | 기각 유지 (prefetch 품질 저하, 병합 복잡도) |

### 2.3 트랜스포트: 로컬 HTTP

- raw TCP JSON-RPC는 프레이밍(길이 접두/개행), 부분 읽기, half-open 연결, 재연결을 클라이언트마다 구현해야 합니다.
- Codex hook은 매번 뜨는 단발 프로세스라 상시 연결이 맞지 않습니다. 요청-응답 HTTP(`fetch`, `curl`, urllib)가 적합합니다.
- `localhost` 대신 **`127.0.0.1` 명시 바인딩** (`::1` 해석 문제 회피).
- Unix domain socket은 Windows에서 "미지원"이라기보다 언어/런타임별 지원이 고르지 않습니다. [확인 필요] 어느 쪽이든 HTTP 결론은 동일합니다.
- stdio(에이전트가 core를 자식 프로세스로 실행)는 core가 다중 기동되어 멀티 writer로 되돌아가므로 기각합니다.

### 2.4 동시성 모델

- 요청 전체를 단일 스레드로 처리하면 Jev 호출(~275ms, 타임아웃+재시도 시 수 초) 동안 모든 에이전트의 prefetch/write가 막힙니다 (head-of-line blocking).
- 따라서 **직렬화 대상은 DB commit뿐**입니다.
  - HTTP/Jev 호출: asyncio
  - 임베딩(CPU): 소형 스레드풀 2~4개 (onnxruntime은 GIL 해제)
  - 읽기: read-only 커넥션 풀 (WAL이라 writer와 공존)
  - 쓰기: 전담 writer 스레드 + 큐가 **유일한 쓰기 커넥션** 소유 (§7)
- 같은 세션 내 턴은 커밋 순서를 보장합니다 (세션별 asyncio.Lock). 세션 간에는 병렬입니다.

### 2.5 Hermes 임베디드 → RPC 전환

- 런타임 듀얼 모드는 단일 writer 보장을 깨고 테스트 표면을 2배로 만듭니다 (D4).
- 대신 **자동 기동 + 스풀 + 배포 단위 롤백** (v0.1.0 태그와 환경변수 플래그)을 사용합니다.
- 회귀 방어는 **골든 테스트**입니다. 같은 쿼리에 대해 임베디드 경로와 RPC 경로가 동일한 `## Mnemosyne Context`를 내는지 비교합니다. `core/j1_engine`이 순수 로직이므로 차이는 트랜스포트뿐입니다.
- `sync_turn`은 결과를 쓰지 않으므로 ack만 받는 fire-and-forget입니다.
- core는 Hermes venv 밖에서 돌므로 `gateway` 패키지 섀도잉 우회(`j1_access` / `wg_access`)가 core 쪽에서는 불필요합니다.

### 2.6 놓친 고장 모드와 대응

| 시나리오 | 대응 | 참조 |
|---|---|---|
| 타임아웃 후 재시도로 중복 저장 | 멱등성 키 + ledger | §6 |
| core 프로세스 alive지만 hang | `/v1/health` + 모든 요청 타임아웃 + watchdog | §4, §14 |
| core 다중 기동 | 포트 bind를 싱글턴 락으로 사용 | §4 |
| core 다운 시 저장 누락 | 어댑터 스풀 + core replay | §9 |
| Jev 장애 / rate limit | circuit breaker, 전역 동시성 제한, pending_gate | §8 |
| Jev 장애 시 게이트 정책 미정의 | 기본값 `spool`(pending_gate) | §8 |
| OneDrive 등 동기화 폴더의 DB (WAL/SHM 손상) | 경로 검사 후 경고 | §13 |
| 안티바이러스 파일 잠금 | busy_timeout, 재시도, 로그 | §13 |
| 단일 파일에 전 기억 집중 | 주기 백업 (`VACUUM INTO`) | §13 |
| 어댑터/코어 버전 불일치 | protocol version 헤더 | §5.1 |
| 임베딩 모델 교체 시 벡터 비호환 | DB 메타에 model id 기록·검증 | §13 |
| 메모리 오염 (웹/툴 출력의 인젝션이 assistant 발화로 저장) | 출처 태그, context 렌더링 시 "참고 데이터" 구분 | §7.5 |
| 슬립/복귀 후 stale 연결 | 상시 연결 미사용, 요청마다 연결 | §11.1 |
| 로그 무한 증가, 콘솔 창 | `pythonw` 기동, 로그 로테이션 | §4, §14 |

### 2.7 확장 한계

단일 사용자가 에이전트 10개를 써도 요청률은 사람 속도에 묶입니다. 예상 병목 순서는 **① Jev API rate limit/비용 → ② CPU 임베딩 버스트(서브에이전트 병렬) → ③ RAM → ④ 수십만 건 이상에서 vector lane 검색 비용**입니다. DB 쓰기가 병목이 될 가능성이 가장 낮습니다. 재설계 트리거는 추측이 아니라 계측(§14)으로 잡습니다. 멀티 유저/원격이 요구되는 시점이 사실상의 재설계 시점입니다.

---

## 3. Part B — 목표 아키텍처

```
 Hermes(plugin) ─┐
 pi (TS ext)   ──┤   HTTP  127.0.0.1:<port>/v1/*      ┌──────────────────────────────┐
 Codex (hooks) ──┼───────────────────────────────────▶│ jev-mem-core (Python, 1개)    │
 opencode (TS) ──┘  (스풀 JSONL: core 다운 시)          │  asyncio HTTP server          │
        │                                              │  ├─ prefetch pipeline         │
        └── spool/*.jsonl ──── replay ────────────────▶│  ├─ turn pipeline (gate)      │
                                                       │  ├─ Jev client + breaker      │
                                                       │  ├─ Reader pool (RO conns)    │
                                                       │  └─ SingleWriter thread       │
                                                       │       ├ BeamMemory(write)     │
                                                       │       └ core_state.db (ledger)│
                                                       └───────────────┬──────────────┘
                                                                       ▼
                                                         mnemosyne.db  (WAL)
```

### 3.1 데이터 디렉터리 [확정]

기본 `%LOCALAPPDATA%\jev-mem\` (OneDrive 등 동기화 폴더 **밖**). 기존 `mnemosyne.db` 경로를 유지해도 되지만 동기화 폴더 여부를 검사합니다 (§13).

```
%LOCALAPPDATA%\jev-mem\
  config.toml
  token                 # 랜덤 토큰 (사용자만 읽기 ACL)
  core.json             # {"port":..., "pid":..., "started_at":..., "protocol":1, "version":"..."}
  mnemosyne.db          # 기존 메모리 DB (core만 접근)
  core_state.db         # ledger / pending_gate (core만 접근)
  spool\<agent>\        # 어댑터가 쓰는 스풀 (core 다운 시)
  logs\core.log         # 로테이션
  logs\jev_trace.log    # 기존 trace 포맷 유지 + 확장
  backups\
```

---

## 4. 프로세스 수명주기

### 4.1 싱글턴 [확정]

- core는 기동 시 `127.0.0.1:<port>`를 bind합니다. bind 실패 시 기존 인스턴스가 있는 것이므로 `/v1/health`를 조회합니다.
  - 응답이 정상이면 즉시 종료합니다 (exit 0, 이미 실행 중).
  - 응답이 없으면 hang된 인스턴스로 간주하고, `core.json`의 pid를 로그에 남긴 뒤 **종료 코드 3**으로 실패합니다. 자동 kill은 하지 않고 사용자/스크립트가 결정합니다.
- 기본 포트는 `47821` (임의 값, `config.toml`로 변경 가능). 포트 충돌 시 탐색하지 않고 명시적으로 실패합니다.

### 4.2 기동 순서 [확정]

1. 설정 로드, 경로 검사 (동기화 폴더 경고)
2. 포트 bind (서버 소켓은 열되 readiness는 `starting`)
3. 임베딩 모델 로드 → DB 열기 → 스키마/메타 검증 (model id 일치 확인)
4. writer 스레드 기동 (`SingleWriter.start()`)
5. reader 풀 초기화
6. ledger 복구: `received / gated / pending_gate` 상태 행을 재큐잉 (§6.4)
7. 스풀 디렉터리 replay 스캔 (§9.3)
8. `core.json` 기록, health를 `ready`로 전환

`starting` 동안 `/v1/prefetch`, `/v1/turns`는 `503 NOT_READY`(retryable)를 반환합니다.

### 4.3 자동 기동 (어댑터 측) [확정]

- 어댑터는 연결 거부 시 `auto_start = true`이면 아래 명령으로 core를 detached로 실행합니다.
  - `pythonw -m jev_mem_core --serve` (플래그: `CREATE_NO_WINDOW | DETACHED_PROCESS`)
- 기동 후 `/v1/health`를 최대 5초 폴링합니다. **쿨다운 30초**로 spawn 폭주를 방지합니다.
- 싱글턴(§4.1) 덕분에 여러 어댑터가 동시에 spawn해도 하나만 살아남습니다.
- 상시 실행은 Windows 작업 스케줄러(로그온 시 시작)로도 등록합니다. 자동 기동은 안전장치입니다.

### 4.4 종료 [확정]

`POST /v1/admin/shutdown` 또는 종료 신호 → 새 요청 거부(`SHUTTING_DOWN`) → 진행 중 요청 완료 대기(최대 10초) → writer 큐 drain → `PRAGMA wal_checkpoint(TRUNCATE)` → 커넥션 close → `core.json` 삭제.

---

## 5. HTTP API 명세

### 5.1 공통 규칙 [확정]

- Base URL: `http://127.0.0.1:{port}/v1`
- 요청/응답: `application/json; charset=utf-8`. POST에서 다른 Content-Type은 `415`.
- 필수 헤더:

| 헤더 | 값 |
|---|---|
| `Authorization` | `Bearer <token>` (`/v1/health` 제외) |
| `Content-Type` | `application/json` |
| `X-Jev-Protocol` | 정수. 현재 `1`. 서버가 지원하지 않으면 `426` |
| `X-Request-Id` | (선택) UUID. 서버가 응답과 로그에 그대로 사용, 없으면 생성 |

- 본문 최대 크기 1 MiB (`413`). `user_content`, `assistant_content` 각각 최대 256 KiB.
- `agent` 형식: `^[a-z0-9][a-z0-9_-]{1,31}$` (예: `hermes`, `pi`, `codex`, `opencode`).
- 세션 키: `session_key = f"{agent}_{session_id}"`. 단, `session_id`가 이미 `{agent}_`로 시작하면 중복 접두하지 않습니다 (Hermes 기존 `hermes_<session_id>` 호환).
- 시각은 **core 수신 시각**을 기준으로 저장합니다. `client_ts`는 참고 정보입니다.
- 모든 에러 응답 형식 (§5.9):

```jsonc
{ "ok": false,
  "error": { "code": "QUEUE_FULL", "message": "writer queue is full",
             "retryable": true, "retry_after_ms": 500, "request_id": "..." } }
```

### 5.2 `GET /v1/health` (인증 없음)

최소 정보만 반환합니다 (auto-start 판정용). Origin 헤더가 있는 요청은 거부합니다 (§10).

```jsonc
// 200
{ "status": "ready",          // "starting" | "ready" | "degraded" | "shutting_down"
  "protocol": 1,
  "version": "0.2.0" }
```

`degraded`는 동작은 하지만 Jev circuit이 open이거나 DB 쓰기 문제가 있는 경우입니다. HTTP 상태는 `starting/shutting_down`이면 503, 나머지 200.

### 5.3 `POST /v1/prefetch`

**요청**

```jsonc
{
  "agent": "hermes",
  "session_id": "20260929_104012_df1103",
  "query": "사용자 발화 또는 검색 질의",        // 필수, 최대 8000자
  "options": {                                  // 모두 선택
    "scope": "all",                             // "all"(기본) | "agent" (해당 agent 메모리만)
    "max_chars": 6000,                          // context 블록 최대 길이
    "timeout_ms": 1500,                         // 서버측 전체 예산 (200~10000)
    "rerank": true                              // false면 RRF-only
  }
}
```

**응답 200**

```jsonc
{
  "ok": true,
  "context": "## Mnemosyne Context\n- ...",     // 결과가 없으면 "" (빈 문자열)
  "meta": {
    "request_id": "...",
    "degraded": false,
    "degraded_reason": null,                     // "jev_unavailable" | "jev_timeout" | "budget_exceeded" | "rerank_disabled"
    "rerank": "jev",                             // "jev" | "skipped" | "failed"
    "lanes": { "fts": 12, "vector": 20, "importance": 5, "graph": 0 },
    "latency_ms": 312
  }
}
```

**의미 [확정]**

- Jev 장애/타임아웃은 **에러가 아니라 degraded 200**입니다. lanes+RRF(1단계) 결과를 먼저 만들고, 남은 예산 내에서만 Jev rerank(2단계)를 시도합니다. 실패하면 1단계 결과를 반환합니다.
- 5xx/4xx는 인증·검증·NOT_READY·과부하일 때만 사용합니다.
- 어댑터는 어떤 에러에서도 **빈 문자열**로 계속 진행합니다 (모델이 보는 계약 불변).
- 출력 형식(`## Mnemosyne Context`)은 기존 `core.j1_engine`의 결과를 **그대로** 사용합니다.

### 5.4 `POST /v1/turns` (sync_turn 대체)

**요청**

```jsonc
{
  "idempotency_key": "hermes:20260929_104012_df1103:12",  // 선택. 없으면 서버가 파생 (§6.1)
  "agent": "hermes",
  "session_id": "20260929_104012_df1103",
  "turn_seq": 12,                    // 선택(권장). 세션 내 단조 증가 정수
  "user_content": "...",
  "assistant_content": "...",
  "messages": [ { "role": "user", "content": "..." } ],   // 선택. 서버가 크기 제한 후 사용
  "client_ts": "2026-09-29T10:40:12+09:00",                // 참고용
  "mode": "async"                    // "async"(기본) | "sync"
}
```

**응답: async (기본) → `202 Accepted`**

`ledger`에 `received` 상태가 **내구적으로 커밋된 뒤** 반환합니다. 이후 게이트 판정과 저장은 백그라운드에서 진행합니다.

```jsonc
{ "ok": true, "status": "accepted", "turn_id": "t_01J...", "deduplicated": false }
```

**응답: sync → `200 OK`** (판정과 저장 완료까지 대기. 디버깅/테스트용, 어댑터 기본값 아님)

```jsonc
{
  "ok": true,
  "status": "stored",                  // "stored" | "skipped" | "pending_gate"
  "turn_id": "t_01J...",
  "deduplicated": false,
  "decisions": {
    "user":      { "action": "KEEP", "reason": "G-qual: ..." },        // "KEEP" | "SKIP"
    "assistant": { "action": "SKIP", "reason": "G-AS: type=context" }
  },
  "memory_ids": ["m_..."]
}
```

**중복 요청 (같은 키, 같은 payload 해시) →** 최초 결과를 그대로 반환하고 `"deduplicated": true`. 처리 중이면 `202`, 완료됐으면 `200`(status 포함).

**충돌 (같은 키, 다른 payload) →** `409 IDEMPOTENCY_CONFLICT`.

**게이트 판정 규칙 [확정, 기존 로직 이동]**: 4-way 분기(both KEEP → 둘 다 저장 / user SKIP → assistant만 / asst SKIP → user만 / both SKIP → 저장 없음)를 **core가 수행**합니다. 저장 형식은 기존대로 `[USER] ...` / `[ASSISTANT] ...` prefix + importance + scope이며, `source_agent`와 세션 키를 메타데이터에 추가합니다.

### 5.5 `GET /v1/turns/{turn_id}`

ledger 상태 조회 (디버깅/테스트용).

```jsonc
{ "ok": true, "turn_id": "t_01J...", "status": "stored",
  "attempts": 1, "decisions": { ... }, "memory_ids": ["m_..."],
  "received_at": "...", "updated_at": "...", "last_error": null }
```

### 5.6 `POST /v1/spool/flush`

스풀 디렉터리를 즉시 replay합니다. 본문 없음.

```jsonc
{ "ok": true, "files": 2, "turns_replayed": 41, "deduplicated": 3, "failed": 0 }
```

### 5.7 `GET /v1/status`, `GET /v1/metrics` (인증 필요)

`/v1/status`는 상세 상태를, `/v1/metrics`는 §14의 지표를 JSON으로 반환합니다.

```jsonc
// /v1/status
{ "status": "ready", "uptime_s": 8123, "version": "0.2.0", "protocol": 1,
  "embedding_model": "<model id>",
  "db": { "path": "...", "writable": true, "journal_mode": "wal", "synced_folder_warning": false },
  "jev": { "circuit": "closed", "last_ok_at": "...", "consecutive_failures": 0 },
  "queues": { "writer_depth": 0, "pending_gate": 0, "spool_files": 0 } }
```

### 5.8 `POST /v1/admin/shutdown`

graceful 종료 (§4.4). 응답 `202 {"ok":true,"status":"shutting_down"}`. 업데이트 배포 시 사용.

### 5.9 에러 코드표 [확정]

| HTTP | code | retryable | 설명 / 클라이언트 동작 |
|---|---|---|---|
| 400 | `INVALID_REQUEST` | ✗ | 스키마/형식 오류. 재시도하지 말고 로그 |
| 401 | `UNAUTHORIZED` | ✗ | 토큰 없음/불일치. `token` 파일 재로드 후 1회만 재시도 |
| 403 | `FORBIDDEN_ORIGIN` | ✗ | Origin/Host 검증 실패 (브라우저 요청 차단) |
| 404 | `NOT_FOUND` | ✗ | 경로 또는 turn_id 없음 |
| 409 | `IDEMPOTENCY_CONFLICT` | ✗ | 같은 키에 다른 payload. 키 생성 버그이므로 로그 |
| 413 | `PAYLOAD_TOO_LARGE` | ✗ | 본문/필드 크기 초과. 어댑터가 잘라서 재전송하지 말고 로그 |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | ✗ | Content-Type 오류 |
| 426 | `PROTOCOL_UNSUPPORTED` | ✗ | 어댑터/코어 버전 불일치. 로그 후 degrade |
| 429 | `RATE_LIMITED` | ✓ | `retry_after_ms` 준수 |
| 500 | `INTERNAL` | ✓ (1회) | 서버 버그. 1회 재시도 후 스풀/빈 블록 |
| 503 | `NOT_READY` | ✓ | 기동 중. 짧게 재시도 |
| 503 | `QUEUE_FULL` | ✓ | writer 큐 포화. `retry_after_ms` 준수, 초과 시 스풀 |
| 503 | `SHUTTING_DOWN` | ✓ | 종료 중. 스풀 |
| 503 | `DB_UNAVAILABLE` | ✓ | DB 잠금/접근 불가. 긴 백오프(1s+) 후 스풀 |
| 504 | `TIMEOUT` | ✓ | 서버측 예산 초과 (`/turns` sync 등) |

### 5.10 클라이언트 재시도 규칙 [권장]

| 호출 | connect 타임아웃 | 전체 타임아웃 | 재시도 | 최종 실패 시 |
|---|---|---|---|---|
| `/health` | 200ms | 300ms | 없음 | "core 없음"으로 간주 → 자동 기동 시도 |
| `/prefetch` | 200ms | 1500ms | 최대 1회 (연결 오류 한정) | **빈 문자열** 반환 |
| `/turns` (async) | 200ms | 3000ms | 최대 2회, 지터 100~300ms | **스풀에 적재** |

`/turns`는 멱등성 키가 있으므로 재시도해도 안전합니다. `/prefetch`는 읽기이므로 안전하지만 지연 예산 때문에 재시도를 제한합니다.

---

## 6. 멱등성 설계

### 6.1 키 [확정]

- 클라이언트가 `idempotency_key`를 제공하면 그대로 사용합니다 (형식 `^[A-Za-z0-9_.:-]{8,128}$`). 권장 형식: `{agent}:{session_id}:{turn_seq}`.
- 제공하지 않으면 서버가 파생합니다.

```
idem_key = "d:" + sha256(
    "v1\0" + agent + "\0" + session_id + "\0" + str(turn_seq or "") + "\0" +
    sha256(norm(user_content)) + "\0" + sha256(norm(assistant_content))
).hexdigest()[:40]
```

`norm` = 개행 통일(`\r\n`→`\n`) + 앞뒤 공백 제거. 스풀 replay 시에도 어댑터가 만든 키를 그대로 사용하므로 같은 턴이 중복 저장되지 않습니다.

### 6.2 payload 해시

`payload_hash = sha256(agent, session_id, turn_seq, norm(user), norm(assistant))`. 같은 키 + 같은 해시 → 중복(정상), 같은 키 + 다른 해시 → `409`.

### 6.3 ledger 스키마 (`core_state.db`, writer 스레드가 소유)

```sql
CREATE TABLE IF NOT EXISTS ingest_ledger (
  idem_key       TEXT PRIMARY KEY,
  turn_id        TEXT NOT NULL UNIQUE,
  payload_hash   TEXT NOT NULL,
  agent          TEXT NOT NULL,
  session_key    TEXT NOT NULL,
  turn_seq       INTEGER,
  status         TEXT NOT NULL CHECK (status IN
                   ('received','gated','stored','skipped','pending_gate','failed')),
  decisions_json TEXT,
  memory_ids_json TEXT,
  payload_json   TEXT,            -- 원문. 종료 상태(stored/skipped/failed)가 되면 NULL로 비움
  attempts       INTEGER NOT NULL DEFAULT 0,
  last_error     TEXT,
  received_at    TEXT NOT NULL,
  updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_status ON ingest_ledger(status, received_at);
CREATE INDEX IF NOT EXISTS idx_ledger_updated ON ingest_ledger(updated_at);

CREATE TABLE IF NOT EXISTS core_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- 예: embedding_model, schema_version, created_at
```

- 원문은 처리 중에만 보관하고 종료 상태에서 지웁니다 (대화 원문이 sidecar에 남지 않도록).
- ledger 보존 기간은 30일이며 이후 행을 삭제합니다 (`updated_at` 기준, 일 1회).

### 6.4 크래시 복구 [확정] / crash window [확인 필요]

- 기동 시 `received / gated / pending_gate` 행을 재큐잉합니다 (`attempts` 증가, 5회 초과 시 `failed`).
- **크래시 윈도우**: mnemosyne에 `remember()` 커밋 후, ledger를 `stored`로 갱신하기 전에 프로세스가 죽으면 재큐잉 시 중복 저장될 수 있습니다.
  - **1안**: `remember()` 메타데이터에 `idem_key`를 함께 저장하고, 재큐잉 전 그 마커를 조회해 이미 저장됐으면 `stored`로 마감합니다.
  - **2안 (1안이 불가능할 때)**: 윈도우가 ms 단위임을 근거로 **중복 1건 허용**하고 문서화합니다.
  - `BeamMemory.remember()`가 메타데이터 저장과 조회를 지원하는지에 따라 결정합니다 (§12 Q1).

---

## 7. 서버 내부 구조

### 7.1 기술 선택 [권장]

- 서버: `asyncio` 기반 경량 HTTP (`aiohttp` 또는 `starlette+uvicorn` 중 의존성이 가벼운 쪽). 로컬 전용이므로 프레임워크는 최소화합니다.
- Jev 호출: 기존 `gateway/write_gate.py`, `j1_pipeline.py`가 **동기 HTTP**라면 로직은 수정하지 않고 `asyncio.to_thread` + 세마포어로 감쌉니다. (async 클라이언트 전환은 후속 최적화)
- 스레드 구성: `db-writer`(1) + `db-reader`(2, 설정) + `embed`(2~4, 설정) + 이벤트 루프.

### 7.2 SingleWriter — writer 큐 골격 [확정]

```python
# jev_mem_core/writer.py
from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Callable

log = logging.getLogger("jev_mem.writer")


class QueueFull(Exception):
    """writer 큐 포화 → HTTP 503 QUEUE_FULL"""


class WriterStopped(Exception):
    """종료 중 → HTTP 503 SHUTTING_DOWN"""


@dataclass
class _Job:
    fn: Callable[["WriterContext"], Any]   # writer 스레드에서만 실행됨
    fut: Future
    label: str
    enqueued_at: float


class WriterContext:
    """writer 스레드가 소유하는 자원 묶음. 다른 스레드는 절대 접근하지 않는다."""
    def __init__(self, beam, state_conn):
        self.beam = beam              # BeamMemory (mnemosyne.db 쓰기 커넥션)
        self.state = state_conn       # sqlite3.Connection (core_state.db)


_STOP = object()


class SingleWriter:
    """
    DB 쓰기 전담 스레드 1개 + 큐.
    - 쓰기 커넥션(BeamMemory, core_state)은 이 스레드가 만들고 이 스레드만 사용한다.
    - job 하나 = 짧은 트랜잭션 하나. (네트워크 I/O, Jev 호출, 임베딩 계산 금지)
    """

    def __init__(self, context_factory: Callable[[], WriterContext],
                 max_depth: int = 500, slow_job_warn_ms: int = 200,
                 on_close: Callable[[WriterContext], None] | None = None):
        self._factory = context_factory
        self._on_close = on_close
        self._q: queue.Queue = queue.Queue(maxsize=max_depth)
        self._slow_ms = slow_job_warn_ms
        self._accepting = True
        self._ready = threading.Event()
        self._init_error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, name="db-writer")

    # ---- lifecycle ---------------------------------------------------
    def start(self, timeout: float = 60.0) -> None:
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("writer init timeout")
        if self._init_error:
            raise self._init_error

    def stop(self, timeout: float = 10.0) -> None:
        """새 job 거부 → 큐에 남은 job drain → 커넥션 정리."""
        self._accepting = False
        self._q.put(_STOP)               # 남은 job 뒤에 도달하므로 자연스럽게 drain됨
        self._thread.join(timeout)
        if self._thread.is_alive():
            log.error("writer did not stop within %.1fs", timeout)

    # ---- API (이벤트 루프에서 호출) ------------------------------------
    @property
    def depth(self) -> int:
        return self._q.qsize()

    def submit(self, fn: Callable[[WriterContext], Any], label: str = "job") -> "asyncio.Future":
        if not self._accepting:
            raise WriterStopped()
        fut: Future = Future()
        try:
            self._q.put_nowait(_Job(fn, fut, label, time.monotonic()))
        except queue.Full:
            raise QueueFull() from None
        return asyncio.wrap_future(fut)   # 이벤트 루프에서 await 가능

    # ---- writer thread -------------------------------------------------
    def _run(self) -> None:
        try:
            ctx = self._factory()
        except BaseException as e:        # noqa: BLE001
            self._init_error = e
            self._ready.set()
            return
        self._ready.set()
        try:
            while True:
                job = self._q.get()
                if job is _STOP:
                    break
                if not job.fut.set_running_or_notify_cancel():
                    continue              # 호출자가 취소함
                t0 = time.monotonic()
                try:
                    job.fut.set_result(job.fn(ctx))
                except BaseException as e:   # noqa: BLE001
                    job.fut.set_exception(e)
                dur_ms = (time.monotonic() - t0) * 1000
                if dur_ms > self._slow_ms:
                    log.warning("slow writer job %s: %.0fms (queued %.0fms)",
                                job.label, dur_ms, (t0 - job.enqueued_at) * 1000)
        finally:
            try:
                if self._on_close:
                    self._on_close(ctx)   # wal_checkpoint(TRUNCATE), close()
            except Exception:             # noqa: BLE001
                log.exception("writer close failed")
```

**규칙 [확정]**

- job 함수는 **DB 작업만** 합니다. 임베딩 계산, Jev 호출, 파일 I/O를 넣지 않습니다. (`slow_job_warn_ms` 초과 시 경고 로그)
- job 하나는 트랜잭션 하나입니다 (`BEGIN IMMEDIATE` … `COMMIT`). 실패 시 롤백 후 예외가 호출자에게 전달됩니다.
- `QueueFull`은 HTTP `503 QUEUE_FULL` (`retry_after_ms: 500`)로 변환합니다. 큐 크기는 기본 500.
- 임베딩을 **락 밖에서 미리 계산**할 수 있으면 그렇게 합니다. `BeamMemory.remember()`가 임베딩 계산과 INSERT를 한 덩어리로 수행한다면 임베딩 시간만큼 write가 직렬화되므로 §12 Q2에서 확인합니다.

### 7.3 ReaderPool [확정, 세부는 확인 필요]

```python
# jev_mem_core/readers.py
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable


class ReaderPool:
    """읽기 전용 커넥션 풀. 스레드마다 커넥션 1개 (thread-local)."""

    def __init__(self, reader_factory: Callable[[], Any], workers: int = 2):
        self._factory = reader_factory
        self._local = threading.local()
        self._ex = ThreadPoolExecutor(max_workers=workers,
                                      thread_name_prefix="db-reader",
                                      initializer=self._init_thread)

    def _init_thread(self) -> None:
        self._local.beam = self._factory()    # read-only 모드 (mode=ro, WAL)

    async def run(self, fn: Callable[[Any], Any]) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._ex, lambda: fn(self._local.beam))

    def close(self) -> None:
        self._ex.shutdown(wait=True)
```

- `core.j1_engine.run(beam, ...)`은 `beam`을 받으므로 reader용 `BeamMemory` 인스턴스가 **읽기 전용 커넥션으로 만들어질 수 있는지**가 관건입니다 (§12 Q3). 불가능하면 reader도 같은 프로세스 내 별도 `BeamMemory` 인스턴스로 만들되 쓰기 경로를 호출하지 않는 규율로 대체합니다.
- 임베딩 모델은 프로세스에서 **1회만 로드**하고 reader/writer 경로가 공유합니다.

### 7.4 turn 파이프라인 골격 [확정]

```python
# jev_mem_core/pipeline.py  (골격)
async def process_turn(req: TurnRequest, ctx: CoreContext) -> TurnResult:
    # 1) 내구적 수신: ledger 'received' 커밋 (writer 큐). 중복이면 기존 결과 반환.
    rec = await ctx.writer.submit(lambda w: ledger_receive(w.state, req), "ledger_receive")
    if rec.deduplicated:
        return rec.as_result()

    # async 모드면 여기서 202를 반환하고 이후 단계는 백그라운드 태스크로 진행
    async with ctx.session_lock(req.session_key):          # 같은 세션은 순서 보장, 세션 간 병렬
        # 2) 게이트 판정: 네트워크 I/O → writer 밖에서 수행
        try:
            async with ctx.jev_sem:                        # 전역 동시성 제한 (기본 4)
                ctx.breaker.before_call()                  # open이면 JevUnavailable
                decisions = await asyncio.to_thread(ctx.gate.evaluate_both, req)
                ctx.breaker.on_success()
        except (JevUnavailable, JevTimeout, JevError) as e:
            ctx.breaker.on_failure(e)
            return await handle_gate_failure(req, rec, ctx, e)   # §8: pending_gate 등

        await ctx.writer.submit(lambda w: ledger_mark(w.state, rec.key, "gated", decisions), "ledger_gated")

        # 3) 저장: 4-way 분기 결과를 한 트랜잭션(짧게)으로 commit
        vecs = await ctx.embedder.embed_for(req, decisions)   # 락 밖에서 (가능하다면, §12 Q2)
        mem_ids = await ctx.writer.submit(
            lambda w: store_kept(w.beam, req, decisions, vecs), "store_turn")

        # 4) 종료 상태 기록 + 원문 비우기
        status = "stored" if mem_ids else "skipped"
        await ctx.writer.submit(
            lambda w: ledger_finish(w.state, rec.key, status, decisions, mem_ids), "ledger_finish")
        return TurnResult(status, decisions, mem_ids)
```

- `session_lock`은 `(agent, session_id)`별 `asyncio.Lock`이며 LRU로 정리합니다 (유휴 10분 이상 제거).
- `turn_seq`가 있으면 lock 내부에서 순서를 정렬하고, 없으면 도착 순서를 따릅니다.
- `store_kept`는 기존 저장 형식(`[USER]`/`[ASSISTANT]` prefix + importance + scope)을 유지하고 메타데이터에 `source_agent`, `session_key`, (가능하면) `idem_key`를 추가합니다.

### 7.5 prefetch 파이프라인 골격 [확정]

```python
async def process_prefetch(req: PrefetchRequest, ctx: CoreContext) -> PrefetchResult:
    budget = Deadline(req.options.timeout_ms)

    # 1단계: lanes → RRF → 보수적 필터 (DB 읽기 + 임베딩). Jev 불필요.
    stage1 = await ctx.readers.run(lambda beam: j1_engine.retrieve(beam, req.query, ...))

    # 2단계: Jev choice 재순위화 (남은 예산 내에서만)
    if req.options.rerank and budget.remaining_ms > MIN_RERANK_BUDGET_MS and ctx.breaker.allow():
        try:
            async with ctx.jev_sem:
                ranked = await asyncio.wait_for(
                    asyncio.to_thread(j1_engine.rerank, stage1, ...),
                    timeout=budget.remaining_s)
            ctx.breaker.on_success()
            return render(ranked, degraded=False)
        except (asyncio.TimeoutError, JevError):
            ctx.breaker.on_failure(...)
            return render(stage1, degraded=True, reason="jev_timeout")   # RRF-only
    return render(stage1, degraded=True, reason="budget_exceeded")
```

- `render`는 기존 `## Mnemosyne Context` 포맷 그대로이며, 각 항목이 **저장된 과거 데이터임**을 구분하도록 블록 상단에 고정 헤더를 유지합니다. 메모리 오염 완화를 위해 출처(`source_agent`)를 항목에 표기합니다 [권장].
- 이를 위해 `core/j1_engine.run`을 `retrieve()`(1단계)와 `rerank()`(2단계)로 나누고, 기존 `run()`은 둘을 합친 래퍼로 유지합니다 (기존 호출부 호환). §12 Q4 참조.

---

## 8. Jev 장애 처리 [확정]

### 8.1 Circuit breaker

| 상태 | 동작 |
|---|---|
| closed | 정상 호출 |
| open | 호출 생략 (즉시 실패 취급). 30초 후 half-open |
| half-open | 1건만 시험 호출. 성공 시 closed, 실패 시 open 재진입 |

- 전이 조건: 연속 실패 5회 → open. (설정값: `breaker_failures`, `breaker_open_s`)
- 5xx/타임아웃은 기존 로직대로 1회 재시도를 유지하되, **전역 동시성 제한**(기본 4)과 함께 적용합니다. 에이전트 수가 늘어도 Jev 호출이 폭증하지 않도록 합니다.
- HTTP 429는 `Retry-After`를 존중하고 breaker 실패에는 가산하지 않습니다.

### 8.2 write gate 실패 정책 (`on_gate_failure`)

| 값 | 동작 | 비고 |
|---|---|---|
| `spool` (**기본**) | ledger를 `pending_gate`로 두고 원문 보관. Jev 복구 후 재판정 | 데이터 손실 없음, 저장 지연 |
| `skip` | 저장하지 않음 (`skipped`, reason=`gate_unavailable`) | 단순하지만 누락 발생 |
| `store_ungated` | 낮은 importance + `gated=false` 메타로 저장 | 노이즈 유입 위험, 비권장 |

- `pending_gate` 재판정 루프: circuit이 closed일 때 60초마다 오래된 순으로 최대 20건 처리.
- 24시간 경과한 `pending_gate`는 `failed(reason=expired)`로 종료하고 원문을 삭제합니다 (`pending_gate_max_age_h`).

### 8.3 prefetch 정책

Jev 장애 시 **Mnemosyne-only(RRF) degraded 응답**이 1급 동작입니다 (§5.3). 에러가 아닙니다.

---

## 9. 스풀 (core 다운 대비) [확정]

### 9.1 어댑터 측 기록

- 위치: `%LOCALAPPDATA%\jev-mem\spool\<agent>\<agent>-<pid>-<yyyymmdd>.jsonl`
- **프로세스별 파일**을 사용합니다. 여러 프로세스가 같은 파일에 동시에 append하면 Windows에서 줄이 섞일 수 있습니다.
- 각 줄은 `POST /v1/turns` 요청 본문 그대로이며 **반드시 `idempotency_key`를 포함**합니다. 한 줄 = 한 JSON 객체(개행 없음, UTF-8).
- 스풀에는 `/turns`만 기록합니다. prefetch는 재현할 이유가 없으므로 기록하지 않습니다.
- 용량 상한: 에이전트별 50 MiB. 초과 시 가장 오래된 파일부터 삭제하고 경고 로그를 남깁니다.

### 9.2 스풀 기록 조건

`/turns` 최종 실패(§5.10) 시: 연결 불가, 5xx 재시도 소진, `QUEUE_FULL`/`NOT_READY` 재시도 소진. `4xx`(재시도 불가)는 스풀하지 않고 로그만 남깁니다.

### 9.3 core 측 replay

1. 기동 시, 그리고 `POST /v1/spool/flush` 및 10분 주기로 스풀 디렉터리를 스캔합니다.
2. 파일을 `*.jsonl.processing`으로 **원자적 rename** 후 줄 단위로 `process_turn`에 투입합니다 (멱등성 키로 중복 방지).
3. 모든 줄이 종료 상태(또는 `pending_gate`로 ledger 인계)가 되면 파일을 삭제합니다.
4. 파싱 불가 줄은 `spool\_corrupt\`로 옮기고 계속 진행합니다.
5. 다른 프로세스가 아직 쓰고 있는 파일(마지막 수정 10초 이내)은 건너뜁니다.

---

## 10. 보안 [확정]

- **바인딩**: `127.0.0.1` 고정 (`0.0.0.0`, `localhost` 금지).
- **토큰**: 최초 기동 시 32바이트 랜덤 토큰을 `token` 파일에 생성 (현재 사용자만 읽기 가능하도록 ACL 설정). 모든 요청(`/v1/health` 제외)에 `Authorization: Bearer` 필수, 상수 시간 비교.
- **브라우저 차단**: 브라우저의 임의 웹페이지가 localhost로 요청하는 것을 막기 위해
  - `Origin` 헤더가 있으면 `403 FORBIDDEN_ORIGIN`
  - `Host` 헤더가 `127.0.0.1:<port>`가 아니면 `403` (DNS rebinding 방어)
  - POST는 `Content-Type: application/json`이 아니면 `415` (단순 CSRF 방어)
- **입력 제한**: 본문 1 MiB, 필드별 크기 제한 (§5.1). 잘못된 UTF-8은 `400`.
- **로그**: 요청 본문 원문은 로그에 남기지 않습니다 (길이·해시·agent·session만). 기존 `jev_trace.log`는 기존 정책을 따릅니다.
- **저장 데이터 취급 (메모리 오염)**: assistant 발화에는 웹 문서·툴 출력의 인용이 섞일 수 있습니다. 저장 시 `source_agent`를 태깅하고, context 블록은 "과거 저장 데이터(참고용)"임을 표시해 다른 에이전트가 지시문으로 오인하지 않도록 합니다 [권장].

---

## 11. 어댑터 명세

### 11.1 공통 클라이언트 계약 [확정]

- 요청마다 새 연결을 사용합니다 (상시 연결 없음: 슬립 복귀 후 stale 연결 문제 방지).
- `core.json`에서 포트를, `token` 파일에서 토큰을 읽습니다. 401 시 토큰을 다시 읽고 1회만 재시도합니다.
- 재시도/타임아웃은 §5.10을 따르고, 실패 시 동작은 다음과 같습니다.
  - prefetch → **빈 문자열**
  - turns → **스풀 적재**
- 어댑터에는 비즈니스 로직(게이트 판정, 4-way 분기, 재순위화)을 두지 않습니다.
- 자동 기동은 §4.3을 따릅니다.
- 공용 CLI (`jev-mem-client`, 의존성 없는 단일 Python 파일, urllib 사용)를 함께 제공합니다: `jev-mem-client prefetch --agent codex` / `jev-mem-client turn --agent codex`(stdin JSON). 셸 hook 기반 에이전트가 사용합니다.

### 11.2 Hermes 어댑터 (`harnesses/hermes_j1.py`) [확정]

| 항목 | 변경 |
|---|---|
| `prefetch(query, *, session_id="")` | 시그니처 유지. `POST /v1/prefetch` 호출 → `context` 반환. 실패 시 `""` |
| `sync_turn(user, assistant, *, session_id="", messages=None)` | 시그니처 유지. `POST /v1/turns` (async, fire-and-forget). 4-way 분기 코드 **삭제** (core로 이동) |
| base `MnemosyneMemoryProvider` 상속 | 임베디드 경로는 제거 (base fallback 금지). 상속이 Hermes 플러그인 인터페이스에 필요한 부분만 남김 |
| 세션 접두사 | `hermes_<session_id>` 유지 (서버가 동일 규칙으로 생성) |
| 전환 플래그 | `JEV_MEM_MODE=rpc` (기본) / `embedded` (v0.1.0 동작으로 롤백, 배포 단위 스위치). 두 모드를 **동시에 실행하지 않음** |
| Hermes 코어 | **수정 금지**. 플러그인/외부 스크립트로만 변경 |

### 11.3 pi (TypeScript 확장) [권장]

- 위치: `~/.pi/agent/extensions/`. `fetch`로 §5 API를 직접 호출합니다 (Python 헬퍼 spawn 불필요).
- 턴 시작 시 prefetch → 컨텍스트 주입, 턴 종료 시 `/turns` 호출. `agent = "pi"`.
- 확장 API의 훅 명칭과 컨텍스트 주입 방식은 `@earendil-works/pi-coding-agent` 문서로 확인합니다 [확인 필요].

### 11.4 Codex CLI (hooks) [권장]

- `UserPromptSubmit` → `jev-mem-client prefetch`, `Stop` → `jev-mem-client turn`. `agent = "codex"`.
- hook의 입력(stdin JSON)과 출력(컨텍스트 주입) 포맷, 세션 ID 제공 방식은 Codex 문서로 확인합니다 [확인 필요].
- hook은 단발 프로세스이므로 CLI의 시작 비용을 측정하고, 문제가 있으면 curl 기반 스크립트로 대체합니다.

### 11.5 opencode (TypeScript 플러그인) [권장]

- pi와 같은 방식(`fetch` 직접 호출). `agent = "opencode"`. 플러그인 훅 명칭은 문서로 확인합니다 [확인 필요].

---

## 12. 확인 필요 항목 (구현 시작 전에 코드로 검증하고 결과 보고)

| # | 질문 | 결과에 따른 분기 |
|---|---|---|
| Q1 | `BeamMemory.remember()`가 임의 메타데이터(`source_agent`, `session_key`, `idem_key`)를 저장하고 조회할 수 있는가? | 가능 → §6.4 1안. 불가능 → 2안(중복 1건 허용)과 `source_agent`는 content/scope 규칙으로 인코딩할지 별도 협의 |
| Q2 | `remember()`가 임베딩 계산과 INSERT를 한 덩어리로 하는가? 사전 계산된 벡터를 받을 수 있는가? | 분리 가능 → 임베딩은 락 밖. 불가능 → remember() 전체가 writer 안에서 실행되므로 그 지연을 측정해 `slow_job_warn_ms`와 큐 크기 조정 |
| Q3 | `BeamMemory`(또는 하위 커넥션)를 read-only(`mode=ro`)로 열 수 있는가? 여러 인스턴스를 한 프로세스에서 동시에 열어도 안전한가? | 가능 → §7.3 그대로. 불가능 → 읽기용 별도 인스턴스 + 쓰기 메서드 미호출 규율 |
| Q3-1 | `BeamMemory` 초기화 시 WAL/`busy_timeout`/`synchronous` PRAGMA를 무엇으로 설정하는가? | §13 기준과 다르면 core 쪽에서 재설정 가능한지 확인 |
| Q4 | `core/j1_engine.run()`을 `retrieve()`(lanes+RRF+필터)와 `rerank()`로 분리할 수 있는가? | 가능 → §7.5. 불가능 → `run(..., rerank=False)` 파라미터 추가로 대체 (둘 다 기존 호출부 호환 유지) |
| Q5 | `write_gate.evaluate()`/`evaluate_assistant()`는 동기 HTTP인가? 재시도 로직이 함수 내부에 있는가? | 동기 → `to_thread`로 감쌈. 내부 재시도는 유지 |
| Q6 | Python 헬퍼에서 `AF_UNIX`가 필요한가? | HTTP로 결정했으므로 불필요. 참고용 확인만 |
| Q7 | Codex hook / pi ExtensionAPI / opencode 플러그인의 입출력 포맷과 세션 ID 제공 방식 | §11.3~11.5 세부 확정 |

---

## 13. DB 운영 [확정]

- **PRAGMA** (core가 연결마다 설정): `journal_mode=WAL`, `synchronous=NORMAL`(정전 시 마지막 트랜잭션 손실 가능하나 손상 없음 — 개인 메모리 용도에 적합), `busy_timeout=5000`(외부 도구 방어), `foreign_keys=ON`.
- **경로 검사**: 기동 시 DB 경로가 OneDrive/Dropbox/Google Drive 동기화 폴더 하위이면 `/v1/status`의 `synced_folder_warning=true`로 표시하고 로그에 경고합니다. 자동 이동은 하지 않습니다.
- **체크포인트**: 유휴 5분마다 `wal_checkpoint(PASSIVE)`. 종료 시 `TRUNCATE`.
- **백업**: 하루 1회 `VACUUM INTO 'backups\mnemosyne-YYYYMMDD.db'` (writer 큐를 거치지 않고 별도 읽기 커넥션에서 실행), 최근 7개 보관. `core_state.db`는 백업 대상이 아닙니다 (ledger/스풀 복구용 임시 상태).
- **임베딩 모델 고정**: `core_meta.embedding_model`에 model id를 기록하고, 기동 시 설정값과 불일치하면 **기동을 거부**하고 재색인 절차를 안내합니다 (조용히 벡터 공간이 섞이는 것을 방지).
- **스키마 마이그레이션**은 core만 수행합니다. 어댑터는 스키마에 접근하지 않습니다.
- **외부 프로세스의 직접 접근 금지**: 정비 목적의 직접 접근은 core 종료 후에만 수행합니다.

---

## 14. 관측성 [확정]

`/v1/metrics` (JSON)와 `jev_trace.log` 확장 이벤트로 다음을 남깁니다.

| 지표 | 설명 |
|---|---|
| `req_latency_ms{endpoint, p50/p95/p99}` | 엔드포인트별 지연 |
| `writer_queue_depth`, `writer_job_ms{label}` | 큐 깊이, job별 소요 |
| `jev_calls`, `jev_failures`, `jev_circuit`, `jev_latency_ms` | Jev 호출/실패/상태 |
| `prefetch_degraded_ratio` | degraded 응답 비율 |
| `turns{status}` | stored / skipped / pending_gate / failed 카운트 |
| `dedup_count` | 멱등성으로 걸러진 요청 수 |
| `spool_files`, `spool_replayed` | 스풀 잔량/replay 수 |
| `embed_ms`, `rss_mb` | 임베딩 지연, 프로세스 메모리 |

- 로그는 `logs\core.log`에 일 단위 로테이션(최근 14일).
- 기존 trace 이벤트(`write-gate`, `write-gate-as`)는 형식 유지하고 `agent`, `session_key`, `idem_key` 필드를 추가합니다.
- watchdog: 30초마다 자체 `/health`를 호출하고, 이벤트 루프 지연이 5초를 넘으면 경고 로그를 남깁니다.
- **재설계 트리거(§2.7)는 이 지표로 판단**합니다 (예: writer 큐 깊이가 지속적으로 50 초과, prefetch p95 > 1.5s, Jev 429 빈발).

---

## 15. 구현 단계와 수용 기준

| 단계 | 내용 | 수용 기준 |
|---|---|---|
| **P0** | §12 확인 항목 검증, 결과 보고 | Q1~Q5 답변 완료, 분기 결정 |
| **P1** | core 서버: HTTP, 인증, `/health`, `/status`, `SingleWriter`, `ReaderPool`, `/prefetch`, `/turns`, ledger, 멱등성 | 골든 테스트(임베디드 vs core 출력 동일), 단위 테스트, smoke_write_gate 7/7 유지 |
| **P2** | 스풀 + replay, circuit breaker, pending_gate 루프, 자동 기동, 싱글턴 | 카오스 테스트(§16.3) 통과 |
| **P3** | **pi 어댑터** (신규 경로, 회귀 위험 최소) | 실제 pi 세션에서 prefetch/turns 동작, core 다운/복구 시나리오 통과 |
| **P4** | Codex hook → opencode | 각 에이전트 동시 사용 시나리오 통과 (Hermes 없이 codex + pi 포함) |
| **P5** | **Hermes 어댑터 전환** (`JEV_MEM_MODE=rpc`, 플래그 뒤) | 골든 테스트 + 동시성 테스트 + 롤백(`embedded`) 리허설 성공 |

각 단계는 이전 단계가 수용 기준을 통과한 뒤 진행합니다. Hermes는 마지막입니다 (D9).

---

## 16. 테스트 계획

### 16.1 골든 테스트 [확정]

동일한 쿼리 N개(대표 20개 이상)에 대해 v0.1.0 임베디드 경로와 core `/v1/prefetch` 경로의 `## Mnemosyne Context`가 동일한지 비교합니다. Jev 재순위화의 비결정성이 있다면 rerank를 고정(모킹)하거나 결과 집합/순서 허용 오차를 명시합니다.

### 16.2 동시성 테스트 [확정]

- 클라이언트 프로세스 8개 × 각 200턴을 동시에 `/turns`에 전송.
- 무작위 10%는 같은 키로 중복 전송(재시도 모사).
- **기대값**: 고유 키 수 = 최종 ledger 종료 상태 행 수, 중복 저장 0, `SQLITE_BUSY` 등 DB 잠금 오류가 클라이언트에 노출되지 않음 (`QUEUE_FULL` 백프레셔는 허용).
- prefetch를 4개 클라이언트가 병행 호출하며 지연 측정 [권장 목표]: Jev 정상 시 p95 < 800ms, degraded 시 p95 < 300ms.

### 16.3 카오스 테스트 [확정]

| 시나리오 | 기대 동작 |
|---|---|
| core를 `kill -9`(강제 종료) 후 재기동 | ledger 미종료 행 재큐잉, 중복 저장 없음(또는 §6.4 2안이면 최대 1건) |
| core 다운 상태에서 어댑터가 턴 전송 | 스풀 적재 → core 기동 후 replay, 손실 0 |
| Jev 무응답/5xx 지속 | prefetch degraded 200, turns는 pending_gate, 복구 후 재판정 |
| 포트를 hang된 프로세스가 점유 | 새 core가 명확히 실패(exit 3), 어댑터는 스풀/빈 블록으로 동작 |
| 외부 프로세스가 DB를 오래 잠금 | `DB_UNAVAILABLE`, 스풀, 잠금 해제 후 복구 |
| 자동 기동 경쟁 (어댑터 4개 동시 spawn) | core 1개만 생존 |
| 토큰 파일 없음/불일치 | 401 → 재로드 1회 → degrade, 서버 안정 |
| 브라우저에서 `fetch('http://127.0.0.1:<port>/v1/prefetch')` | 403 (Origin 차단) |
| 1 MiB 초과 본문 | 413 |
| 슬립/복귀 후 요청 | 새 연결로 정상 처리 |

### 16.4 회귀 테스트

- 기존 `smoke_write_gate` 7/7 PASS를 core 경로에서도 유지.
- G-AS 판정 품질 (gold50: precision 0.744 / recall 0.935 / F1 0.829), J1 효과(recall@1 0.712)는 core 이전 후에도 **저하 없음**을 확인합니다 (로직 무수정이므로 동일해야 함).

---

## 17. 비목표

- 멀티 유저, 원격 접근, 인증 체계 확장
- 수백만 건 규모 저장소 최적화 (필요해지는 시점에 계측 기반으로 재설계)
- Docker/WSL 상시 운영
- 에이전트 간 메모리 파티셔닝(격리). 필요한 경우 `scope=agent` 옵션으로 조회 범위만 제한
- Hermes 코어 수정

---

## 부록 A. `config.toml` 예시

```toml
[server]
host = "127.0.0.1"
port = 47821
max_body_bytes = 1048576

[paths]
data_dir = "%LOCALAPPDATA%\\jev-mem"
mnemosyne_db = "%LOCALAPPDATA%\\jev-mem\\mnemosyne.db"

[writer]
max_queue_depth = 500
slow_job_warn_ms = 200

[readers]
workers = 2

[embedding]
workers = 2               # 임베딩 스레드풀 (2~4)
model_id = "<현재 사용 중인 fastembed model id>"

[jev]
max_concurrency = 4
request_timeout_ms = 4000
retries = 1
breaker_failures = 5
breaker_open_s = 30
on_gate_failure = "spool"          # "spool" | "skip" | "store_ungated"
pending_gate_max_age_h = 24
pending_gate_retry_interval_s = 60
pending_gate_batch = 20

[prefetch]
default_timeout_ms = 1500
min_rerank_budget_ms = 400

[spool]
max_bytes_per_agent = 52428800     # 50 MiB
replay_interval_s = 600
min_idle_s = 10

[ledger]
retention_days = 30

[backup]
enabled = true
keep = 7
```

## 부록 B. 어댑터 의사코드 (공통)

```python
def prefetch(agent, session_id, query) -> str:
    try:
        r = post("/v1/prefetch", {"agent": agent, "session_id": session_id, "query": query},
                 timeout=1.5, retries=1)          # 연결 오류에 한해 재시도
        return r["context"]
    except Exception:
        return ""                                  # 어떤 실패에도 빈 블록

def sync_turn(agent, session_id, user, assistant, turn_seq=None, messages=None):
    body = {"agent": agent, "session_id": session_id, "turn_seq": turn_seq,
            "user_content": user, "assistant_content": assistant, "messages": messages,
            "idempotency_key": f"{agent}:{session_id}:{turn_seq}" if turn_seq is not None else None,
            "mode": "async"}
    try:
        post("/v1/turns", body, timeout=3.0, retries=2)   # 멱등 → 재시도 안전
    except NonRetryable as e:
        log(e)                                             # 4xx: 스풀하지 않음
    except Exception:
        spool_append(agent, body_with_key(body))           # 키 반드시 포함
```
