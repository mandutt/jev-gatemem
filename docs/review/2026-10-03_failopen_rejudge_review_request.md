# 검토요청서 — JEV 장애(fail-open) 메모리 저장의 식별·재분류 설계 검토

| 항목 | 내용 |
|---|---|
| 요청일 | 2026-10-03 |
| 검토 대상 | JEV-Mnemosyne Middleware 의 JEV API 장애 기간 메모리 저장 처리 설계 |
| 검토 목적 | 「태그 + 원문 보존 → JEV 회복 후 재분류」 구조의 타당성·리스크·대안 검토 |
| 판단 필요 | 아래 7번 검토 질문 (Q1~Q6) |
| 독립성 | 본 문서만으로 전체 상황 파악 가능 (코드/로그는 발췌 포함, 참조 경로는 부록) |

---

## 1. 검토 배경

사용자가 TypeSafe(JEV API 제공사) 크레딧 소진으로 **2026-10-02 00:00 ~ 10-03 11:04 동안 JEV API가 전부 실패**(HTTP 402 → 403)한 상태로 시스템을 계속 사용했다.

이 기간의 대화가 Mnemosyne 메모리에 전부 기록됐는데, **fail-open 원칙**(아래 3.1)에 따라 JEV 판정 없이 "전부 저장"됐다. 문제는:
1. 이 기간 메모리는 평소와 구분할 **태그가 없어** 식별 불가 (설계 의도 F11이 402/403에 미적용)
2. **원문이 보존되지 않아** 사후 재분류 불가능
3. 결과적으로 **필터링 없이 저장된 오염 메모리가 평소와 동일하게 recall에 노출**됨

이에 대해 「장애 메모리 식별 → 태그 → JEV 회복 후 재분류」 구조를 제안했으나, 그 전에 **독립 검토**를 요청한다.

---

## 2. 시스템 개요

**JEV-Mnemosyne Middleware**는 Hermes(LLM 에이전트)의 메모리 저장 파이프라인이다. 데몬(`jev_mem_core`)이 Hermes의 대화 턴(user/assistant 발화)을 받아:

```
Hermes 턴 → /v1/turns 수신
  → ingest_ledger 기록 (idem_key, payload_json=대화 원문)
  → write-gate 판정
       user 발화:      G-qual 규칙 (JEV 호출, 1500자 truncation)
       assistant 발화: G-AS  규칙 (JEV 호출)
  → KEEP만 Mnemosyne DB(working_memory) 저장
    (metadata_json에 source_agent/session_key/idem_key/turn_id 기록)
  → terminal 상태 (stored/skipped) 도달 시 payload_json=NULL 처리 (프라이버시)
```

- **JEV API**: `https://api.typesafe.ai/v1/systemone` (모델 `jev-latest`), POST 1회에 gateway classification + ranking 동시 수행
- **저장 DB**: Mnemosyne `working_memory` / `episodic_memory` (SQLite)
- **대기열**: `ingest_ledger` (SQLite) — 상태: received / gated / stored / skipped / pending_gate / failed

### 2.1 판정 규칙 요약

| 게이트 | 규칙 | KEEP 조건 |
|---|---|---|
| G-qual (user) | store==NO_STORE && type==NO_STORE && conf>=0.6 → SKIP | 그 외 (실패 시 전부 KEEP) |
| G-AS (assistant) | store==NO_STORE \|\| (store==STORE && type==context) → SKIP | 그 외 (실패 시 전부 KEEP) |

### 2.2 관련 상태 코드 (실측)

| 상태 | 의미 | 로그에서 |
|---|---|---|
| `reason=http-402` | HTTP 402 Payment Required (크레딧 소진) | `write-gate HTTP 402 -> KEEP` |
| `reason=http-403` | HTTP 403 Forbidden | `write-gate-as HTTP 403 -> KEEP` |
| `reason=no-key` | TYPESAFE_API_KEY 없음 | `-> KEEP` |
| `reason=parse` | 응답 파싱 실패 | `-> KEEP` |
| transient (`http-5xx`, `error`) | 서버 오류·예외 | **raise → JevUnavailable → pending_gate 스풀 (재시도 큐)** |

---

## 3. 설계 의도 (SoT: B 스펙 + F11)

### 3.1 fail-open 원칙
JEV API 실패 시 **KEEP(전부 저장)** — 저장 누락(데이터 손실)보다 과잉 저장을 택한다.
근거: 필터링은 "있으면 좋음"이지만, 대화 기록 손실은 복구 불가.

### 3.2 F11 — fail_open 마커 (이미 구현됨)
```
store.py  _remember_with_meta():
    if fail_open:
        meta["gate"] = f"fail_open:{reason}"
```
**의도**: "게이트 없는 저장(gate-less storage) 마커 → 이후 재판정/정리 가능" (코드 주석 원문).
그리고 pipeline.py의 `fail_open_reasons`:
```python
transient = ("http-5", "error")
fail_open_reasons = ("http-401", "no-wg", "kill", "parse")
# reason이 fail_open_reasons에 속하고 keep=True면 r["fail_open"]=reason → meta gate 마커 부착
```
`/v1/status`의 `degraded_reasons`와 `gate_fail_open_total` 통계도 이 마커에 의존.

### 3.3 프라이버시 B 스펙 — 원문 미보존
`ledger_mark(..., clear_payload=True)` : 턴 처리 완료(terminal) 시 `payload_json=NULL`.
**의도**: 대화 원문이 DB에 남지 않도록 (로컬 단일 사용자 + Windows ACL로 통제하지만, 최소 보존 원칙).

---

## 4. 장애 사건 실측 데이터

| 측정 항목 | 값 | 근거 |
|---|---|---|
| 장애 기간 | 2026-10-02 00:00:08 ~ 10-03 11:04:07 | `core.log` |
| HTTP 402 발생 | **61회** (10-02 하루 종일) | `core.log.2026-10-02` grep |
| HTTP 403 발생 | **33회** (10-03 11:04까지) | `core.out.log` grep |
| 이 기간 저장된 메모리 | **35건** (10-02 24건 + 10-03 11건) | `ingest_ledger` + mnemosyne.db |
| 이 기간 decisions reason | 전부 `http-402` / `http-403` | `ingest_ledger.decisions_json` |
| fail_open 마커 부착 건수 | **0건** (metadata_json 검색) | mnemosyne.db |
| 원문 payload 보존 | **0건** (stored 240 / skipped 40 전부 NULL) | `ingest_ledger.payload_json` |
| attempts>1 (재시도) | 0건 | `ingest_ledger` |
| last_error 기록 | 0건 | `ingest_ledger` |

**핵심**: 402/403은 `transient`가 아니라 KEEP으로 즉시 저장됐고, `fail_open_reasons`에 없어 마커도 안 붙었다. 저장은 됐지만 "이 메모리는 평소와 다른 경로로 들어왔다"는 증거가 기록되지 않았다.

---

## 5. 문제 분석 (기대 vs 실제)

| # | 기대 (설계 의도) | 실제 (실측) | 영향 |
|---|---|---|---|
| G1 | fail_open 마커로 장애 저장 식별 가능 | `http-402`, `http-403`이 `fail_open_reasons`에 없어 마커 미부착 | 장애 메모리 식별 불가, degraded 감지·통계 누락 |
| G2 | (설계상 명시 없음) | `clear_payload=True`로 원문 즉시 폐기 | **재분류 불가능** (판정에 필요한 원문 소멸) |
| G3 | fail_open 저장은 "일시적"이며 재분류 예정 | 재분류 경로(pending_gate)는 transient만 대상, 402/403은 즉시 저장 | 오염 메모리가 평소와 동일하게 recall에 영구 노출 |
| G4 | 402(크레딧)은 일시적 문제 | 재시도 없이 즉시 저장 (pending_gate로 안 감) | 장애 하루치가 죄다 "확정 저장" 취급 |

**근본 원인**: fail-open의 두 축 — 「저장 누락 방지」(OK) 와 「사후 복구 가능성」(미구현) — 중 후자가 빠져 있다. F11 마커는 첫 축의 보조일 뿐, 재분류 파이프라인(원문 보존 → 재판정 → 정리)이 없다.

---

## 6. 제안 설계 (검토 대상)

**원칙**: recall 배제(단순 삭제·차단)는 "보관 의미를 없애는" 방향이라 채택하지 않음. 대신 **나중에 JEV 회복 시 재분류가 가능한 구조**를 제안.

### P1 — fail_open 마커 확장 (코드 1줄)
```python
fail_open_reasons = ("http-401", "http-402", "http-403", "no-wg", "kill", "parse")
```
→ 402/403 저장 메모리에 `metadata.gate = "fail_open:http-402"` 부착, degraded/통계 반영.

### P2 — fail_open 저장 시 원문 보존
- `_finish`의 `clear_payload`를 `fail_open` 여부에 따라 분기: **fail_open 저장 건만 `clear_payload=False`** (평소는 기존대로 NULL)
- 보존 위치: `ingest_ledger.payload_json` (기존 스키마 그대로, 원문은 redaction 적용 상태)
- **프라이버시 트레이드오프**: 원문이 terminal 상태로 남음. 단, redaction(고정밀 패턴: 카드번호·전화 등)은 저장 경로에 이미 적용됨. 보존 기간 상한(예: 30일) 설정 가능.

### P3 — 수동 재분류 스크립트 (JEV 회복 후 실행)
```
tools/jed_failopen_rejudge.py
  1. ledger에서 fail_open + stored + payload 존재 행 선별
  2. payload의 user/assistant 원문으로 write-gate 재호출 (JEV 정상 상태)
  3. 판정:
       KEEP  → 유지 + fail_open 마커 제거 (정상 메모리로 승격)
       SKIP  → 해당 메모리 삭제 (또는 아카이브) — 삭제 전 스냅샷
  4. 결과 리포트 (건수, reason별, gold 손실 여부)
```

### P4 — (선택) 재분류 전 recall 노출 완화
- 태그된 메모리를 recall에서 **완전 배제하지 않고** 가중치 하향 (임시, 옵션)
- 또는 `JEV_FAILOPEN_HIDE=1`로 완전 필터 (기본 OFF — 사용자는 보관 유지 원함)

### 적용 범위 (변경 파일)
`jev_mem_core/pipeline.py` (fail_open_reasons, _finish), `jev_mem_core/store.py` (마커는 기존), 신규 `tools/jed_failopen_*.py`, 문서(HANDOFF, 스킬)

---

## 7. 검토 요청 질문

**Q1. fail-open 원칙과 402/403의 취급**
402(크레딧 소진)·403은 "일시적" 문제일 수 있는데, 현재는 재시도 없이 즉시 저장된다. (a) pending_gate 스풀로 보내 일정 시간 후 재시도하는 편이 나은가? (b) 아니면 즉시 저장 + 사후 재분류가 옳은가? (c) 장애 지속 시간이 길어지면 어떤 방식이 메모리 품질에 더 유리한가?

**Q2. 원문 보존 (P2)의 트레이드오프**
fail_open 건만 원문을 redacted 상태로 ledger에 보존하는 설계는 타당한가? 프라이버시(B 스펙: terminal 시 원문 폐기)와 재분류 가능성 사이의 절충점으로서 충분한가? 대안(별도 보존 DB, 보존 기간 상한, 암호화)이 있다면?

**Q3. 재분류 시점: 수동 vs 자동**
(수동) 사용자가 스크립트 실행 — 안전·명시적. (자동) 데몬이 장애 해소 감지 후 자동 재분류 — 편리·사고 위험. 어느 쪽이 시스템 운영에 적합한가? 자동이면 해소 감지 조건(예: 연속 성공 N회)과 재분류 트리거는 어떻게 설계해야 하나?

**Q4. 재분류로 SKIP 판정된 기존 메모리의 처리**
이미 recall·consolidation(에피소드 요약)에 반영됐을 수 있는 메모리를 삭제해도 안전한가? (a) 삭제 (b) 아카이브/비활성 (c) 그대로 두되 신뢰도 하향 — gold(실제로 유용한) 메모리 손실을 막는 최선의 방법은?

**Q5. 재분류 전 recall 노출**
재분류 완료 전까지 오염(fail-open) 메모리가 평소와 동일한 recall 가중치로 노출되는 것 — (a) 허용 가능 (b) 가중치 하향 필요 (c) 완전 필터 필요? 사용자는 "보관 의미를 없애는" 완전 배제를 반대하나, 실사용 관점의 리스크 평가가 필요.

**Q6. 전체 설계 검토**
P1~P4 구성의 누락·과잉·대안. 특히 (a) F11 마커를 이미 두고도 402/403을 빠뜨린 원인 (b) 재분류 파이프라인에 필요한 다른 요소 (c) 유사 사례(결제 실패 fail-open)의 알려진 패턴이 있다면.

---

## 8. 부록

### 8.1 참조 파일 경로 (이 문서의 근거)
- `jev_mem_core/pipeline.py` — 게이트 판정·fail_open·_finish (clear_payload)
- `jev_mem_core/store.py` — F11 마커 (`_remember_with_meta`), redaction
- `jev_mem_core/ledger.py` — `ledger_mark` clear_payload, `recover_incomplete`
- `gateway/write_gate.py` — G-qual/G-AS 평가, fail 시 `reason=http-xxx` 반환
- `%LOCALAPPDATA%/jev-mem/logs/core.log.2026-10-02`, `core.out.log` — 장애 로그
- `%LOCALAPPDATA%/jev-mem/core_state.db` — ingest_ledger (식별·기록 근거)
- `%LOCALAPPDATA%/hermes/mnemosyne/data/mnemosyne.db` — 저장 메모리

### 8.2 실측 로그 발췌
```
2026-10-02 00:00:31,005 INFO jev_write_gate_direct: write-gate HTTP 402 -> KEEP
2026-10-02 00:00:31,194 INFO jev_write_gate_direct: write-gate-as HTTP 402 -> KEEP
2026-10-03 11:04:07,764 INFO jev_write_gate_direct: write-gate-as HTTP 403 -> KEEP
2026-10-03 11:04:29,582 INFO gateway.j1_pipeline: Jev choice HTTP 403
2026-10-03 11:04:29,583 ... POST /v1/prefetch HTTP/1.1 200 7375
2026-10-03 11:18:22,844 INFO httpx: HTTP Request: POST .../systemone "HTTP/1.1 200 OK"  ← 회복
```

### 8.3 용어
- **JEV**: TypeSafe systemone API의 분류/랭킹 모델 (`jev-latest`)
- **write-gate**: 대화 발화를 KEEP(저장)/SKIP(폐기) 판정하는 게이트
- **fail-open**: 게이트 실패 시 전부 저장하는 원칙 (누락 방지)
- **F11**: fail_open 메타 마커 설계 항목 번호
- **pending_gate**: JEV 일시 실패 시 대화 원문을 보관하고 나중에 재판정하는 스풀 상태
- **clear_payload**: 턴 처리 종료 시 원문 삭제 (프라이버시)
- **G-qual / G-AS**: user/assistant 발화별 분류 규칙