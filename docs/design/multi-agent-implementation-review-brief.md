# JEV Memory Middleware — Core-as-Writer 전환: 설계 대비 구현 상태 검토 요청서

작성: 2026-09-29 · 대상 독자: **본 문서만으로 검토를 수행하는 외부 AI 검토자** (저장소 접근 불가 가정)
검토 요청자: 프로젝트 오너 (구현은 Hermes Agent가 수행)

---

## 0. 검토자에게 부탁하는 것

이 문서는 ①당초 설계(B 스펙 v1.1)의 핵심 내용과 ②현 구현 상태를 한 곳에 모은 것입니다.
별도 자료 없이 아래를 검토해 주세요:

1. **편차 판정**: §4의 설계-구현 차이 5건이 각각 수용 가능한 편차인지, 설계 의도를 훼손하는지 판정
2. **누락 위험**: 설계에 있으나 구현에서 빠졌거나, 문서화되지 않은 잠재 결함
3. **운영 리스크**: §3의 검증 결과가 실제 장기 운영에서 깨질 수 있는 시나리오
4. **우선순위 제안**: 잔여 과제 중 무엇을 먼저 해야 하는지

출력 형식: 항목별 판정(수용 가능 / 조건부 수용 — 조건 명시 / 수정 필요) + 근거.

---

## 1. 프로젝트 개요

### 1.1 배경

- 사용자는 여러 코딩/일반 AI 에이전트(Hermes, pi, Codex CLI, OpenCode)를 한 Windows PC에서 사용하며,
  각 에이전트의 장기 기억을 **Mnemosyne**(SQLite + sqlite-vec + fastembed 기반 로컬 메모리 시스템,
  `%LOCALAPPDATA%\hermes\mnemosyne\data\mnemosyne.db`)에 저장합니다.
- 기존에는 각 에이전트 프로세스가 Mnemosyne을 in-process로 직접 구동 → 멀티 에이전트 동시 사용 시
  SQLite 멀티 writer 충돌, fastembed 모델 중복 로드(RAM 압박, 시스템 RAM 15.6GB), 게이트 로직 중복 구현 문제.
- 해법으로 **Core-as-Writer 중앙 데몬(`jev-mem-core`)** 채택: 데몬 1개가 DB의 유일 writer이자 fastembed의
  유일 로더이며, 어댑터들은 로컬 HTTP로 접근.
- 3개 외부 AI 검토(A/B/C)를 종합해 스펙 v1.0 → P0 코드 검증 → **스펙 v1.1 확정** 후
  P1(코어 서버)→P2(운영 기능)→P3(pi)→P4(Codex/OpenCode)→P5(Hermes) 순으로 구현 완료.

### 1.2 시스템 구성 (현 상태)

```
[Hermes 데스크톱]  [pi CLI]  [Codex CLI]  [OpenCode]      ← 어댑터 (writer 아님)
     │ JevRpcProvider   │ JevMemClient(TS) │ hooks │ v2 plugin
     └────────────┬─────┴──────────────────┘
                  │ HTTP 127.0.0.1:47821 (Bearer token, Origin/Host 검증)
        [jev-mem-core 데몬]  ← 유일 writer + fastembed 유일 로드
                  │ (SingleWriter 스레드 + ReaderPool RO 커넥션)
        %LOCALAPPDATA%\hermes\mnemosyne\data\mnemosyne.db  (Hermes 실 DB, ~969행)
        %LOCALAPPDATA%\jev-mem\  (ledger/spool/token/logs — 데몬 운영 상태)
```

- 어댑터는 데몬이 없으면 **on-demand 기동**(probe → 없으면 detached spawn → readiness 폴링).
  부팅 시 상주·작업 스케줄러 등록은 **의도적으로 안 함** (오너 확정: 에이전트가 없으면 core가 떠 있을 필요 없음).
- 롤백: Hermes는 `JEV_MEM_MODE=embedded`로 in-process provider 복귀 (자동 fallback 금지 — split-brain 방지).

### 1.3 기술 스택

- Python 3.14 (Hermes venv) / aiohttp 서버 / stdlib-only 클라이언트(urllib)
- SQLite WAL + busy_timeout 5000ms + foreign_keys ON (BeamMemory와 동일 PRAGMA)
- fastembed (BAAI/bge-small-en-v1.5) + sqlite-vec, JEV 분류 게이트는 외부 LLM API (TypeSafe SystemOne, 동기 httpx)

---

## 2. 당초 설계 (B 스펙 v1.1) 핵심 요약

> 원문: `docs/design/reviews/B-ai-jev-mem-core-implementation-spec.md` (이 검토에서는 요약만 제공)

### 2.1 불변 제약 [확정]

1. core 1개가 mnemosyne.db의 **유일 writer** + fastembed **유일 로더**
2. transport = 로컬 HTTP 127.0.0.1:47821 (raw TCP 금지)
3. 직렬화 범위 = DB commit 순간만 (JEV LLM 호출 ~275ms는 단일 스레드 직렬화 금지 — head-of-line blocking 방지)
4. **자동 embedded fallback 금지** (split-brain 방지) — 명시적 `JEV_MEM_MODE=embedded`만 롤백
5. 멱등성 키는 **어댑터가 항상 생성** (서버는 키 없으면 400)
6. core 다운 시 어댑터 스풀(JSONL) + core replay = "판정 전 턴 best-effort 보존"
7. JEV 장애: prefetch = RRF degraded(200), write gate = pending_gate 재판정 (일시적 오류만; 401/파싱 실패는 fail-open KEEP)
8. `source_agent` 태깅 = provenance 목적, 검색 격리 아님 (scope 옵션만)
9. 구현 순서 D9: core → pi → codex → opencode → **Hermes 마지막(플래그 뒤)**
10. 보안: Bearer token + Origin/Host 검증 + 127.0.0.1 bind만
11. 파일 락 재시도(2s×3)는 스풀·백업 경로에만 (writer는 busy_timeout만)

### 2.2 P0에서 확정된 분기 (코드 실측 기반, D12~D15)

| 결정 | 내용 |
|---|---|
| D12 | 크래시 윈도우 = remember() metadata에 `idem_key` 저장, 재큐잉 전 LIKE 조회로 중복 방지 (1안) |
| D13 | ReaderPool = read-only 커넥션 (`mode=ro`, thread-local, sqlite-vec RO 로드 확인) |
| D14 | 임베딩은 writer 스레드에서 통째 실행 (remember()가 임베딩+INSERT 한 덩어리) — `slow_job_warn_ms` 500ms |
| D15 | core PRAGMA = BeamMemory와 동일 (WAL + busy_timeout 5000 + FK ON) |

### 2.3 설계 주요 절차

- **기동(§4.3)**: 어댑터가 연결 거부 시 auto_start=true면 `pythonw -m jev_mem_core --serve` detached 실행
  (CREATE_NO_WINDOW | DETACHED_PROCESS), health 최대 폴링, **spawn 쿨다운 30초**, 싱글턴(§4.1)으로
  동시 spawn 무해. **상시 실행은 작업 스케줄러에도 등록** (자동 기동은 안전장치).
- **종료(§4.4)**: shutdown 요청 → 새 요청 거부 → 진행 요청 완료(≤10s) → writer drain → wal_checkpoint(TRUNCATE) → core.json 삭제
- **API(§5)**: health(무인증, Origin 있으면 거부) / prefetch / turns / turns{id} / spool/flush / status / metrics / admin/shutdown.
  prefetch 옵션: `scope: all|agent`, `max_chars`, `timeout_ms`(기본 1500, 상한 10000), `rerank`
- **동시성(§16.2 게이트)**: 8 클라이언트 × 200턴, 10% 중복 → 고유 키 = ledger 행 수, 중복 저장 0, BUSY 노출 0, prefetch p95 < 800ms
- **골든(§16.1)**: 대표 20개 이상 쿼리로 임베디드 vs core `/v1/prefetch` 출력 비교
- **회귀(§16.4)**: smoke 7/7 유지 + 게이트 품질 지표(gold50 P 0.744 / R 0.935 / F1 0.829) 저하 없음 확인

---

## 3. 현 구현 상태 (2026-09-29, 전 단계 완료)

### 3.1 구현·검증 이력

| 단계 | 산출 | 검증 결과 |
|---|---|---|
| P1 core 서버 | `jev_mem_core/` (app, server, pipeline, writer, store, ledger, config) | 골든 3/3, 라이브 게이트 PASS |
| P2 운영 | spool(JSONL cap 50MiB, replay, corrupt 격리), ops(WAL 체크포인트, VACUUM INTO 일 1회 keep 7), client(auto-start), pending_gate 루프(60s×≤20, 24h 만료), ACL(icacls user-only), redaction(기본 OFF, 스풀·ledger만) | 카오스 **7/7**, redact **19/19** |
| P3 pi | `adapters/pi/pi-jev-mem.ts` (ExtensionAPI, before_agent_start prefetch 주입 + turn_end 저장) | Hermes+pi 동시 10턴 → SQLITE_BUSY 0 |
| P4 codex/opencode | codex hooks(recall/record, trusted_hash 갱신), opencode v2 plugin(aisdk.language 래퍼), MCP bridge | 실측: 모델 인용·DB 저장·tools/call |
| P5 Hermes | `JevRpcProvider`(rpc 기본/embedded 롤백), `/v1/tools` 프록시(writer 스레드 직렬화), core DB → Hermes 실 DB | §16.2 **7/7**: 1760 요청, 0 BUSY, 0 중복, p95 508ms |

P5 커밋 이력: `d2f6a05`(본체) → `6f91d8b`(보고서) → `2c1845e`(auto-start 수정) → `d4df938`(NO_WINDOW) → `46e24cc`(pythonw) → `981cdf3`(문서).

### 3.2 P5 라이브 실측 (데스크톱 재시작 후 실세션)

- agent.log: `mode=rpc` → `Memory provider 'jev-mem' activated` ✓
- 실제 턴: `POST /v1/prefetch 200`, sync_turn → 실 DB에 `hermes_<session_id>` 세션 2행 (967→969)
- `mnemosyne_stats` 툴 호출 → core log `POST /v1/tools 200` (툴 프록시 라이브 실증)
- 세션 접두사 규칙(`hermes_<sid>`) 유지 — writer 스레드가 `beam.session_id`를 요청별로 재바인딩

### 3.3 P5 과정에서 발견·수정한 결함 (모두 실측 기반)

1. **store 시그니처**: writer 스레드 경유 호출이 키워드 전용 파라미터에 위치 인자 전달 → TypeError. 수정 완료.
2. **플러그인 silent 다운그레이드**: Hermes 로더가 register() 실패 시 fallback으로 `dir()` 알파벳 순
   MemoryProvider 서브클래스를 인스턴스화 — `JevRerankProvider`(embedded)가 조용히 선택됨.
   → 플러그인은 `JevRpcProvider`만 노출하도록 수정.
3. **auto-start 2중 결함**: ① spawn이 `sys.executable`로 실행해 middleware repo가 없는 인터프리터에서
   "No module named jev_mem_core" 실패 → PYTHONPATH 주입 ② config가 `JEV_MEM_DATA_DIR` env에서
   DB 경로를 추론해 `jev-mem/mnemosyne.db`로 자동 다운그레이드 → data_dir와 DB 독립 분리.
4. **콘솔 창 깜빡임**: DETACHED_PROCESS → CREATE_NO_WINDOW로도 재발 → **pythonw.exe spawn**으로
   구조적 차단 (검증: 데몬 프로세스가 pythonw로 기동, 실 DB, breaker closed).

---

## 4. 설계 대비 편차 (검토 대상)

| # | 설계(v1.1) | 현 구현 | 구현 사유 |
|---|---|---|---|
| Δ1 | **상시 실행 병행**: 작업 스케줄러 로그온 시작 등록 + 자동 기동은 안전장치. spawn 쿨다운 30초 | **on-demand 전용**: 작업 스케줄러 미등록, 쿨다운 없음(싱글턴이 폭주 방지), health 폴링 20초 | 오너 확정 — "에이전트가 없으면 core가 떠 있을 필요 없음". 쿨다운은 싱글턴+짧은 폴링으로 대체 가능하다고 판단 |
| Δ2 | prefetch `options.scope: all\|agent` | **미구현** (옵션 파싱 없음) | D8(source_agent=provenance, 격리 아님)과 실질 중복 — 스코프 격리 수요 미확인 |
| Δ3 | **§16.1 골든**: 20개+ 쿼리 임베디드 vs core 출력 비교 | **미실행** — P1 골든 3/3 + P5 prefetch 결정론(동일 쿼리 2회 비교)으로 대체 | 로직 무수정 원칙으로 출력 동일 가정 |
| Δ4 | §16.4 게이트 품질 재측정 (gold50 저하 없음 확인) | **미실행** | 동일 원칙 — 게이트 로직은 무수정, smoke만 유지 |
| Δ5 | health 응답에 `degraded` 상태 포함 | `degraded` 미구현 (ready/shutting_down만) | JEV circuit open 시에도 ready 반환 — status의 `jev.circuit` 필드로 대체 관측 |

### 잔여 과제 (미해결)

- `/v1/tools` 실행 시 provider 세션이 고정값 `hermes_core-tools` — read 계열은 무해하나
  **remember류 툴 호출 시 어떤 세션 스코프로 저장되는지 미확인**
- prefetch 타임아웃 스킵: 데몬 죽은 시간대에 시작한 세션은 이후 턴도 스킵(새 세션에서 복구) — 구조상 허용

---

## 5. 검토 포인트 (오너가 특히 의견을 듣고 싶은 것)

1. **Δ1 (on-demand 전용)**: 쿨다운 부재 시 어댑터 4개 동시 기동 상황에서 spawn 경합은 싱글턴으로
   정리되지만, 실패한 spawn들이 반복 재시도하는 폭주 가능성이 남나? 운영상 문제될 수준인가?
2. **Δ3/Δ4 (골든·품질 미실행)**: 로직 무수정이라는 전제가 맞다면 수용 가능한가? 아니면 P5 수용 조건으로
   강제해야 하는가? (임베디드 provider는 코드상 유지 중이므로 비교 실행은 가능)
3. **`/v1/tools` remember류 스코프**: 현재 구조(Hermes MnemosyneMemoryProvider를 core 프로세스에서
   그대로 실행)에서 remember 툴 호출의 session 스코프는 어떻게 결정되는지 — 세션 누수/오배정 위험 평가.
4. **장기 운영**: 24/7 켜두는 PC가 아닌 환경(수시 재부팅)에서 on-demand 기동 + 데스크톱 종료 시 데몬 잔존
   패턴이 만드는 문제(예: 잔존 데몬이 옛 DB 핸들 보유, 재부팅 전 미 flush 스풀) 리스크 평가.
5. 기타: 문서에서 발견되는 설계-구현 불일치, 누락된 고장 모드.

---

## 6. 부록 — 주요 파일·경로 (참고용)

- 코드: `jev_mem_core/` (app/server/pipeline/writer/store/ledger/spool/ops/client/redact/tools), `harnesses/hermes_j1.py`, `harnesses/jev_mem_plugin/__init__.py`
- 어댑터: `adapters/pi/`, `adapters/codex/`, `adapters/opencode/`
- 검증: `experiments/verify_p1_core.py`, `verify_p2_chaos.py`, `verify_redact.py`, `verify_p5_concurrency.py`, `verify_p5_rpc.py`
- 데이터: 실 DB `%LOCALAPPDATA%\hermes\mnemosyne\data\mnemosyne.db` / 운영 상태 `%LOCALAPPDATA%\jev-mem\`
- 설계 문서: `docs/design/multi-agent-v1_1-p0-spec.md`(v1.1 SoT), `docs/design/reviews/B-ai-jev-mem-core-implementation-spec.md`(B 스펙 원문), 단계별 보고서 `p1-core-server-report.md` ~ `p5-hermes-rpc-report.md`
- GitHub: `mandutt/jev-gatemem` (main)
