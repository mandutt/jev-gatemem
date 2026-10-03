# Fail-open ③ 재판정 — dry-run 완료 (2026-10-03)

## 상태: dry-run 완료 (DB 미변경). apply는 승인 대기.

## 실행 요약

| 항목 | 값 |
|---|---|
| JEV 호출 | 64회 (user 32 + assistant 32) |
| 소요 | 14.8초 (latency 평균 ~230ms) |
| **판정** | **keep=48, skip=16, fail=0** (strict-fail 0) |
| 비용 | 64회 × ~1.1K in / ~0.1K out → ~76K 토큰 (< 1¢) |

## 중간 장애와 해결

- 1차 시도: **전부 strict-fail (http-403)** — 원인: 터미널 셸 env의 `TYPESAFE_API_KEY`가 **이전 키**(hash `8f66dc22...`)를 물고 있었음 (HKCU 현재 키 `e925bdd...`와 불일치, 데몬은 새 키로 정상 동작)
- 해결: 스크립트가 **HKCU 레지스트리 키를 우선 로드**하도록 수정 (`_resolve_api_key()`) → 2차 시도 64/64 성공
- **교훈**: 셸 env는 이전 세션 값이 남을 수 있음 — 데몬과 동일 키 보장은 HKCU 읽기가 정석

## SKIP 후보 16건 (사용자 눈 확인용)

모두 합리적 SKIP (진행 확인·상태 알림·단발 질문):
1. [user] Qwen3.5 0.8B 모델 평가? (단발 질문)
2. [asst] No reply 경고 (tempcombo 미응답)
3. [user] "좋아 진행해줘" (진행 지시)
4. [asst] a8m baseline 분리 실행 중 (context)
5. [user] "9router를 실행해줘" (명령)
6. [asst] 9router 실행 완료 알림 (context)
7. [user] "좋아 실험해볼래?" (진행 지시)
8. [user] 토큰 소모 질문 (단발)
9. [user] "좋아 추가해줘" (진행 지시)
10. [asst] 모델 시작 대기 알림 (context)
11. [user] 다른 AI 문의 방법 (단발)
12. [user] 임베딩 모델 jina-v5 질문 (단발)
13. [user] jina-v5-small 양자화 질문 (단발)
14. [user] "좋아 돌려봐줘" (진행 지시)
15. [asst] GLiNER 평가 백그라운드 알림 (context)
16. [user] jev 키 변경 방법 (단발 — 오늘 이미 처리됨)

## KEEP 48건 — 정상 승격 후보 (예시)
- 실험 결과·판정·문서화 내용 등 저장 가치 있는 대화

## 다음 단계 (승인 대기)
- [ ] **SKIP 16건**: soft-delete (아카이브) — 삭제 전 DB 스냅샷 + 사용자 확인
- [ ] **KEEP 48건**: 마커를 `rejudged:keep`로 전환 (감사 이력 보존) — 비파괴
- [ ] rollback: 백업 JSON으로 복원 가능

## 도구
- `tools/jed_failopen_rejudge.py` (`--apply`로 실행 시 DB 반영; dry-run 기본)
- 결과: `failopen_rejudge_result.json` (64건, verdict/reason/latency 기록)