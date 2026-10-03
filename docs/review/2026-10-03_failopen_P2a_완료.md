# P2a 완료 — 불변식 반전 + failure_class + 경보 (2026-10-03)

## 상태: ✅ 완료 (코드 + 라이브 실측 검증)

## 변경 요약

| 변경 | 파일 | 내용 |
|---|---|---|
| failure_class 추가 | `gateway/write_gate.py` | `_classify_http()`(402→billing, 401/403→auth, 429/5xx→transient, 기타→unknown), `_failure_result()`(KEEP+availability/preservation/retry/probe 정책) |
| 불변식 반전 | `jev_mem_core/pipeline.py` | allowlist(4개) 폐기 → **정상 판정(NORMAL_REASONS 8개)이 아닌 모든 KEEP = fail_open** + `_infer_failure_class()` 폴백추론 |
| 클래스 집계 | `jev_mem_core/pipeline.py` | `gate_fail_{class}` 카운터 (billing/auth는 1회만으로 degraded) |
| 경보 노출 | `jev_mem_core/server.py` | `/v1/status`에 `human_alert` + `gate_fail_classes` — billing/auth 감지 시 `gate_billing_exhausted`/`gate_auth_failed` 이유 추가 |

## 라이브 실측 (2026-10-03, 데몬 재시작 3회)

### ① 정상 상태 (거짓 경보 없음)
```
degraded: False | reasons: [] | human_alert: False | classes: {}
```

### ② 킬스위치 (no-wg → config 클래스)
```
decisions.user: {keep: true, reason: "killswitch-off", fail_open: "killswitch-off",
                 availability: "unavailable", preservation: "quarantine"}
status: fail_total=2, classes={gate_fail_config: 2}
```
→ `killswitch-off`도 config 클래스로 분류되도록 보완 (최초엔 unknown)

### ③ HTTP 402 에뮬레이션 (목 서버 127.0.0.1:15099)
```
decisions.user: {keep: true, reason: "http-402", failure_class: "billing",
                 availability: "unavailable", preservation: "quarantine",
                 request_retry_policy: "none", recovery_probe_policy: "periodic"}
status: degraded=True | reasons=['gate_billing_exhausted'] | human_alert=True
        classes={'gate_fail_billing': 2} | fail_total=2
```
→ **402 = "충전 필요" 경보 + 사람 개입(alert) 표시** — B-AI 지적 실측 입증

## 불변식 (C-AI 설계 반영)
```
availability==UNAVAILABLE && decision==KEEP → preservation==QUARANTINE
```
- write_gate가 failure 반환 시 3-tuple(KEEP/클래스/정책) 제공
- pipeline은 reason 기반으로 동일 불변식 강제 (게이트 미탑재 시에도)

## 정리
- 테스트로 저장된 fail_open 메모리 4건 삭제 완료
- 데몬 정상 복원 (실 API, circuit closed)
- 남은 P2b: 상태 직교 컬럼 + rejudge 엔진 + 승인 흐름 (승인 대기)