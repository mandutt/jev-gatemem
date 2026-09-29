# 멀티 에이전트 전환 — 스펙 v1.0 (승인 반영) · 2026-09-29

> 상태: **✅ 승인 완료 (조건부 3건 반영)** — 스펙 v1.0 확정. **P0 코드 검증 후 스펙 v1.1 확정** (게이트).
> 입력: A-ai(구조 검토) / B-ai(구현 명세) / C-ai(설계 v2) 3개 외부 검토 + 사용자 조건부 승인 (2026-09-29)
> 기본 스펙: `reviews/B-ai-jev-mem-core-implementation-spec.md` (원문 불변, 본 문서가 승인 반영 델타의 SoT)

---

## 1. 3개 검토 공통 합의 (전원 100% 동의 항목)

| # | 합의 | 근거 |
|---|---|---|
| 1 | **Core-as-Writer 채택** | RAM(fastembed 중복 로드 차단) + 로직 단일화 + 무결성. 대안 3종(A: WAL 직렬화, B: 파일 인박스, C: DB 분리) 전부 기각. **기각의 진짜 근거는 락 경합이 아니라 "fastembed 중복 로드 + 로직 중복"** (브리프의 "SQLite 동시쓰기 불가" 프레임은 정정) |
| 2 | **로컬 HTTP (127.0.0.1)** | TCP JSON-RPC는 프레이밍·재연결을 클라이언트마다 구현해야 함. Codex hook(단발 curl), TS(fetch), python(urllib) 모두 즉시 연동. 오버헤드 0.5ms << JEV 275ms |
| 3 | **단일 스레드 금지** | 단일 스레드 전체 직렬화는 JEV 호출(275ms~수초) 동안 모든 에이전트 blocking(head-of-line). **직렬화 범위 = DB commit 순간만**, 나머지(I/O·JEV·임베딩)는 병렬 |
| 4 | **자동 embedded fallback 금지** | core 다운 시 Hermes가 직접 DB 쓰기 = 복수 writer 회귀(split-brain). 명시적 `JEV_MEM_MODE=embedded`(롤백용)만 허용 |
| 5 | **멱등성 키 필수** | retry-safe: 같은 key+같은 payload → dedup, 같은 key+다른 payload → 409 |

---

## 2. 차이점 및 종합 판단

| 항목 | A | B | C | **종합 결정** |
|---|---|---|---|---|
| core 다운 시 보존 | soft-fail + lazy-spawn | **스풀 JSONL + replay** | degraded, outbox=미래 | **B 채택** — 단 "손실 0"은 **"판정 전 턴 best-effort 보존"**으로 정정 (§5 손실 경로표) |
| 보안 | 미언급 | 토큰+Origin/Host 차단 | v1 인증 없음 | **B 채택** (로컬이어도 CSRF/DNS rebinding 방어) |
| API 명세 | 없음 | /v1/* 전면 명세 | /prefetch, /sync_turn 단순 | **B 채택** (멱등성·ledger·스풀 포함) |
| 테스트 계획 | 엣지케이스 5종 | golden/동시성/카오스 전면 | 시나리오 목록 | **B 기반 + A 엣지케이스 흡수** |
| Jev 장애 | circuit breaker | breaker+pending_gate+RRF degraded | retry 한정 | **B 채택** |
| Hermes 전환 | (미언급) | **마지막(D9) + 플래그** | 호환 모드(플래그) | **B 채택** — 단 P3~P4 과도기 조건 (§4) |

**B의 유일한 보류점**: §12 Q1~Q5 (+ Q3-1) — `BeamMemory.remember()` 메타데이터 지원 여부 등 **코드 검증 필요** 항목. P0에서 확인 후 **v1.1 확정** (아래 §6).

---

## 3. 최종 아키텍처

```
 Hermes(plugin) ─┐
 pi (TS ext)   ──┤  HTTP 127.0.0.1:{47821}/v1/*       ┌────────────────────────────┐
 Codex (hooks) ──┼───────────────────────────────────▶ │ jev-mem-core (Python 1개)   │
 opencode (TS) ──┘  (core 다운 시 스풀 JSONL)           │ asyncio 서버                │
        │                                              │ ├ prefetch (병렬, JEV 세마)  │
        └── spool/*.jsonl ── replay ─────────────────▶ │ ├ turns (게이트→SingleWriter)│
                                                       │ ├ ReaderPool (RO)           │
                                                       │ ├ SingleWriter (유일 쓰기)   │
                                                       │ └ core_state.db (ledger)    │
                                                       └──────────────┬─────────────┘
                                                                      ▼
                                                              mnemosyne.db (WAL)
```

### 3.1 핵심 결정 (D-list, v1.0)

| # | 결정 | 상태 |
|---|---|---|
| D1 | core가 유일 writer + fastembed 유일 로드 | 확정 |
| D2 | HTTP JSON (127.0.0.1, 포트 47821) | 확정 |
| D3 | 직렬화 = DB commit만 (asyncio + SingleWriter 큐 + ReaderPool) | 확정 |
| D3a | **임베딩 제한 = 스레드풀 1개로 통일** (embed pool 2~4, onnxruntime GIL 해제). B의 embed 스레드풀과 A의 asyncio.Semaphore 제안을 **스레드풀 하나**로 통합 | 확정 (사용자 조건 b) |
| D4 | 듀얼 모드 금지. 어댑터는 자동기동 + 실패 시 스풀 | 확정 |
| D5 | **멱등성 키는 어댑터가 항상 생성**: `turn_seq` 있으면 `{agent}:{session}:{turn_seq}`, 없으면 **UUID**. 서버는 키 없으면 400 (서버 파생 없음) | 확정 (사용자 조건 a) |
| D6 | 스풀(JSONL) + core replay — **"판정 전 턴 best-effort 보존"** (§5 손실 경로 명시) | 확정 (사용자 조건) |
| D7 | Jev 장애: prefetch=RRF degraded(200), gate=pending_gate 후 재판정 | 확정 |
| D7a | **prefetch 타임아웃: 기본 1.5s / 상한 2.0s** (클라이언트 하드리밋, 초과 시 빈 블록) | 확정 (사용자 조건 c) |
| D8 | provenance=`source_agent` 태깅, 검색 격리 아님 (scope 옵션만) | 확정 |
| D9 | **구현 순서: core → pi → codex → opencode → Hermes(마지막, 플래그)** — P3~P4 과도기 조건 §4 | 확정 (조건부) |
| D10 | 보안: Bearer token + Origin/Host 검증 + 127.0.0.1만 | 확정 (B) |
| D11 | **파일 락 재시도(2s×3)는 스풀·백업 경로에만 적용** — writer 경로에는 적용하지 않음 (busy_timeout만) | 확정 (사용자 조건 d) |

---

## 4. P3~P4 과도기 (Hermes 임베디드 + core 공동 쓰기)

D9 승인 조건으로 아래를 문서화한다.

| 항목 | 내용 |
|---|---|
| **과도기 정의** | P3(pi 어댑터) 착수 ~ P5(Hermes rpc 전환) 완료 사이. 이 기간 **Hermes 프로세스(임베디드)와 jev-mem-core가 같은 mnemosyne.db에 둘 다 쓰는 복수 writer 상태** |
| **과도기 제약 1** | **core는 mnemosyne.db 스키마 변경 금지** (기존 테이블/인덱스 DDL 불가). Hermes 임베디드 BeamMemory와의 공존 보장이 최우선. core_state.db(ledger)는 core 전용이므로 자유 |
| **과도기 제약 2** | **P0에서 Q3-1(PRAGMA 충돌) 확인 필수** — BeamMemory 초기화 PRAGMA(WAL/busy_timeout/synchronous)와 core 설정이 충돌하지 않도록 core 쪽에서 조정 (B §13 기준, 임베디드는 불변) |
| **과도기 제약 3** | **P3 착수 전 mnemosyne.db 백업 필수** (`VACUUM INTO`, backups/ 보관) |
| **과도기 종료 목표일** | **2026-10-13 (P5 완료, Hermes `JEV_MEM_MODE=rpc` 전환 + 롤백 리허설 통과)** — 목표일 초과 시 상태 보고 후 지연 사유·새 목표일 승인 |
| **과도기 모니터링** | core 지표에서 `turns` 정상 처리 + Hermes 독립 기록 지속 확인 (이중 쓰기 충돌 없음). `SQLITE_BUSY`/lock 오류 발생 시 **즉시 P3 정지 후 보고** |

> 참고: P3~P4 기간의 복수 writer는 어디까지나 **과도기적 허용**이며, D1(단일 writer)의 최종 목표는 P5에서 달성된다. 과도기 동안 core 스키마 변경 금지로 충돌 표면을 최소화한다.

---

## 5. 스풀 정책 (v1.0 정정)

### 5.1 보존 보장 표현

- ~~"데이터 손실 0"~~ → **"판정 전 턴 best-effort 보존"** — 스풀은 core 부재 시 턴을 보존하려는 최선의 노력이며, 아래 손실 경로가 존재한다.

### 5.2 손실 가능 경로와 처리 정책

| # | 손실 경로 | 조건 | 처리 정책 |
|---|---|---|---|
| L1 | **용량 초과** | 에이전트별 스풀 50 MiB 초과 | 가장 오래된 파일부터 삭제 + 경고 로그. 삭제된 턴은 **판정 전 유실**로 기록 (스풀은 어댑터 로컬이므로 ledger 기록 없음). 재시도 시 새 파일로 계속 적재 |
| L2 | **pending_gate 만료** | Jev 장애로 `pending_gate` 보관 후 24h 경과 | `failed(reason=expired)` 처리 + 원문 삭제. **게이트 판정 없이 유실** — 재판정 불가분을 명시적으로 기록 |
| L3 | **단발 프로세스 종료** | hook(Codex 등)이 스풀 기록 전에 비정상 종료 (kill, 크래시) | **hook은 ack 수신 또는 스풀 기록 완료를 확인한 뒤에만 종료** (동기 대기). 그래도 프로세스가 죽으면 해당 턴은 유실 — 구조적 한계로 문서화 |
| L4 | **디스크 오류** | 스풀 파일 write 실패 (디스크 가득 참, 권한) | 스풀 실패를 에러 로그 + stderr로 명시. 재시도 1회 후 포기 (무한 루프 금지). D11의 파일 락 재시도(2s×3) 적용 |

### 5.3 원문 평문 보관 — ACL·redaction 방침 (P2 보고 항목)

- 스풀/ledger에는 **대화 원문 평문**이 기록된다 (보존 목적상 불가피).
- **P2에서 다음 방침 확정 여부를 보고한다** (구현 전 승인):
  - **ACL**: `%LOCALAPPDATA%\jev-mem\` 디렉터리에 현재 사용자만 접근 (Windows ACL, `icacls`). token 파일은 기존 B 스펙대로 32B 랜덤 + 사용자 읽기 전용.
  - **redaction 후보**: ① 스풀 원문에 민감 패턴(주소·전화·카드번호 등) redaction 적용 여부 ② ledger `payload_json`은 처리 종료 시 NULL 처리 (B 스펙 유지) ③ 로그에 원문 미기록 (B 스펙 유지)
  - **기본값 제안**: ACL 적용 + ledger 원문 삭제 유지 + 스풀 redaction은 **적용 안 함** (redaction 부작용으로 게이트 판정 텍스트가 훼손될 위험 > 민감정보 노출 위험 — 로컬 단일 사용자 + ACL로 통제). P2에서 재보고.

---

## 6. 구현 단계 (v1.0 + v1.1 게이트)

| 단계 | 내용 | 수용 기준 |
|---|---|---|
| **P0** | §12 Q1~Q5 **+ Q3-1(PRAGMA)** 코드 검증 (remember 메타데이터 / RO 커넥션 / PRAGMA / j1_engine 분리 / write_gate 동기) | 답변 + 분기 결정, 결과 보고 → **스펙 v1.1 확정 (게이트)** — 검증 결과 반영해 본 문서를 v1.1로 개정 후 P1 착수 |
| **P1** | core 서버 (HTTP/인증/health/prefetch/turns/ledger/멱등성/SingleWriter/ReaderPool) | 골든 테스트(임베디드 vs core 동일) + smoke 7/7 유지 |
| **P2** | 스풀+replay, circuit breaker, pending_gate, 자동기동, 싱글턴 **+ ACL·redaction 방침 확정 보고 (§5.3)** | 카오스 테스트 통과 + 방침 승인 |
| **P3** | **pi 어댑터** — **착수 전 mnemosyne.db 백업 필수 (§4)** | 실제 pi 세션 prefetch/turns 동작. 과도기 시작 |
| **P4** | Codex hook → opencode | Hermes 없는 codex+pi 동시 시나리오. hook은 ack/스풀 기록 후 종료 (L3) |
| **P5** | Hermes 전환 (`JEV_MEM_MODE=rpc`, 플래그) — **과도기 종료 목표 2026-10-13** | 골든+동시성+롤백(embedded) 리허설 → 단일 writer 복귀 |

### A·C의 보강 사항 (B에 추가 반영)

- **A**: prefetch 타임아웃 하드 1.5~2.0s (D7a), fastembed 스레드풀 통일 (D3a), 고스트 프로세스 대응(health로 검증), 파일 락 재시도는 스풀·백업 한정 (D11), WAL 주기 체크포인트
- **C**: provenance(출처) ≠ scope(검색범위) 분리 원칙, outbox는 DB writer가 아니라는 정의(스풀과 동일 개념), core는 단일 스레드가 아니라 **DB ownership 하나**가 핵심

---

## 7. 승인 기록 (2026-09-29)

| # | 승인 항목 | 결과 | 조건 |
|---|---|---|---|
| 1 | B(구현 명세) 기본 스펙 채택 | ✅ 조건부 | (a) 멱등성 키 어댑터 항상 생성 (turn_seq 없으면 UUID) — D5 (b) 임베딩 제한 스레드풀 1개 통일 — D3a (c) prefetch 타임아웃 기본 1.5s/상한 2.0s — D7a (d) 파일 락 재시도는 스풀·백업에만 — D11 (e) **P0 종료 시 스펙 v1.1 확정 단계 추가** — §6 |
| 2 | 스풀 채택 | ✅ 조건부 | "손실 0" → **"판정 전 턴 best-effort 보존"** + 손실 경로 4종 표 (§5.2) + hook ack/스풀 기록 후 종료 (L3) + 원문 ACL·redaction 방침 P2 보고 (§5.3) |
| 3 | D9 구현 순서 | ✅ 조건부 | 과도기 문서화 + core 스키마 변경 금지 + Q3-1 P0 확인 + P3 전 백업 + 종료 목표일 2026-10-13 (§4) |

---

## 8. 파일 배치

```
docs/design/
  multi-agent-architecture-brief.md   # 원안 브리프 (외부 검토용)
  reviews/
    A-ai-구조 검토.md                  # A 원문 (참고, 재작성 금지)
    B-ai-implementation-spec.md       # B 원문 = 기본 스펙 (참고, 재작성 금지)
    C-ai-설계-v2.md                    # C 원문 (참고, 재작성 금지)
  multi-agent-v3-synthesis.md         # 본 문서 = 스펙 v1.0 (SoT, 승인 반영)
```