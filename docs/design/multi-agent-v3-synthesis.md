# 멀티 에이전트 전환 — 3개 AI 검토 종합 및 구현 방향 (v3)

> 상태: **종합 완료 — 승인 대기** · 2026-09-29
> 입력: A-ai(구조 검토) / B-ai(구현 명세) / C-ai(설계 v2) 3개 외부 검토

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
| core 다운 시 보존 | soft-fail + lazy-spawn | **스풀 JSONL + replay ** | degraded, outbox=미래 | **B 채택** (데이터 손실 0. 사용자 요구에 부합) |
| 보안 | 미언급 | 토큰+Origin/Host 차단 | v1 인증 없음 | **B 채택** (로컬이어도 CSRF/DNS rebinding 방어) |
| API 명세 | 없음 | /v1/* 전면 명세 | /prefetch, /sync_turn 단순 | **B 채택** (멱등성·ledger·스풀 포함) |
| 테스트 계획 | 엣지케이스 5종 | golden/동시성/카오스 전면 | 시나리오 목록 | **B 기반 + A 엣지케이스 흡수** |
| Jev 장애 | circuit breaker | breaker+pending_gate+RRF degraded | retry 한정 | **B 채택** |
| Hermes 전환 | (미언급) | **마지막(D9) + 플래그** | 호환 모드(플래그) | **B 채택** (Hermes 마지막 = 회귀 위험 최소) |

**B의 유일한 보류점**: §12 Q1~Q5 — `BeamMemory.remember()` 메타데이터 지원 여부 등 **코드 검증 필요** 항목 (P0에서 확인).

---

## 3. 최종 구현 방향 (종합)

### 3.1 아키텍처 (B 그림 + C 원칙)

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

### 3.2 핵심 결정 (D-list, B 기준)

| # | 결정 | 상태 |
|---|---|---|
| D1 | core가 유일 writer + fastembed 유일 로드 | 확정 |
| D2 | HTTP JSON (127.0.0.1, 포트 47821) | 확정 |
| D3 | 직렬화 = DB commit만 (asyncio + SingleWriter 큐 + ReaderPool) | 확정 |
| D4 | 듀얼 모드 금지. 어댑터는 자동기동 + 실패 시 스풀 | 확정 |
| D5 | 모든 쓰기 멱등성 키 | 확정 |
| D6 | 스풀(JSONL) + core replay (데이터 손실 0) | 확정 |
| D7 | Jev 장애: prefetch=RRF degraded(200), gate=pending_gate 후 재판정 | 확정 |
| D8 | provenance=`source_agent` 태깅, 검색 격리 아님 (scope 옵션만) | 확정 |
| D9 | **구현 순서: core → pi → codex → opencode → Hermes(마지막, 플래그)** | 확정 |
| D10 | 보안: Bearer token + Origin/Host 검증 + 127.0.0.1만 | 확정 (B) |

### 3.3 구현 단계 (B §15 채택)

| 단계 | 내용 | 수용 기준 |
|---|---|---|
| **P0** | §12 Q1~Q5 코드 검증 (remember 메타데이터/RO 커넥션/PRAGMA/j1_engine 분리/write_gate 동기) | 답변 + 분기 결정, 결과 보고 |
| **P1** | core 서버 (HTTP/인증/health/prefetch/turns/ledger/멱등성/SingleWriter/ReaderPool) | 골든 테스트(임베디드 vs core 동일) + smoke 7/7 유지 |
| **P2** | 스풀+replay, circuit breaker, pending_gate, 자동기동, 싱글턴 | 카오스 테스트 통과 |
| **P3** | **pi 어댑터** (신규, 회귀 위험 최소) | 실제 pi 세션 prefetch/turns 동작 |
| **P4** | Codex hook → opencode | Hermes 없는 codex+pi 동시 시나리오 |
| **P5** | Hermes 전환 (`JEV_MEM_MODE=rpc`, 플래그) | 골든+동시성+롤백(embedded) 리허설 |

### 3.4 A·C의 보강 사항 (B에 추가 반영)

- **A**: prefetch 클라이언트 타임아웃 **하드 1.5~2.0s**, fastembed `asyncio.Semaphore(1~2)`, 고스트 프로세스 대응(health로 검증), Windows 파일 락 3회 재시도, WAL 주기 체크포인트
- **C**: provenance(출처) ≠ scope(검색범위) 분리 원칙, outbox는 DB writer가 아니라는 정의(스풀과 동일 개념), core는 단일 스레드가 아니라 **DB ownership 하나**가 핵심

---

## 4. 승인 요청

아래 3가지를 승인해 주시면 P0(코드 검증)부터 착수합니다:

- [ ] **B(구현 명세)를 기본 스펙으로 채택** — A·C는 참고 문서로 관리 (파일: `docs/design/` 하위에 A/B/C 원문 보관)
- [ ] **스풀 방식 채택** — core 다운 시에도 턴 손실 0 (어댑터별 50MiB 한도)
- [ ] **구현 순서 D9 승인** — core → pi → codex → opencode → Hermes(마지막)

---

## 5. 파일 배치

```
docs/design/
  multi-agent-architecture-brief.md   # 원안 브리프 (외부 검토용)
  reviews/
    A-ai-구조 검토.md                  # A 원문
    B-ai-implementation-spec.md       # B 원문 (기본 스펙)
    C-ai-설계-v2.md                    # C 원문
  multi-agent-v3-synthesis.md         # 본 문서 (종합)
```