# Changelog

## [0.1.0] - 2026-09-29

### 첫 릴리즈 — JEV-Mnemosyne Middleware (Hermes 메모리 플러그인)

JEV(Mnemosyne용 LLM reranker) 기반 메모리 검색 강화 + 쓰기 게이트를 갖춘
Hermes 메모리 플러그인의 첫 공개 릴리즈.

### J1 재순위화 파이프라인 (`gateway/j1_pipeline.py`)
#### Added
- lane pool (FTS / vector / importance / graph) + RRF 통합 (`build_lane_pool`)
- 보수적 게이트 (`_filter_and_rank`) → JEV choice rerank (`jev_rerank`)
- prefetch당 `pool`→`gate`→`jev`→`lift` 4-이벤트 trace (`gateway/trace.py`, ring buffer 512KB)

### 쓰기 게이트 G-qual (user) / G-AS (assistant) (`gateway/write_gate.py`)
#### Added
- G-qual: `store==NO_STORE && type==NO_STORE && conf>=0.6` → SKIP (P8 프롬프트 기반)
- G-AS: `store==NO_STORE | (store==STORE && type==context)` → SKIP
  (gold50: precision 0.744 / recall 0.935 / F1 0.829)
- KEEP/SKIP 모두 `jev_trace.log`에 기록 (unconditional trace, 2026-09-29)
- 킬스위치 `JEV_WRITE_GATE=0` → 게이트 비활성(전량 KEEP)
- `ASSISTANT` / `USER` prefix로 역할 구분 저장

### Hermes 통합 (`harnesses/hermes_j1.py`, `harnesses/jev_mem_plugin/`)
#### Added
- `JevRerankProvider`: `MnemosyneMemoryProvider` 상속 — `prefetch()`만 오버라이드
- `sync_turn()` 4-way 분기 (both KEEP / user SKIP / asst SKIP / both SKIP)
- 섀도잉 안전 accessor (`j1_access.py`, `wg_access.py` — hermes-agent `gateway` 패키지 충돌 우회)
- Hermes plugin discovery 계약 (`register_memory_provider`)

### 검증 / 실험 산출물
#### Added
- `harnesses/smoke_write_gate.py` — 7케이스 ALL PASS (SKIP/KEEP/킬스위치/JEV실패/G-AS 2종/sync_roles)
- `memory-classification-evaluation/` — JEV_INGESTION_REPORT, AB_WRITE_GATE_REPORT, ASSISTANT_GATE_REPORT
- A/B 실사용 1차 (12쿼리, 2,000+ rows 후 재평가 예정)

### Prior history (pre-0.1.0, 컨텍스트용)
- `3e36675` — 구현: JEV 쓰기 게이트 (P8+G-qual)
- `7615e1a` — G-AS assistant 게이트 통합 (sync_turn 4-way 분기, smoke 7케이스 ALL PASS)
- `c351ed5` — B: KEEP/SKIP 모두 trace + G-AS 09-29 실측 문서화
- `e1389b2` — docs: G-AS 적용 완료 반영
- `dbe7c01` — docs: Hermes 종속성 독립화 로드맵