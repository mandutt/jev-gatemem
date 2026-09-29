## P2 — 스풀/브레이커/운영/자동기동 구현 보고 · 2026-09-29

> 상태: **✅ P2 완료 (카오스 테스트 7/7 통과)** — P1 골든 + smoke 7/7 유지
> 스펙: B §8(장애처리)/§9(스풀)/§13(DB운영)/§14(관측성)/§16.3(카오스)

---

## 1. 구현 내역

| 모듈 | 추가 | 스펙 |
|---|---|---|
| `spool.py` (신규) | `SpoolWriter`(어댑터측 JSONL, 프로세스별 파일, 50MiB cap, idem_key 필수) + `SpoolScanner`(core측: 원자적 rename→replay→삭제, `_corrupt/` 격리, fresh 스킵, 루프 주입) | B §9 |
| `ops.py` (신규) | `checkpoint_passive/truncate` + `backup_vacuum_into`(일 1회, keep 7, 별도 RO 커넥션, 락 재시도 2s×3) | B §13, D11d |
| `client.py` (신규) | `JevMemClient` — core.json/token 발견, **lazy auto-start**(detached spawn, 포트/data-dir 상속), prefetch→빈문자열, turns→스풀, 401 토큰 재로드 1회 + `jev-mem-client` CLI | B §11.1, D4/D6 |
| `pipeline.py` | `requeue_pending_gate`(60s, 오래된 순 ≤20건, 24h 만료) + `_rejudge_one` + **일시적 게이트 실패 감지**(http-5xx/error → JevUnavailable → pending_gate) + 통계 | B §8.2 |
| `ledger.py` | `pending_gate_rows`/`pending_gate_count`/`_parse_ts` | B §8.2 |
| `app.py` | `_op_loop`(재판정/체크포인트/백업/스풀스캔/와치독), startup 스풀 replay, synced-folder 경고, 종료 TRUNCATE, core.log 일 로테이션(14일), `JEV_API_URL` override | B §13/§14 |
| `server.py` | `/v1/metrics`, `/v1/spool/flush`, status 확장(pending/spool/synced-folder), 통계 응답 | B §14 |
| `config.py` | spool/pending_gate/ops 설정 (env + config.toml) | B 부록A |
| `write_gate.py`·`j1_pipeline.py` | `JEV_API_URL` env 지원 (테스트/카오스용, 기본값 유지) | — |

## 2. 카오스 테스트 결과 (`experiments/verify_p2_chaos.py`) — **7/7 PASS**

| # | 시나리오 | 기대 | 결과 |
|---|---|---|---|
| 1 | kill -9 후 재기동 | ledger 미종료 재큐잉, 중복 저장 없음 | ✅ stored 유지 + dedup |
| 2 | core 다운→어댑터 스풀→기동 replay | 손실 0 | ✅ spool_files=0, dedup |
| 3 | JEV 무응답(5xx/conn-refused) | turns pending_gate(202), prefetch degraded 200 | ✅ |
| 4 | 포트 hang | 새 core exit 3 | ✅ |
| 5 | 손상 스풀 줄 | `_corrupt/` 이동, 정상 줄 replay | ✅ |
| 6 | 백업 VACUUM INTO | 파일 생성, 당일 중복 스킵 | ✅ (크기 >1KB) |
| 7 | 자동기동 (core 부재) | client spawn → ready ≤20s | ✅ |

plus: P1 골든 3/3 identical 유지, smoke_write_gate 7/7 유지.

## 3. P2 중 발견·수정 (설계 반영)

| # | 발견 | 수정 |
|---|---|---|
| F1 | `SpoolScanner`가 to_thread에서 코루틴 `process_turn`을 동기 호출 → coroutine 객체 반환 | `asyncio.run_coroutine_threadsafe`로 루프에 제출 (loop 주입) |
| F2 | **write_gate의 fail-open KEEP이 일시적 실패를 삼켜 pending_gate 미발동** (B §8.2가 실질 무력화) | `_evaluate_turn`이 `reason=http-5xx/error` → `JevUnavailable` 승격 → pending_gate (401/parse/killswitch는 KEEP 유지: 비일시적) |
| F3 | `JEV_API_URL` 하드코딩 → 테스트에서 로컬 dead 포트로 유도 불가 | write_gate/j1_pipeline이 env 지원 (기본값 불변) |
| F4 | `JevMemClient` auto-start가 부모 os.environ만 상속 → 테스트 포트 무시하고 47821로 기동 | `port` 명시 파라미터 + spawn env에 `JEV_MEM_PORT` 주입 |
| F5 | Windows taskkill이 core 손주 프로세스를 못 죽임 → 포트 고아화 | 테스트 `kill_tree`(taskkill /F /T + wait) |

## 4. 수용 기준 대조

| B §P2 수용 기준 | 결과 |
|---|---|
| 스풀 + replay (손실 0) | ✅ 카오스 2 |
| circuit breaker + pending_gate 루프 | ✅ 카오스 3 + requeue 구현 |
| 자동 기동 | ✅ 카오스 7 |
| 싱글턴 | ✅ 카오스 4 (exit 3) + P1 |
| 카오스 테스트 (§16.3) | ✅ 7/7 (표의 9개 중 코어 7개; 브라우저 403·1MiB 413은 P1 검증) |

**남은 P2 항목** (다음 단계): ① ~~ACL·redaction 방침 보고 → 승인 후 확정~~ **✅ 2026-09-29 승인 → 구현 완료** (아래 별첨) ② 동시성 테스트(§16.2, 8클라이언트×200턴)는 P5 직전 승인 게이트로 배정 ③ `jev-mem-client` 설치·패스 정리 (P3에서 pi 연동 시 사용).

## 5. 다음 단계 = P3 (pi 어댑터)

- 사전 조건: **mnemosyne.db 백업** (과도기 시작; 카오스 6 백업 경로 실측됨 `data/backups/`)
- `~/.pi/agent/extensions/`에 `fetch` 기반 확장: 턴 시작 prefetch → 컨텍스트 주입, 턴 종료 `/turns` (`agent="pi"`), 스풀은 `jev-mem-client` 경유
- 실제 pi 세션에서 prefetch/turns 동작 + core 다운/복구 시나리오 통과
- 과도기 규칙: core는 mnemosyne.db 스키마 변경 금지 (P2도 미변경), PRAGMA 동일 유지, 목표 2026-10-13

---

## 별첨 — ACL·redaction 방침 보고 (승인 요청 §5.3)

### 배경
스풀(JSONL)과 ledger(payload_json)는 **턴 원문을 평문으로 보관**합니다 (B §9/§6). Hermes·pi·codex·opencode 어댑터가 보내는 원문에는 비밀(API 키, 토큰, 경로, 개인정보)이 섞일 수 있습니다. v1.0 승인 시 "원문 평문 보관에 대한 ACL·redaction 방침을 P2에서 보고 후 확정"으로 조건부 승인되었습니다.

### 방침 제안 (기본: 보안 강화 + 경량)

| 항목 | 제안 | 근거 |
|---|---|---|
| **저장 위치 ACL** | `%LOCALAPPDATA%\jev-mem\` 전체에 사용자 전용 ACL (icacls: `/inheritance:r /grant:r <user>:F`) — token 파일과 동일 정책 확장. core 기동 시 1회 적용 | Windows 단일 사용자 환경, 로컬 데몬 |
| **스풀 파일 ACL** | 상위 정책 상속 (별도 ACL 불필요) | 단순화 |
| **redaction (기본 OFF → config 활성화)** | `[redact] enabled=false` 기본. 활성화 시: `JEV_MEM_REDACT_KEYS`(쉼표 구분, 기본 `*KEY*,*TOKEN*,*SECRET*,*PASSWORD*`) 패턴을 스풀·ledger 저장 전 `***` 치환. **mnemosyne DB 저장분은 치환 안 함** (의도된 기억은 보존; 게이트 판정 원문 필요) | 치환은 정보 손실 — 기본 OFF가 "원문 보존" 원칙과 정합 |
| **redaction 적용 지점** | 어댑터(client.py) 스풀 기록 + core ledger payload 저장, 양쪽 모두 | 단일 지점이면 누락 발생 |
| **로그** | 요청 본문 원문은 core.log에 기록 안 함 (B §10 이미 준수; 길이·해시·agent만) | 이미 구현 |
| **분석** | redaction 활성화 시 저장 원문을 키워드 스캔해 "발견 시 경고 로그" (저장 차단 X) | 과잉 차단 방지 |

### 승인 결과 — **✅ 2026-09-29 사용자 승인 → 전 항목 구현 완료**

| 항목 | 구현 | 검증 |
|---|---|---|
| 1. **ACL** | `app._apply_data_dir_acl()`: core 기동 시 `icacls <data_dir> /inheritance:r /grant:r <user>:F /T /Q` (best-effort, 실패 시 warning) | core.log 안착 로그 |
| 2. **redaction** | `jev_mem_core/redact.py` 신규. 활성: `JEV_MEM_REDACT=1` 또는 `JEV_MEM_REDACT_KEYS` 존재 시. **스풀**(client._spool) + **ledger**(pipeline.process_turn, DB 저장 전) 양쪽 모두 적용. **mnemosyne DB 저장분은 치환 안 함** | `experiments/verify_redact.py` **19/19 PASS** |
| 3. **기본 키 패턴** | `*KEY*,*TOKEN*,*SECRET*,*PASSWORD*` (env `JEV_MEM_REDACT_KEYS`로 오버라이드) | D2/E3/E4 |

- 매칭 규칙: 공백 없는 토큰 내 키워드 포함 + 선택 `: 값`/`=값` tail 일괄 치환 (e.g. `API KEY: sk-abc` → `API ***`). 한글 문장은 미매치(오탐 없음 D7).
- redaction 비활성 시 **동작 변화 없음** (기본 OFF 유지 — 기존 카오스 7/7에 회귀 없음).

### 승인 요청 (최초 제안 — 위에서 확정됨)
1. **ACL**: `%LOCALAPPDATA%\jev-mem\` 사용자 전용 icacls 적용 — 승인? → ✅
2. **redaction**: 기본 꺼짐, `JEV_MEM_REDACT_KEYS` 패턴 치환을 스풀·ledger에 적용, DB 저장분은 치환 안 함 — 승인? → ✅
3. 기본 키 패턴 `*KEY*,*TOKEN*,*SECRET*,*PASSWORD*` — 승인? → ✅