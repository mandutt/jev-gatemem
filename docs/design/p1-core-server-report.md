# P1 — jev-mem-core 서버 구현 보고 · 2026-09-29

> 상태: **✅ P1 완료 (수용 기준 통과)** — 골든 테스트 + 라이브 JEV 게이트 + smoke 7/7 유지
> 스펙: `docs/design/multi-agent-v1_1-p0-spec.md` (v1.1) / B 원문 `docs/design/reviews/`

---

## 1. 구현 내역 (`jev_mem_core/`)

| 모듈 | 내용 | 스펙 |
|---|---|---|
| `__init__.py` | version 0.2.0, PROTOCOL=1 | B §5.1 |
| `config.py` | Config dataclass + env/config.toml 로드 (tomllib, stdlib) | B §부록A |
| `ledger.py` | ingest_ledger 스키마, receive/duplicate/conflict, mark, recover_incomplete | B §6 |
| `writer.py` | **SingleWriter** (쓰기 전담 스레드+큐, QueueFull→503, slow warn 500ms) + **ReaderPool** (thread-local RO, mode=ro, sqlite-vec) | B §7.2/§7.3, v1.1 D13/D14 |
| `store.py` | **4-way 분기** (기존 hermes_j1 로직 이동) + `_remember_with_meta` (D12: idem_key/source_agent/session_key를 metadata로) + `find_stored_by_idem` (크래시 윈도우 조회) | B §5.4, v1.1 D12 |
| `pipeline.py` | **CircuitBreaker** + `process_turn`(ledger→gate→store→finish, session lock) + `process_prefetch`(stage1 lanes+RRF / stage2 JEV rerank, budget clamp D7a) | B §7.4/§7.5/§8.1 |
| `server.py` | aiohttp 앱, Bearer token, Origin/Host 가드, /health /prefetch /turns /turns/{id} /status /shutdown | B §5/§10 |
| `app.py` | bootstrap: 싱글턴(포트 bind, EADDRINUSE→health probe→exit 3), 토큰 생성, writer/reader 팩토리, 임베딩 워밍업, **크래시 복구 재큐잉**(D12 idem 조회) | B §4, v1.1 D12 |

## 2. 검증 결과

### 2.1 골든 테스트 (`experiments/verify_p1_core.py`) — **ALL PASS**
- 임베디드(`j1_engine.run`, JEV off) vs core RPC `/v1/prefetch` — **3/3 identical** (1881/3061/2968자)
- turns async → ledger `stored` / metadata(D12) / idempotency dedup / auth 401 / idem-key 필수 400 — 전부 PASS

### 2.2 라이브 JEV 게이트 (`experiments/verify_p1_live_gate.py`) — **PASS**
```
sync turn: user KEEP(store=STORE conf=0.96 type=commitment, 215ms)
           asst SKIP(store=NO_STORE conf=0.97 type=context, 282ms)  → 4-way: user만 저장
```

### 2.3 회귀 — **smoke_write_gate 7/7 PASS** (기존 임베디드 경로 무영향)

### 2.4 싱글턴
- 두 번째 core 기동 → 포트 bind 실패 → health probe 정상 → **조용히 종료 (exit 0)**
- 응답 없는 점유자 → exit 3 (미검증, 카오스 P2 범위)

## 3. P1 중 발견·수정 (설계 반영)

| # | 발견 | 수정 |
|---|---|---|
| F1 | `build_lane_pool`은 hydration 단계에서 **`get` kind**를 recall_raw로 요청 — pipeline 초기 recall_raw에 get 케이스 없어 pool 구성 실패(빈 결과) | `j1_engine.hydration_get` 분기 추가 (j1_engine._run과 동일 계약) |
| F2 | JEV off시 `jev_rerank(call_jev=False)`는 pool 전체 반환 → RPC 렌더가 6000자로 비대 (embedded: top_k=5 잘림) | `_render`에 `rows[:5]` 적용 — golden 3/3 일치 |

## 4. 수용 기준 대비

| 기준 | 결과 |
|---|---|
| 골든 테스트 (임베디드 vs core 출력 동일) | ✅ 3/3 identical |
| smoke_write_gate 7/7 유지 | ✅ ALL PASS |
| D5키 필수(서버 파생 없음) | ✅ 키 없으면 400 |
| D7a prefetch 타임아웃 clamp (1.5s 기본/2.0s 상한) | ✅ 코드 반영 (options.timeout_ms clamp) |
| D12 크래시 윈도우 1안 (idem metadata) | ✅ store+recover 구현 |

## 5. 다음 단계 (P2)

- 스풀(JSONL) + replay, circuit breaker 완성(pending_gate 재판정 루프), 자동기동(lazy-spawn), WAL 주기 체크포인트, 백업(VACUUM INTO), **ACL·redaction 방침 보고(§5.3)**, 카오스 테스트