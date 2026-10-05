# 운영 데몬 재시작 기록 — [ASSISTANT] prefetch 제외 해제 반영

- **날짜/시각**: 2026-10-05 17:19~17:21 (KST)
- **커밋**: `ffb2ca5` (gateway/j1_pipeline.py `_PREFETCH_EXCLUDED_PREFIXES = ("[ASSISTANT]",)` → `()`)
- **실측 근거**: STAGE1_LONGMEM_PROBE.md 실측 9 — op-90 회귀 0, noans 오주입 0, 장문 gold 1/19→8/19

## 수행 절차

1. 프로세스 스냅샷: 부모 27116 → 자식(리슨) 16164, 포트 47821
2. 정지: 자식→부모 순 `Stop-Process -Force` → pythonw 0개 확인 (CLEAN)
3. 재스폰: `terminal(background=true)` → `pythonw.exe -m jev_mem_core --serve` (pid 19656 → 트리 2368→20460)
4. 검증:
   - `/v1/status` → `status: ready`, embedding `bench/bekko-a8m`
   - `/v1/prefetch` 정상 응답
   - **라이브 게이트 통과 변화**: 동일 쿼리 "S4 임베딩 마이그레이션(bekko-a8m) 이후..." 재시작 전 `passed 48`(gate trace 17:09:06) → 재시작 후 같은 류 쿼리 `pool 116 → passed 85` (17:21:41)
   - context 길이: 20자(과거 무관) → 4,303자 ([ASSISTANT] 행 유입)

## 반영 확인

- trace 로그(`AppData/Local/hermes/logs/jev_trace.log`)의 `gate` 라인 passed 증가로 새 코드 반영 확인
- 이 시점부터 [ASSISTANT] 행이 prefetch 후보에 포함됨

## 관찰 계획 (shadow/enforcement)

- [ASSISTANT] 행 유입으로 인한 prefetch 품질 변화를 shadow 배치(`query_log`/`shadow_log`)로 추적
- 경고선: noans 오주입 증가 / op-90 지표 회귀 시 롤백 (커밋 `89282ee`로 revert 가능)