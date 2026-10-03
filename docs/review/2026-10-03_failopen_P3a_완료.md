# P3a 완료 보고 — 자동 재판정 worker (fail-open quarantine → rejudge)

작성: 2026-10-03 (KST) · 상태: **구현+검증 완료, 라이브 데몬 재시작 대기**
설계 SoT: `docs/review/2026-10-03_failopen_P3_설계안.md` (외부 AI 3종 검토 종합, 실행주체 A안)

## 1. 구현 범위 (P3a)

| 구성 | 파일 | 내용 |
|---|---|---|
| 재판정 엔진 | `jev_mem_core/recover.py` (신규) | `RejudgeEngine` — quarantine 조회/lease claim/strict 재판정/verdict 기록/apply/incident 종결. CLI·데몬 공용 순수 함수 |
| 회복 감지 | `jev_mem_core/pipeline.py` | `_note_recovery()` — 실사용 턴 성공 시 open incident에 streak 1회 (턴당 1회, to_thread) |
| 배치 루프 | `jev_mem_core/app.py` | op_loop 60s tick에 자동 재판정 마이크로 배치 (ready → open → remnant 순) |
| 상태 노출 | `jev_mem_core/server.py` | `/v1/status` `rejudge{pending, ready_incidents, skip_staged, oldest_staged_days}` |
| 설정 | `jev_mem_core/config.py` | `JEV_AUTO_REJUDGE` / `JEV_REJUDGE_BATCH` / `JEV_REJUDGE_STREAK` / `JEV_REJUDGE_COOLDOWN` / `JEV_REJUDGE_LEASE` / `JEV_REJUDGE_TRANSIENT` / `JEV_REJUDGE_BILLING` |
| 스키마 | `jev_mem_core/ledger.py` | `gate_outage` P3 컬럼(recovery_success_count·confirmed_at·eligible_at·rejudge_finished_at), `rejudge_lease`, `rejudge_verdicts`, `_migrate_outage_p3`, `_migrate_status_check` |
| writer | `jev_mem_core/writer.py` | `submit_sync()` — 동기 `.result()` 전용 raw Future 경로 (§4 버그 수정) |

## 2. 검증 결과 (실측)

| 검증 | 스크립트 | 결과 |
|---|---|---|
| 단위 (ledger/verdict 분류/quarantine) | `tools/jed_failopen_p3a_verify.py` | **20/20 통과** |
| sync-path 회귀 (InvalidStateError 재발 방지) | `tools/jed_failopen_p3a_syncpath_verify.py` | **7/7 통과** — 루프 스레드 직접 호출·to_thread·async submit 3경로 전부 |
| 실통합 (실 JEV 호출) | `tools/jed_failopen_p3a_live_verify.py` | 이전 세션 전부 통과 (실 API 2콜, 테스트 행 원복) |
| 실데이터 소진 | 라이브 데몬 op_loop | 잔여 quarantine **26건 처리 → 20 KEEP / 6 SKIP, pending 0** (2026-10-03 16:35~36 로그) |

## 3. 라이브에서 발견·수정한 버그 3건 (P3a 실전 검증)

1. **HTTP 실패-응답의 skip 오분류** — `rejudge_one`이 `reason='http-NNN'` KEEP을 정상 verdict로 취급해 `_classify_verdict`가 skip 처리. → HTTP 실패를 예외로 승격(`exc.reason`/`status_code`), run_batch halt 경로(D8)로 유도.
2. **무한 재처리 루프** — `quarantine_rows`에 `NOT LIKE '%rejudged%'` 필터 누락으로 apply 완료 행을 매 tick 재claim. → 필터 추가 (v2 도구와 동일 규칙).
3. **`InvalidStateError` (submit/wrap_future 불일치)** — `writer.submit()`은 이벤트 루프 스레드에서 `asyncio.wrap_future` 래핑 Future를 반환하는데 `recover.py`가 즉시 `.result()` 호출 → `Result is not set` 매 tick 반복. **incident 기반 재판정(회복 감지·streak)이 라이브에서 전부 실패**하고 있었음 (remnant 경로만 to_thread라 우연히 동작). → `SingleWriter.submit_sync()` 신설(raw concurrent Future, 컨텍스트 무관) 후 `.result()` 호출부 6곳 전환 + `_note_recovery`/op_loop는 `asyncio.to_thread` 경유.

> 3번은 실데몬 로그(`core.log` 16:24~16:38, `recovery_ready_incidents failed` / `outage_open_incidents failed` / `_note_recovery failed`)에서 발견. sync-path 회귀 스크립트로 재발 방지 고정.

## 4. 남은 작업

- [ ] **라이브 데몬 재시작** (사용자 승인 필요) — 현재 데몬(pid 22492, port 47821, 16:37 기동)은 수정 전 이미지로 동작 중. 재시작 후 `/v1/status`의 `rejudge` 블록 정상화 + `core.log`에서 InvalidStateError 소멸 확인.
- [ ] 재시작 후 확인: `GET /v1/status` → `rejudge.pending: 0`, `ready_incidents: []`, `human_alert: false`; `core.log`에 `recovery_ready_incidents failed` 미발생.
- [ ] 커밋 + 푸시 (변경: writer.py, recover.py, pipeline.py, app.py + 검증 스크립트 2종 + 본 문서).
- [ ] (P3b 후보) CLI `tools/jed_failopen_rejudge_v2.py`를 `RejudgeEngine` 공용 경로로 전환, admin 엔드포인트.
