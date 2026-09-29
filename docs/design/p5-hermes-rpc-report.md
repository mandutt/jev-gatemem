# P5 — Hermes Core-as-Writer RPC 전환 보고 (v1.1 §16)

작성: 2026-09-29 · 검증 커밋: `d2f6a05`

## 1. 목표

Hermes를 embedded(JevRerankProvider, in-process beam)에서 **RPC 모드(JevRpcProvider)** 로 전환해,
prefetch / sync_turn / mnemosyne_* 툴 실행 전부를 jev-mem-core 데몬(단일 writer) 경유로 통일한다.
split-brain(멀티 writer) 원천 차단이 목적.

## 2. 구현

| 구성요소 | 파일 | 내용 |
|---|---|---|
| 툴 프록시 (core) | `jev_mem_core/tools.py` | core 프로세스에서 Hermes `MnemosyneMemoryProvider` 직접 실행 — 로직 복제 없음, Hermes 코어 수정 없음 |
| 툴 엔드포인트 | `jev_mem_core/server.py` | `POST /v1/tools` — SingleWriter 스레드 내 직렬 실행 |
| RPC provider | `harnesses/hermes_j1.py` | `JevRpcProvider`: prefetch→`/v1/prefetch`(실패 시 빈 블록, base fallback 금지), sync_turn→`/v1/turns`(fire-and-forget), 툴→`/v1/tools`. **beam 미생성** |
| 플러그인 | `harnesses/jev_mem_plugin/__init__.py` | `JEV_MEM_MODE=rpc`(기본) / `embedded`(롤백) 분기 |
| 세션 스코프 | `jev_mem_core/store.py` | 저장 시 `beam.session_id`를 요청 `session_key`(`hermes_<sid>`)로 스코프 — B §11.2 세션 접두사 규칙 유지 |
| DB 전환 | `jev_mem_core/config.py` | 기본 DB를 Hermes 실 DB(`%LOCALAPPDATA%\hermes\mnemosyne\data\mnemosyne.db`)로 |

## 3. 발견·수정된 버그

### 3.1 store 시그니처 (P5 진행 중)
`_store_kept_impl(..., *, ...)` 키워드 전용 파라미터에 위치 인자 전달 → TypeError.
→ `*` 제거로 수정. 실 DB 저장 재검증으로 확인.

### 3.2 플러그인 silent embedded 다운그레이드 (재시작 후 실측에서 발견)
Hermes 로더 `plugins/memory/__init__.py`의 `register(ctx)` 경로는 정상이나,
collector가 내부 예외 시 fallback `_instantiate_subclass`가 **dir() 알파벳 순**으로
`JevRerankProvider`(Rerank < Rpc)를 골라 조용히 embedded로 로드됨.
→ 플러그인이 `JevRpcProvider`만 모듈 속성으로 노출하도록 수정 (embedded는
`harnesses.hermes_j1` 직접 import로만 접근 — 롤백 경로 무손상).

## 4. 검증

| 항목 | 결과 |
|---|---|
| §16.2 동시성 (`verify_p5_concurrency.py`) | 8클라이언트×200턴=1760 요청(중복 10%), 0 BUSY, 0 중복 저장, p95 508ms < 800ms — **7/7** |
| RPC 기능 (`verify_p5_rpc.py`) | prefetch 결정론, sync_turn, 툴 프록시, beam 미생성 — **8/8** + embedded 롤백 3/3 |
| 전 회귀 | smoke 7/7, P1 골든 ALL, P2 chaos 7/7, redact ALL |
| 로더 경유 로드 | `load_memory_provider('jev-mem')` → `JevRpcProvider, is_available=True` |
| **라이브 실측 (재시작 후)** | agent.log `mode=rpc` → `'jev-mem' activated`; `POST /v1/prefetch 200`; turns.stored→실 DB 2행(`hermes_20260929_230014_afe197`); `POST /v1/tools 200`(mnemosyne_stats). 행수 967→969 |

## 5. 라이브 운영 관측 → 해소 (2026-09-29 심야 후속)

- **데스크톱 재시작 시 core 데몬 동반 사망** → **해소 (on-demand 기동 확정)**: 사용자 확정 — 부팅 상주 불필요,
  첫 에이전트 요청 시 client `ensure_core()`가 probe → 없으면 기동. 수정 전 auto-start는 두 결함으로 실패:
  ① `sys.executable`(Hermes venv python)에 `jev_mem_core`가 없어 spawn 실패 ("No module named jev_mem_core") →
  `_spawn_core`가 PYTHONPATH에 middleware repo 주입 (`2c1845e`)
  ② config가 `JEV_MEM_DATA_DIR`에서 DB 경로를 추론해 `jev-mem/mnemosyne.db`로 자동 다운그레이드 →
  data_dir와 DB 분리, 기본 DB는 항상 Hermes 실 DB (같은 커밋)
- **재기동 시 콘솔 창 깜빡임** → **해소**: DETACHED_PROCESS → CREATE_NO_WINDOW(`d4df938`)로도 재발(23:20 실측) →
  최종 해법: spawn 실행 파일을 같은 venv의 **pythonw.exe**(콘솔 없는 호스트)로 교체 (`46e24cc`) —
  깜빡임 구조적 불가능. 검증: shutdown → ensure_core → pythonw 데몬, 실 DB, breaker closed.
- **prefetch 타임아웃 스킵**: 데몬 죽은 시간대 시작 세션은 이후 턴도 스킵. 새 세션에서 복구 확인. (인지됨, 구조상 허용)
- `/v1/tools` 응답 `session_id: hermes_core-tools` — 툴 실행용 임시 세션 고정값. read 중심이라 무해하나, remember류 툴 호출 시 스코프 확인 필요. (잔여)
- 검증 후 정리: `jev-mem\mnemosyne.db`의 P4 검증 테스트 행 15행 삭제 (승인 반영). 라이브 DB 무영향.

## 6. 롤백

`config.yaml` `memory.provider: mnemosyne`(기존) + `JEV_MEM_MODE=embedded` 설정 시
in-process JevRerankProvider로 복귀. DB는 동일 파일이므로 데이터 무손실.

## 7. 최종 커밋 이력 (P5 본체 + 후속)

| 커밋 | 내용 |
|---|---|
| `d2f6a05` | P5 본체: /v1/tools 프록시, store 세션 스코프, 플러그인 rpc 로드 수정 |
| `6f91d8b` | P5 보고서 + HANDOFF 전체 완료 표기 |
| `2c1845e` | client auto-start 수정 (PYTHONPATH 주입 + DB 다운그레이드 방지) |
| `d4df938` | CREATE_NO_WINDOW (불충분 — 이후 46e24cc로 대체) |
| `46e24cc` | pythonw.exe spawn — 창 깜빡임 구조적 차단 (최종) |
