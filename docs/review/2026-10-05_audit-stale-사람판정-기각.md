# audit stale Tier 2 — 사람 판정 결과: 기각 확정 (2026-10-05)

## 요약

- 전체 코퍼스 파일럿(1,589행, $0.06 free 레인) → STALE 119건 (7.5%)
- 사람 판정(샘플 20건 = prob 상위 0.70~0.92): **REAL_STALE 1 (5%) / PAST_REPORT 16 (80%) / STILL_TRUE 3 (15%)**
- **precision 5% — false positive 95% → 기각**

## 판정 기준

- REAL_STALE = 지금 참고하면 틀린 답을 주는 것 (대체·폐기·옛 상태)
- PAST_REPORT = 과거 행위/완료 보고 — 기록일 뿐, 참고해도 해롭지 않음
- STILL_TRUE = 여전히 참인 사실 (시스템 오판)

## 결과

| 판정 | 건수 | 비율 |
|---|---|---|
| PAST_REPORT | 16 | 80% |
| STILL_TRUE | 3 | 15% |
| REAL_STALE | 1 | 5% |

## 기각 근거

1. **precision 5%** — prob 상위 20건(가장 자신 있는)조차 해로운 stale는 1건뿐. 전체 119건 추정 REAL_STALE ~6건. 1,589콜(≈$0.06)로 6건 찾는 것은 비효율.
2. **STILL_TRUE 15%** — demote 시 유효 메모리 유실 사고. 운영 "데이터 유실 금지" 원칙 위반.
3. **근본 원인: noul이 "과거 행위 보고"(완료 보고·이전 상태·[codex session] 시작 템플릿)를 stale로 오판** — 우리 메모리 유형(에피소드 기록 포함)과 질문 설계가 부정합.

## audit 최종 판정

- **Tier 1 (결정적 검증, 0콜)**: 유효 — env/port/db 기계 검증은 오판 불가, 155건 중 1건 실제 stale 발견. 가벼운 주기 점검 용도로만 채택 가능.
- **Tier 2 (의미적 모순 스윕, 1콜/메모리)**: **기각**.

## 산출물

- `run_audit_tier2_full.py` + `audit_tier2_full_raw.json` (1,589건 전체)
- `build_stale_review_html.py` + `stale_review.html`
- 사람 판정: `Downloads/stale_verdicts.json` (20건)

## 학습 (fit와 동일 패턴)

- 4-way 비교 프레임 "실측 → 사람 판정 대조 → 기각" 경로 재확인. JEV 자동 판정을 사람이 대조하면 precision이 낮은 기능은 구조적으로 드러난다.
- 대규모 배치 운영: free 레인 병렬 3이면 429 폭주 → **병렬 2 + 60s 드레인 + 연속 20회 자동 종료** 필수 (이번 실측에서 3회 hang 후 확립).