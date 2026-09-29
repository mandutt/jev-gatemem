# JEV-Mnemosyne Middleware — 멀티 에이전트 전환 설계 v2

> 상태: **구현 전 아키텍처 확정안**
>
> 작성일: 2026-09-29
>
> 목적: Hermes 전용 임베디드 메모리 구조를 여러 에이전트가 하나의 Mnemosyne DB를 공유하는 중앙 Memory Core 구조로 전환
>
> 핵심 원칙: **Single DB Owner + Concurrent Request Handling + Serialized Writes**

---

## 0. 문서 목적

현재 `JEV-Mnemosyne Middleware`는 Hermes 프로세스 내부에 임베디드되어 있으며, Hermes의 `prefetch()`와 `sync_turn()`을 통해 Mnemosyne DB에 직접 접근한다. 이 구조에서는 Hermes 프로세스가 사실상 단일 DB writer이므로 동시성 문제가 구조적으로 발생하지 않는다.

본 설계의 목적은 이 구조를 다음과 같이 확장하는 것이다.

```text
Hermes ─┐
pi ─────┤
Codex ──┤──→ jev-mem-core ──→ mnemosyne.db
opencode┘
```

모든 에이전트가 하나의 통합 메모리를 공유하되, Mnemosyne DB에 직접 접근하는 프로세스는 `jev-mem-core` 하나로 제한한다.

본 설계에서 해결해야 하는 핵심 문제는 단순한 SQLite lock 회피가 아니다. 목표는 다음 네 가지를 동시에 만족하는 것이다.

1. 여러 에이전트가 동시에 실행되어도 DB writer가 하나로 유지된다.
2. prefetch/JEV 등의 읽기 작업은 필요할 경우 병렬 처리할 수 있다.
3. RPC timeout/retry로 동일한 turn이 중복 저장되지 않는다.
4. Core 장애가 발생해도 각 agent가 DB를 직접 쓰는 fallback으로 되돌아가지 않는다.

현재 `gateway/*`, `core/j1_engine.py`, Mnemosyne backend 및 기존 Hermes adapter의 핵심 로직은 가능한 한 재사용하며, Hermes 코어 자체는 수정하지 않는다.

---

# 1. 시스템 역할

JEV-Mnemosyne Middleware는 두 가지 핵심 역할을 수행한다.

## 1.1 Read — J1 reranking prefetch

에이전트 턴 시작 시 현재 query와 관련된 과거 메모리를 Mnemosyne에서 검색하고, JEV를 이용해 후보를 재순위화한 뒤 에이전트의 시스템 프롬프트에 다음 형태의 결과를 제공한다.

```text
## Mnemosyne Context
...
```

현재 J1 pipeline은 다음 흐름을 사용한다.

```text
FTS
vector
importance
graph
   ↓
RRF merge
   ↓
conservative filter
   ↓
JEV choice reranking
   ↓
Context block
```

현재 실측 결과는 recall@1 `0.500 → 0.712`, MRR `0.599 → 0.747`이다.

## 1.2 Write — LLM 기반 write gate

턴 종료 시 다음 인터페이스를 통해 저장 여부를 판단한다.

```python
sync_turn(
    user_content,
    assistant_content,
    session_id=...,
    messages=...
)
```

User 발화에는 G-qual, Assistant 발화에는 G-AS를 적용한다.

현재 정책은 다음과 같다.

```text
G-qual:
store == NO_STORE
and type == NO_STORE
and conf >= 0.6
→ SKIP

G-AS:
store == NO_STORE
or
(store == STORE and type == context)
→ SKIP
```

판정은 JEV API를 이용하며 trace에 기록한다.

저장되는 발화에는 다음과 같은 provenance가 포함된다.

```text
[USER] ...
[ASSISTANT] ...
importance
scope
```

---

# 2. 현재 구조

현재 구현은 다음 계층으로 구성된다.

```text
gateway/
  j1_pipeline.py
  write_gate.py
  trace.py

core/
  j1_engine.py

backends/
  mnemosyne.py

harnesses/
  hermes_j1.py
  j1_access.py
  wg_access.py
```

`core/j1_engine.py`와 `gateway/*`는 Hermes에 의존하지 않는 순수 로직으로 유지한다.

현재 Hermes adapter는 다음과 같은 역할을 수행한다.

```python
prefetch(...)
    ↓
core.j1_engine.run(...)
    ↓
Mnemosyne DB

sync_turn(...)
    ↓
write_gate
    ↓
BeamMemory.remember()
    ↓
Mnemosyne DB
```

현재 구조에서 DB writer는 Hermes 프로세스이다.

---

# 3. 멀티 에이전트 전환 목표

지원 대상은 다음과 같다.

| Agent     | Integration             |
| --------- | ----------------------- |
| Hermes    | Plugin                  |
| pi        | TypeScript ExtensionAPI |
| Codex CLI | hooks                   |
| opencode  | TypeScript plugin       |

모든 agent는 다음 DB를 공유한다.

```text
mnemosyne.db
```

목표는 다음과 같다.

```text
Hermes ─┐
pi ─────┤
Codex ──┤
opencode┤
... ────┘
       │
       ▼
┌─────────────────────────┐
│      jev-mem-core       │
│                         │
│ RPC/API                 │
│ Request Dispatcher      │
│ JEV concurrency control │
│ Read/Search             │
│ Write Queue             │
│ Idempotency             │
│ Mnemosyne               │
└────────────┬────────────┘
             │
             ▼
       mnemosyne.db
```

중요한 설계 원칙은 다음과 같다.

> **Core는 single-thread가 아니다. Core가 유일한 DB owner라는 것이 핵심이다.**

즉 여러 RPC 요청을 동시에 처리할 수 있지만, DB write transaction은 하나의 write queue를 통해 직렬화한다.

---

# 4. Core-as-Writer 아키텍처

## 4.1 DB ownership

`mnemosyne.db`에 접근하는 정상적인 application process는 `jev-mem-core` 하나뿐이다.

Agent adapter는 다음을 직접 수행하지 않는다.

```text
BeamMemory()
SQLite connection
Mnemosyne search
Mnemosyne remember()
fastembed loading
```

대신 다음과 같은 RPC만 사용한다.

```text
prefetch()
sync_turn()
health()
version()
```

이렇게 함으로써 DB writer ownership을 애플리케이션 구조에서 명확하게 하나로 만든다.

## 4.2 SQLite 동시성에 대한 정확한 원칙

SQLite 자체가 여러 writer를 물리적으로 실행할 수 없는 것은 아니다. SQLite는 여러 프로세스의 write transaction 요청을 내부적으로 직렬화한다.

그러나 본 시스템에서는 SQLite의 lock arbitration에 application concurrency를 의존하지 않는다.

즉 다음 구조를 사용하지 않는다.

```text
Agent A ──→ SQLite
Agent B ──→ SQLite
Agent C ──→ SQLite
```

WAL 및 `busy_timeout`은 SQLite의 정상적인 안정성 설정으로 사용할 수 있지만, 이것을 멀티 에이전트 write ownership 해결책으로 취급하지 않는다.

본 시스템의 concurrency guarantee는 다음에서 나온다.

```text
Multiple Agents
      ↓
Single Core
      ↓
Single Write Queue
      ↓
SQLite
```

---

# 5. Core 내부 concurrency model

Core는 다음과 같은 구조를 갖는다.

```text
             RPC requests
                  │
       ┌──────────┴──────────┐
       │                     │
     prefetch             sync_turn
       │                     │
       ▼                     ▼
 concurrent            write queue
 request handling           │
       │                    ▼
       │              serialized write
       │                    │
       └──────────┬─────────┘
                  ▼
              Mnemosyne
```

## 5.1 Read / prefetch

prefetch는 요청별로 병렬 처리할 수 있다.

주요 작업은 다음과 같다.

```text
DB candidate retrieval
RRF
filter
JEV reranking
Context formatting
```

단, JEV API에는 별도의 bounded concurrency limit을 둔다.

예:

```text
max_concurrent_jev_requests = N
```

N은 JEV provider의 실제 concurrency/rate limit을 확인한 뒤 결정한다.

Core의 목적은 무제한 병렬화를 하는 것이 아니라, agent 수가 증가해도 JEV와 RAM을 과도하게 압박하지 않는 것이다.

## 5.2 Write

`sync_turn`의 최종 DB mutation은 하나의 write queue를 통해 처리한다.

```text
Agent A ─┐
Agent B ─┼─→ sync_turn queue ─→ Writer ─→ Mnemosyne
Agent C ─┘
```

Writer는 transaction 단위로 다음을 수행한다.

```text
validate
→ idempotency check
→ memory write
→ commit
```

동일 시점에 두 agent가 요청하더라도 DB mutation은 한 번에 하나씩 수행된다.

## 5.3 중요한 원칙

다음은 허용한다.

```text
prefetch A
prefetch B
prefetch C
```

동시에 수행.

다음은 허용하지 않는다.

```text
write A
write B
```

동일 DB transaction을 동시에 수행.

즉 concurrency의 단위는 요청이고, serialization의 단위는 DB mutation이다.

---

# 6. RPC protocol

초기 구현에서는 localhost HTTP/JSON을 우선한다.

권장 endpoint:

```text
GET  /health
GET  /version
POST /prefetch
POST /sync_turn
```

예:

```json
{
  "request_id": "pi-20260929-000001",
  "agent": "pi",
  "session_id": "session_abc",
  "query": "현재 프로젝트의 memory architecture를 설명해줘"
}
```

응답:

```json
{
  "ok": true,
  "request_id": "pi-20260929-000001",
  "context": "## Mnemosyne Context\n..."
}
```

`sync_turn`도 동일한 `request_id`를 사용한다.

```json
{
  "request_id": "pi-20260929-000002",
  "agent": "pi",
  "session_id": "session_abc",
  "user_content": "...",
  "assistant_content": "..."
}
```

응답에는 최소한 다음 정보가 포함된다.

```json
{
  "ok": true,
  "request_id": "pi-20260929-000002",
  "status": "stored"
}
```

가능한 status:

```text
stored
skipped
duplicate
queued
degraded
error
```

---

# 7. Idempotency

멀티 프로세스 RPC에서 가장 중요한 추가 안전장치 중 하나이다.

문제 상황:

```text
Agent
  │
  │ sync_turn(request_id=X)
  ▼
Core
  │
  ├─ DB commit
  │
  X response lost
  │
Agent timeout
  │
  └─ retry(request_id=X)
```

이때 두 번째 요청이 동일 memory를 다시 저장하면 안 된다.

따라서 Core는 `request_id`를 이용해 이미 처리한 요청을 식별한다.

원칙:

```text
same request_id
→ same logical operation
→ no duplicate DB mutation
```

`request_id`는 client가 생성한다.

가능하면 write 요청에는 별도의 `turn_id`도 사용할 수 있다.

```text
request_id
    = transport-level idempotency

turn_id
    = logical conversation turn identity
```

두 값의 역할은 분리한다.

---

# 8. Transaction 및 write ordering

하나의 `sync_turn`에서 User와 Assistant의 저장 결과는 가능하면 하나의 logical operation으로 취급한다.

예:

```text
sync_turn
   │
   ├─ G-qual
   ├─ G-AS
   │
   └─ DB transaction
        ├─ user memory
        └─ assistant memory
```

최종 commit 이전에 프로세스가 종료되면 partial state가 남지 않도록 transaction boundary를 정의한다.

다만 JEV gate 호출 자체를 DB transaction 안에서 수행해서는 안 된다.

잘못된 구조:

```text
BEGIN
  ↓
JEV HTTP call
  ↓
INSERT
  ↓
COMMIT
```

권장 구조:

```text
JEV evaluation
  ↓
write decision
  ↓
BEGIN
  ↓
idempotency check
  ↓
INSERT/UPDATE
  ↓
COMMIT
```

이렇게 해야 외부 API latency가 DB transaction을 장시간 점유하지 않는다.

---

# 9. Agent / Session / Provenance

`agent`, `session_id`, `source_agent`는 서로 다른 개념으로 취급한다.

예:

```text
agent       = pi
session_id  = 20260929_project_x
source_agent = pi
```

## 9.1 Agent

현재 RPC 요청을 보내는 agent.

예:

```text
hermes
pi
codex
opencode
```

## 9.2 Session

해당 agent의 대화 또는 작업 session.

## 9.3 source_agent

해당 memory가 최초 생성된 agent provenance.

예:

```text
source_agent = hermes
```

이 정보는 메모리의 출처를 추적하기 위한 metadata이며, 자동으로 검색 isolation을 의미하지 않는다.

---

# 10. Provenance와 Search Scope의 분리

다음 두 개념을 분리한다.

```text
provenance
=
"이 memory는 어디에서 만들어졌는가?"

search scope
=
"이번 query에서 어떤 memory를 검색할 것인가?"
```

기본 정책은 모든 agent가 하나의 memory pool을 공유하는 것이다.

즉:

```text
Hermes memory
     ↕
shared memory
     ↕
pi memory
     ↕
Codex memory
```

특정 agent 또는 session의 memory만 검색해야 하는 경우에만 명시적인 scope filter를 적용한다.

따라서 `hermes_<session_id>` 같은 prefix를 사용하더라도 이것을 기본적인 검색 격리 장치로 사용하지 않는다.

---

# 11. Transport 선택

## 11.1 HTTP/JSON — 기본 권장

Windows 환경에서는 localhost HTTP를 기본 transport로 채택한다.

장점:

```text
TypeScript/Python/Go 모두 쉽게 사용 가능
curl로 debugging 가능
request/response boundary가 명확함
health endpoint 구현이 쉬움
향후 diagnostics/metrics 확장이 쉬움
```

localhost HTTP의 오버헤드는 본 시스템에서 JEV API 및 embedding/search 비용에 비해 중요하지 않다.

Core는 외부 네트워크가 아니라 다음에만 bind한다.

```text
127.0.0.1
```

## 11.2 TCP JSON-RPC

성능 또는 의존성 최소화가 필요할 경우 사용할 수 있다.

단, TCP는 message boundary를 보장하지 않으므로 다음 중 하나를 반드시 사용한다.

```text
NDJSON
또는
length-prefixed frames
```

단순히 `recv()` 한 번당 JSON 하나가 온다고 가정해서는 안 된다.

## 11.3 Unix Domain Socket

현재 대상이 Windows 11이므로 기본 transport로 사용하지 않는다.

## 11.4 stdio

각 agent마다 Core를 child process로 spawn하는 구조는 사용하지 않는다.

그렇게 하면:

```text
Hermes → core A
pi     → core B
Codex  → core C
```

가 되어 Core가 여러 개 실행되고 DB ownership 문제가 다시 발생한다.

---

# 12. Core lifecycle

Core는 장수 프로세스 하나로 실행한다.

권장 lifecycle:

```text
Windows startup
     ↓
jev-mem-core
     ↓
health = ready
     ↓
agents connect
```

Core가 이미 실행 중인 상태에서 두 번째 Core가 실행되는 것을 방지해야 한다.

HTTP를 사용하는 경우 지정 port의 bind 자체가 기본적인 single-instance guard가 된다.

추가로 `/health`에서 다음 정보를 제공한다.

```text
core_instance_id
core_version
protocol_version
mnemosyne_db_path
schema_version
uptime
status
```

예:

```json
{
  "status": "ready",
  "core_version": "0.2.0",
  "protocol_version": "1",
  "schema_version": "1",
  "core_instance_id": "..."
}
```

---

# 13. Core failure policy

Core가 죽었을 때 agent가 Mnemosyne DB에 직접 접근하는 fallback은 사용하지 않는다.

즉:

```text
Core UP
→ normal RPC mode

Core DOWN
→ degraded mode
```

## 13.1 prefetch failure

Core가 없으면:

```text
## Mnemosyne Context

```

또는 기존 adapter가 정의한 empty-context fallback을 반환한다.

Agent 자체의 작업은 계속 진행된다.

## 13.2 sync_turn failure

Core가 없으면 DB에 직접 쓰지 않는다.

초기 구현에서는:

```text
sync_turn
→ retry
→ failure log
→ return degraded
```

로 처리한다.

향후 데이터 손실을 줄일 필요가 확인되면 client-side durable outbox를 추가한다.

---

# 14. Durable Outbox — 향후 확장

다음 구조는 사용 가능하지만 v1의 필수 구성요소는 아니다.

```text
Agent
  │
  ├─ Core available
  │     ↓
  │   direct RPC
  │
  └─ Core unavailable
        ↓
      local outbox
        ↓
      Core recovery
        ↓
      replay
```

중요한 점은 outbox가 DB writer가 아니라는 것이다.

```text
outbox
=
durable pending request

Core
=
only DB writer
```

따라서 기존에 기각한 “파일 inbox 위임” 구조와 다르다.

파일이 직접 DB를 변경하지 않으며, Core가 재기동한 뒤 replay된 요청을 정상적인 write queue에서 처리한다.

---

# 15. Hermes adapter 전환

기존:

```text
Hermes
  ↓
MnemosyneMemoryProvider
  ↓
BeamMemory
  ↓
SQLite
```

변경:

```text
Hermes
  ↓
MnemosyneMemoryProvider
  ↓
Core RPC client
  ↓
jev-mem-core
  ↓
Mnemosyne
```

외부 Hermes 계약은 유지한다.

특히 다음은 유지한다.

```text
prefetch() signature
sync_turn() signature
## Mnemosyne Context format
failure fallback behavior
```

Hermes 코어 자체는 수정하지 않는다.

---

# 16. Hermes compatibility mode

기존 embedded implementation은 삭제하지 않는다.

다만 이것을 자동 fallback으로 사용하지 않는다.

허용되는 형태:

```text
MNEMOSYNE_MODE=core
```

기본값.

개발/rollback 용도:

```text
MNEMOSYNE_MODE=embedded
```

이렇게 명시적으로 선택했을 때만 기존 경로를 사용한다.

즉 다음 구조는 금지한다.

```text
Core down
   ↓
Hermes automatically writes DB
```

이 구조는 여러 agent가 다시 DB writer가 되는 가능성을 만들기 때문이다.

---

# 17. JEV concurrency

현재 JEV 호출 latency는 약 275ms이다.

멀티 agent 환경에서는 다음과 같은 상황이 가능하다.

```text
Hermes prefetch
pi prefetch
Codex prefetch
opencode prefetch
```

동시에 요청될 수 있다.

따라서 Core에는 JEV concurrency limit을 둔다.

```text
request
  ↓
JEV semaphore
  ↓
JEV API
```

예:

```text
max_jev_concurrency = configurable
```

초기값은 provider의 실제 concurrency/rate limit을 확인한 뒤 설정한다.

JEV 호출이 과도하게 쌓이면 전체 system memory service가 느려지는 것을 방지하기 위해 timeout과 queue policy를 둔다.

---

# 18. DB concurrency 및 connection policy

DB connection은 Core가 소유한다.

Agent가 SQLite connection을 직접 만들지 않는다.

Read는 가능한 범위에서 concurrent하게 처리할 수 있으나, Mnemosyne backend가 thread-safe인지 여부를 확인하기 전까지 무제한 connection sharing을 가정하지 않는다.

따라서 초기 구현에서는 다음 원칙을 사용한다.

```text
Core owns DB
Core owns Mnemosyne object
Core controls DB access
Write path is serialized
Read concurrency is bounded by verified backend safety
```

특히 `fastembed` model instance 역시 Core 프로세스에서 하나만 로드한다.

---

# 19. Error handling

RPC error는 다음 계층으로 구분한다.

```text
Transport error
Protocol error
Validation error
JEV error
Mnemosyne error
Database error
Timeout
Duplicate request
```

각 요청은 최소한 다음 정보를 trace에 기록한다.

```text
timestamp
request_id
agent
session_id
operation
duration
status
error type
```

민감한 원문 prompt/response 전체를 trace에 무조건 기록하지 않는다.

기존 `jev_trace.log`의 역할은 유지한다.

---

# 20. Retry policy

Retry는 operation별로 다르게 적용한다.

## prefetch

read operation이므로 제한적인 retry를 허용한다.

```text
timeout
→ short retry
→ failure
→ empty context
```

## sync_turn

write operation이므로 retry에는 반드시 `request_id`가 포함되어야 한다.

```text
timeout
→ retry same request_id
→ Core idempotency check
```

새로운 request_id로 동일 turn을 재전송해서는 안 된다.

## JEV

기존처럼 5xx/timeout에 한해 제한된 retry를 적용한다.

무제한 retry는 사용하지 않는다.

---

# 21. Core restart

Core가 재시작되면 다음 순서로 동작한다.

```text
process start
    ↓
load configuration
    ↓
open Mnemosyne
    ↓
load embedding model
    ↓
verify DB
    ↓
initialize JEV client
    ↓
start RPC server
    ↓
health = ready
```

`ready` 이전에는 agent 요청을 정상 처리하지 않는다.

Core startup 실패 시 DB를 변경하지 않은 상태에서 명확한 error를 출력한다.

---

# 22. DB migration

Mnemosyne schema migration은 Core startup 시 관리한다.

여러 agent가 각각 migration을 수행하지 않는다.

원칙:

```text
Core owns migration
Agents never migrate DB
```

Migration이 필요한 경우 Core는 정상 request를 받기 전에 migration을 완료해야 한다.

Migration 실패 시:

```text
health = not_ready
```

로 두고 agent에게 정상적인 memory operation을 제공하지 않는다.

---

# 23. 대안 검토 결과

## A. 각 agent가 SQLite 직접 접근

```text
Agent A → SQLite
Agent B → SQLite
Agent C → SQLite
```

채택하지 않는다.

WAL과 busy timeout은 SQLite의 정상적인 lock handling에는 도움이 되지만, 애플리케이션 수준의 single ownership을 제공하지 않는다.

본 프로젝트에서는 Core-as-Writer가 더 명확하다.

## B. Hermes를 writer로 사용

Hermes가 실행 중일 때만 다른 agent가 inbox에 기록하는 방식은 채택하지 않는다.

Hermes가 없는 환경에서 다시 여러 writer 문제가 발생하기 때문이다.

## C. Agent별 DB + 병합

채택하지 않는다.

통합 memory의 즉시성이 사라지고 merge/deduplication/deletion ordering 등의 복잡성이 증가한다.

## D. 파일 append-only log + 별도 indexer

현재 기본 구조로는 채택하지 않는다.

향후 write durability 또는 event sourcing 요구가 커질 경우 검토한다.

## E. 외부 DB 서버

현재 환경에서는 채택하지 않는다.

Windows 11, 16GB RAM, Docker 비선호라는 제약에서 PostgreSQL 등의 별도 서버를 추가하는 것은 현재 문제에 비해 운영 복잡성이 증가한다.

---

# 24. 보안

Core는 기본적으로 다음에만 bind한다.

```text
127.0.0.1
```

외부 네트워크 interface에 bind하지 않는다.

v1에서는 복잡한 authentication system을 도입하지 않는다.

필요할 경우 이후 random local bearer token을 도입할 수 있다.

관리 API는 최소화한다.

특히 외부에서 arbitrary SQL을 실행할 수 있는 endpoint는 제공하지 않는다.

---

# 25. 성능 및 확장성

Agent 수 자체보다 다음 요소가 실제 병목이 될 가능성이 높다.

```text
JEV concurrency
JEV rate limit
embedding computation
vector/FTS search
memory write frequency
RAM
```

10개 이상의 agent가 연결되는 것은 Core architecture 자체에는 문제가 되지 않는다.

예상 구조:

```text
10 agents
   ↓
one RPC server
   ↓
concurrent requests
   ↓
bounded JEV concurrency
   ↓
serialized DB writes
```

초당 요청량이 증가할 경우 먼저 조정할 대상은 다음이다.

```text
JEV concurrency
read worker count
write queue throughput
embedding batching
```

SQLite 자체가 병목이 되기 시작하거나 write volume이 크게 증가하는 경우에만 별도의 DB engine/server 전환을 검토한다.

---

# 26. 관측성

Core는 최소한 다음 metrics를 내부적으로 측정할 수 있어야 한다.

```text
request_count
request_latency
prefetch_latency
sync_turn_latency
JEV_latency
JEV_error_count
write_queue_depth
duplicate_request_count
core_uptime
```

초기에는 별도의 metrics server를 사용하지 않고 log 또는 `/health`/diagnostic endpoint 수준으로 구현할 수 있다.

---

# 27. API compatibility

Agent adapter는 Core의 내부 구현을 알지 못한다.

예를 들어 pi adapter가 다음을 알아서는 안 된다.

```text
BeamMemory
SQLite
FTS5
fastembed
JEV pipeline internals
```

pi는 다음 정도만 알아야 한다.

```text
POST /prefetch
POST /sync_turn
```

이 원칙을 유지하면 Mnemosyne backend가 변경되어도 agent adapter를 수정할 필요가 없다.

---

# 28. 구현 순서

구현은 다음 순서를 권장한다.

### Phase 1 — Core extraction

기존 코드에서 다음을 Core가 직접 import할 수 있도록 정리한다.

```text
gateway/*
core/j1_engine.py
backends/mnemosyne.py
```

이 단계에서는 알고리즘을 변경하지 않는다.

### Phase 2 — RPC server

다음 API만 구현한다.

```text
GET /health
GET /version
POST /prefetch
POST /sync_turn
```

### Phase 3 — Write queue

`sync_turn` DB mutation을 serialized write queue로 이동한다.

### Phase 4 — Idempotency

`request_id` 기반 duplicate detection을 추가한다.

### Phase 5 — Hermes adapter

기존 Hermes adapter의 DB 접근을 Core RPC 호출로 변경한다.

### Phase 6 — pi adapter

TypeScript ExtensionAPI에서 Core client를 구현한다.

### Phase 7 — Codex/opencode

각 환경의 hook/plugin에서 동일한 protocol을 사용한다.

### Phase 8 — failure testing

다음 시나리오를 자동 테스트한다.

```text
Core unavailable
Core restart
RPC timeout
RPC retry
duplicate request
JEV timeout
JEV 5xx
simultaneous prefetch
simultaneous sync_turn
prefetch + sync_turn concurrent
agent crash during request
Core crash during write
DB migration failure
```

---

# 29. Acceptance Criteria

v2 구현이 완료되었다고 판단하기 위한 최소 조건은 다음과 같다.

| 항목                       | 조건                                           |
| ------------------------ | -------------------------------------------- |
| DB ownership             | Core만 정상 DB 접근                               |
| concurrent agents        | Hermes + pi + Codex 동시 실행 가능                 |
| concurrent reads         | 여러 prefetch 요청 처리 가능                         |
| serialized writes        | write queue로 DB mutation 직렬화                 |
| duplicate protection     | 동일 request_id 재전송 시 중복 저장 없음                 |
| crash safety             | transaction 중간 crash에서 partial write 없음      |
| core failure             | agent가 DB 직접 접근하지 않음                         |
| Hermes compatibility     | 기존 `## Mnemosyne Context` 계약 유지              |
| JEV failure              | 기존 fallback/retry 정책 유지                      |
| memory model             | 모든 agent가 동일 DB 공유                           |
| provenance               | agent/session/source metadata 보존             |
| embedding                | fastembed 중복 로드 없음                           |
| Docker                   | 필요 없음                                        |
| Hermes core modification | 없음                                           |
| rollback                 | embedded compatibility mode로 명시적 rollback 가능 |

---

# 30. 최종 아키텍처

최종적으로 채택하는 구조는 다음과 같다.

```text
                         ┌───────────────────┐
                         │      Hermes       │
                         │      Plugin       │
                         └─────────┬─────────┘
                                   │
                         ┌─────────▼─────────┐
                         │        pi         │
                         │    Extension      │
                         └─────────┬─────────┘
                                   │
                         ┌─────────▼─────────┐
                         │      Codex        │
                         │      Hooks        │
                         └─────────┬─────────┘
                                   │
                         ┌─────────▼─────────┐
                         │     opencode      │
                         │      Plugin       │
                         └─────────┬─────────┘
                                   │
                         localhost HTTP/JSON
                                   │
                                   ▼
                ┌─────────────────────────────────┐
                │          jev-mem-core            │
                │                                 │
                │  RPC Request Handler            │
                │          │                      │
                │    ┌─────┴─────┐                │
                │    │           │                │
                │  Prefetch   sync_turn           │
                │    │           │                │
                │ concurrent   write queue        │
                │    │           │                │
                │    ▼           ▼                │
                │   JEV       serialized          │
                │    │          write              │
                │    └─────┬─────┘                │
                │          │                      │
                │     Mnemosyne backend           │
                │          │                      │
                │     fastembed instance           │
                └──────────┬──────────────────────┘
                           │
                           ▼
                    mnemosyne.db
```

핵심은 **Core 자체를 단일 스레드로 만드는 것이 아니라, DB ownership을 Core 하나로 제한하는 것**이다.

```text
Multiple agents
      ↓
Concurrent RPC handling
      ↓
Concurrent read / bounded JEV
      ↓
Single serialized write queue
      ↓
Single Mnemosyne DB owner
```

이 구조는 현재 Hermes에서 검증된 J1/write-gate 로직을 최대한 보존하면서 Hermes, pi, Codex, opencode가 동일한 memory layer를 사용할 수 있도록 한다.

---

# 31. 설계 원칙 요약

본 설계의 불변 원칙은 다음과 같다.

**첫째, Mnemosyne DB는 Core만 소유한다.**

**둘째, Agent adapter는 memory implementation을 알지 못하며 RPC protocol만 사용한다.**

**셋째, Core는 single-thread가 아니라 concurrent request handler를 사용한다.**

**넷째, DB mutation은 하나의 serialized write queue를 통해 수행한다.**

**다섯째, JEV 호출은 bounded concurrency로 제한한다.**

**여섯째, `request_id`를 이용해 RPC retry에 대한 idempotency를 보장한다.**

**일곱째, Core 장애 시 agent가 직접 DB에 쓰는 자동 fallback은 사용하지 않는다.**

**여덟째, provenance와 search scope를 분리한다.**

**아홉째, Hermes 코어는 수정하지 않고 adapter/plugin 경계에서 통합한다.**

**열째, fastembed와 Mnemosyne runtime은 Core에서 한 번만 로드한다.**

이 원칙을 유지하는 한 agent 수가 증가하거나 Hermes 이외의 새로운 agent가 추가되어도 각 agent adapter만 추가하면 동일한 memory infrastructure를 재사용할 수 있다.
