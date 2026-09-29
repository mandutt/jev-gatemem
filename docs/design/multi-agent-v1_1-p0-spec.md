# 멀티 에이전트 전환 — 스펙 v1.1 (P0 코드 검증 반영) · 2026-09-29

> 상태: **✅ P0 코드 검증 완료 — 스펙 v1.1 확정** (게이트 통과). P1 착수 가능.
> 이전: v1.0 (조건부 승인 반영) — `multi-agent-v3-synthesis.md`는 v1.0, 본 문서는 v1.1 델타. **v1.1이 SoT.**

---

## 1. P0 검증 결과 (2026-09-29 실측)

| # | 질문 | 결과 | 실측 근거 / 분기 |
|---|---|---|---|
| Q1 | `remember()` 임의 metadata 저장·조회 | ✅ **가능** | `metadata` kwarg → `metadata_json` 컬럼 (`json.dumps`). `_blob: null` 무해. `LIKE '%"source_agent": "pi"%'` 조회 가능. **→ §6.4 크래시 윈도우 = 1안 채택** (`idem_key`를 metadata로 저장, 재큐잉 전 조회) |
| Q2 | remember() 임베딩+INSERT 한 덩어리? | ✅ **한 덩어리** | `remember()` 내부 `_embeddings.embed([content])` → `_store_working_embedding`. 사전 계산 벡터 파라미터 없음. 실측: remember 0.09~0.12s vs raw INSERT 0.023s → **임베딩이 remember 지연의 대부분**. **→ writer 스레드에서 임베딩 포함 통째 실행 (분리 불가)** |
| Q3 | read-only 커넥션 | ✅ **가능** | `sqlite3.connect(uri='file:...?mode=ro', check_same_thread=False)` + shim(`beam.conn` 노출) → `j1_engine.run()` 0.11s 정상, `## Mnemosyne Context` 1881자 생성. sqlite-vec RO 로드 성공. **→ ReaderPool = RO 커넥션 채택** |
| Q3-1 | PRAGMA 충돌 | ✅ **충돌 없음** | BeamMemory `_get_connection`: `journal_mode=WAL` + `busy_timeout=5000`(env `MNEMOSYNE_BUSY_TIMEOUT_MS`로 변경 가능) + `foreign_keys=ON`, `synchronous` 미설정(기본 FULL). core도 **동일 PRAGMA 사용**로 충돌 방지. **주의**: busy_timeout env는 core·임베디드 공유 — core는 자체 설정 우선 |
| Q4 | `j1_engine.run()` retrieve/rerank 분리 | ✅ **가능** | `_run` 내부에 이미 `build_lane_pool`(1단계) / `jev_rerank`(2단계)가 함수로 분리됨. 시그니처: `build_lane_pool(recall_raw, query)`, `jev_rerank(*, query, pool, client, call_jev, labels, timeout)`. `run()`은 두 단계를 잇는 래퍼로 유지 |
| Q5 | write_gate 동기 HTTP | ✅ **동기** | `httpx.Client`(동기), `AsyncClient` 미사용. 타임아웃 15s + 재시도 1회. **→ core에서 `asyncio.to_thread`로 감쌈** (B §7.1 그대로) |

---

## 2. v1.1 확정 사항 (v1.0 대비 델타)

### 2.1 D-list 추가/수정

| # | 결정 | v1.1 상태 |
|---|---|---|
| D12 | **크래시 윈도우 = 1안 (idem_key metadata 저장·조회)** — remember() metadata에 `idem_key`/`source_agent`/`session_key` 포함. 재큐잉 전 `metadata_json LIKE` 조회로 중복 저장 방지 | 신규 확정 |
| D13 | **ReaderPool = read-only 커넥션 (`mode=ro`)** — thread-local, `check_same_thread=False`, sqlite-vec RO 로드. `j1_engine.run()` 검증 완료 | 신규 확정 |
| D14 | **임베딩은 writer 스레드에서 통째 실행** — remember()가 임베딩+INSERT 한 덩어리이므로 락 밖 분리 불가. `slow_job_warn_ms` 200→**500ms** 상향, 큐 500 유지. 임베딩 워밍업은 core 기동 시 수행 | 신규 확정 |
| D15 | **core PRAGMA = BeamMemory와 동일** (WAL + busy_timeout 5000 + foreign_keys ON, synchronous 미설정) — 과도기 임베디드와 충돌 없음. `MNEMOSYNE_BUSY_TIMEOUT_MS` env로 busy_timeout 조정 가능 | 신규 확정 (Q3-1) |

### 2.2 B 스펙 §7.2 보정 (SingleWriter job)

- `store_kept` job = `remember()` 호출 (임베딩 포함 ~0.1s). `slow_job_warn_ms=500`으로 상향 (기본 200은 정상 임베딩 job에서 매번 경고).
- `remember()` metadata에 `idem_key`, `source_agent`, `session_key` 항상 포함 (D12).

### 2.3 B 스펙 §7.5 보정 (prefetch 파이프라인)

- `j1_engine.run()` 분리: `retrieve()` = `build_lane_pool` + `_filter_and_rank` (ReaderPool에서 실행), `rerank()` = `jev_rerank` (to_thread + JEV 세마포어). `run()`은 기존 호출부 호환을 위한 조합 래퍼.
- ReaderPool의 RO 커넥션에서 `_embeddings.embed()`는 `beam_mod._embeddings` 전역 사용 → core 프로세스에서 모델 1회 로드 (process-wide 공유).

### 2.4 B 스펙 §12 Q분기 확정

| Q | 분기 |
|---|---|
| Q1 | **1안** — metadata 저장·조회 가능 확인 (D12) |
| Q2 | **불가능 분기** — 임베딩+INSERT 한 덩어리. writer에서 통째 실행, 지연 측정으로 큐·warn 상향 (D14) |
| Q3 | **RO 커넥션 그대로** (D13) |
| Q3-1 | **동일 PRAGMA 확인, core 쪽 재설정 불필요** (D15) |
| Q4 | **retrieve()/rerank() 분리 가능** (D16) — `run()` 래퍼 유지 |
| Q5 | **to_thread 필요** — 동기 httpx.Client 확인 |

---

## 3. P0 산출물

- 실측 스크립트: `$LOCALAPPDATA/hermes/cache/scratch/p0_verify.py` (재실행 가능)
- 검증 DB: 스냅샷 `data/snapshots/snap-20260927.db` 복사본 (프로덕션 무접촉)
- G-AS/G-qual 게이트 로직, j1 파이프라인 로직은 무수정 (P0는 확인만)

---

## 4. P1 착수 조건 (모두 충족)

- [x] 스펙 v1.0 승인 (조건부 3건 반영)
- [x] P0 Q1~Q5 + Q3-1 코드 검증 완료
- [x] 분기 결정 (D12~D15)
- [x] 스펙 v1.1 확정 (본 문서)

**→ P1: core 서버 구현 가능** (HTTP/인증/health/prefetch/turns/ledger/멱등성/SingleWriter/ReaderPool)