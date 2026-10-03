# Fail-open 실측 ①② — 식별·태깅·본문 검증 (2026-10-03)

## 상태: ① ② 완료 (JEV 호출 0회, 비용 0원)

## ① 식별 + 백필 태깅 (완료)

- 대상: `ingest_ledger.status='stored'` + `decisions reason ∈ {http-402, http-403}` (2026-10-02~03)
- 결과: **32턴 / 64개 메모리 row** 태깅 완료
  - `fail_open:http-402` 40건, `fail_open:http-403` 24건
  - working_memory 실존 64/64, 사전 태깅 0건 → 전부 신규
- **백업**: `%LOCALAPPDATA%\hermes\cache\scratch\failopen_tag_backup.json` (복원용, 64건 + 기존 meta)
- 도구: `tools/jed_failopen_tag.py` (`--apply` 전 dry-run 기본, idempotent)

## ② 저장 본문 == 판정 입력 검증 (완료)

| 항목 | 결과 |
|---|---|
| `[USER]`/`[ASSISTANT]` 프리픽스 | 64/64 정상 |
| redaction 상태 (재적용 무변화) | 64/64 — 저장본이 곧 sanitized gate 입력 |
| 1500자 초과 (gate truncation) | 19건 (최대 24,021자) |
| 앞 1500자 내 redaction 흔적 | 1건 |

### 결론
- **B-AI 지적 확인: 저장 본문으로 재판정 가능 → P2(원문 별도 보존) 불필요**
- 재판정 시 **저장본 전체를 gate에 그대로 전달**하면 gate가 1500자 truncation 적용 → 원래 판정과 동일한 입력 재현
- (주의) 저장본을 `[:1500]`으로 먼저 자르면 안 됨 — redaction으로 잘리는 지점이 달라질 수 있음 (1건 확인)

## 도구
- `tools/jed_failopen_tag.py` — 태깅 (dry-run 기본)
- `tools/jed_failopen_compare.py` — 본문 비교 검증

## 다음 단계 (미진행, 승인 대기)
- ③ 재판정: JEV 호출 ~64회 (비용 <1센트), strict 모드 (실패 시 예외·행 불변), dry-run → SKIP 후보 눈 확인 → soft-delete
- 백필 태깅 rollback: 백업 JSON에서 metadata 복원