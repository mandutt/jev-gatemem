# P2b 완료 — 상태 머신 확장 + incident / quarantine + 재판정 엔진 (2026-10-03)

## 상태: ✅ 완료 (단위 7/7 + 라이브 통합 실측)

## 변경 요약

| 구성 | 파일 | 내용 |
|---|---|---|
| **상태 확장** | `ledger.py` | STATUSES 6→11 (`fail_open_quarantine`, `rejudge_pending/running/kept/invalidated`) + **CHECK 마이그레이션**(기존 테이블 6→11 상태 허용, rename-swap 데이터 보존) |
| **gate_outage** | `ledger.py` | `gate_outage(incident_id, started_at, ended_at, reason, failure_class, count, status)` — 장애 구간 기록, 5분 연속 병합, open/close |
| **incident 부여** | `pipeline.py` | fail_open 시 `_incident_id()` 생성 + `outage_open`으로 확정, `fail_open_quarantine` 상태 전이, stats에 outages 노출 |
| **메모리 연결** | `store.py` | metadata에 `incident_id` 저장 (재판정 batch 단위) |
| **재판정 엔진** | `tools/jed_failopen_rejudge_v2.py` | strict 모드, incident 필터, batch, `rejudge_verdicts` 테이블(keep/skip/failed+모델+지연), apply(dry-run 기본) |
| **incident 도구** | `tools/jed_failopen_incident.py` | fail_open 메모리 스캔→incident 백필, outages 현황, close |
| **status 노출** | `server.py` | `/v1/status`에 `outages: {open, open_incidents}` |

## 실측 검증

### 단위 (7/7, 임시 DB)
- 스키마/outage 생성/연속 병합/close/STATUSES/CHECK 허용/클래스 집계/verdict 테이블

### 라이브 (402 목 서버)
```
/v1/turns → status: fail_open_quarantine
  user: {keep: true, reason: "http-402", failure_class: "billing",
         fail_open: "http-402", incident_id: "inc-de77e876947a"}
ledger: p2b-incident-0002 | fail_open_quarantine | incident 연결 ✅
메모리: gate: fail_open:http-402 | incident: inc-de77e876947a ✅
gate_outage: inc-78f54c6fc176 [open] http-402 billing count=2 (연속 병합) ✅
```

### CHECK 마이그레이션 (중요)
기존 실 DB에서 `CHECK constraint failed` 발생 → `init_schema`에 **`_migrate_status_check`** 추가.
rename-swap으로 테이블 재생성, **297행 보존 확인**. 재시작 후 quarantine 전이 정상.

### 백필 (실제 403 2건)
- `48f06bb6ed2360d7`/`8c7b3441597eb71c` (10-03 P2a 작업 중 403 저장) → `inc-6e798b116d6b` 연결
- 실제 재판정 dry-run: `[USER] 좋아 진행해줘` → SKIP, `[ASSISTANT] P2a 완료 보고` → KEEP ✅

## 정리
- P2b 테스트 오염 4건 삭제 + 테스트 incident/verdict 삭제
- 데몬 정상 복원 (실 API, circuit closed, outages 0)

## 남은 단계
- **P3**: 자동화 (회복 감지 + 자동 재판정 스케줄) — P2a/P2b 관찰 후 승인 대기
- 실제 403 2건의 apply(승격/archived)는 P1과 동일한 수동 승인 절차로