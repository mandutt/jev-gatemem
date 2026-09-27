# Experiment F — Failure Fallback 검증 보고서 (스펙 §26-F)

- **날짜**: 2026-09-27
- **스크립트**: `experiments/run_experiment_f.py` (신규)
- **입력**: `data/dataset_curated.json` q101 (stealth 브라우저 쿼리, 한국어)
- **DB**: `data/snapshots/snap-20260927.db` (766 rows 스냅샷)
- **풀 크기**: 5 (lane pool → 보수적 게이트 후 top-40 이내)
- **원시 결과**: `experiments/results/experiment_f.json`

## 검증 대상

스펙 §26-F: 의도적으로 Jev 장애(4종)를 발생시켜 Mnemosyne-only fallback(스펙 §19:
`Jev 실패/타임아웃/비활성 → pool-only 결과`)이 정상 작동하는지 확인.

## 결과 (모두 PASS)

| 모드 | 시나리오 | J1 동작 | 결과 | pool 순서 보존 |
|---|---|---|---|---|
| healthy control | 실키 호출 (라이브) | `Jev choice: idx=0 latency=265ms pool=5` | ok | — (idx=0이라 순서 유지, lift 정상) |
| timeout | mock `ReadTimeout` raise | `Jev choice failed: ReadTimeout` → idx=None | ok | ✅ |
| 5xx | mock HTTP 503 | `Jev choice HTTP 503` → idx=None | ok | ✅ |
| network disconnect | mock `ConnectError` raise | `Jev choice failed: ConnectError` → idx=None | ok | ✅ |
| auth error | **라이브** api.typesafe.ai + invalid key | `HTTP/1.1 401 Unauthorized` → `Jev choice HTTP 401` → idx=None | ok | ✅ |
| Jev OFF | `call_jev=False` (JEV_RERANK=0 경로) | 호출 없음 → pool 그대로 | ok | ✅ |

**cross-mode 종합**: `all_match_pool_order: true`, `pass: true`

## 관찰

1. **모든 장애 모드에서 예외 미전파** — `jev_rerank()`가 내부에서 전부 잡고
   `idx=None → pool unchanged`로 귀결 (caller 크래시 없음).
2. **Jev OFF와 장애 fallback의 출력이 shape-동일** — 즉 JEV_RERANK=0 킬스위치와
   장애 fallback이 같은 경로(순서 보존 pool)로 수렴 → 스펙 §19 계약 충족.
3. **auth error는 라이브 검증 포함** — 실제 API가 401을 반환하는 것을 확인했고,
   `_jev_choice`가 `resp.status_code != 200` 분기로 안전하게 처리.
4. **latency**: 정상 265ms, auth 401은 166ms, mock 장애는 0ms (즉시 실패).
   timeout 경로는 mock이 즉시 raise하므로 실제 5s 하드캡 대기는 이 실험에서
   트리거되지 않음 — `JEV_CHOICE_TIMEOUT_S=5.0` 상수가 코드에 이미 반영돼 있고
   harness가 `timeout=`으로 전달하는 것을 코드 리뷰로 확인.

## 결론

스펙 필수 검증 5번(`Jev 장애 시 fallback이 정상 작동한다`) 충족.
Phase 0~2 + 런타임 통합 + Experiment F까지 스펙 필요한 검증 완료.

## 후속 제안 (필요시)

- timeout 하드캡(5s) 자체의 실측: 서버 지연 서버를 띄워 실제 대기 경로 확인 가능
  (현재 mock은 즉시 raise — 실질 위험은 낮음: harness가 5s 내 예외/응답 처리 보장)