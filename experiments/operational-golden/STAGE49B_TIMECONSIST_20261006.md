# stage49b: 시점 일관 리플레이 — 3조건 × 3-run (2026-10-06, 540콜)

> B AI 지식에 따라 stage48의 측정 유효성 의심 3가지를 통제한 재실측.

## 설계

- **시점 필터**: lane 수집 후 `created_at < 2026-10-05`만 후보 (자기참조 제거 — wm 135행/7.4% 배제)
- **3조건**: cur(현행 라벨+win300→150) / head100(쿼리 윈도우 없이 head-100) / imp(improved 라벨)
- **3-run**, pool 쿼리당 1회 사전 구성, 60×3×3 = 540콜, err 0
- 스냅샷: `mnemosyne_snapshot_20261006.db`, 러너 `stage49b_timeconsist.py`

## 결과

| cond | no(22) abstain (run별) | yes(35) abstain | abstain_p median/max | >0.3 |
|---|---|---|---|---|
| cur | 0 / 0 / 0 | 0 / 0 / 0 | 0.00 / 0.17 | 0건 |
| head100 | 0 / 0 / 0 | 0 / 0 / 0 | 0.01 / 0.17 | 0건 |
| imp | 0 / 0 / 0 | 0 / 0 / 0 | 0.01 / 0.24 | 0건 |

- 시점 필터 후 pool: median 60, min 25 (커먼 후보 유지 — 실험 유효)

## 판정 — B AI 의심 3가지 모두 기각, abstain 무력 확정

| 가설 | 결과 |
|---|---|
| ① 자기참조 누수 (B) | **기각** — 135행 제거 후에도 abstain 0. stage49a 복제 검사 0건과 일치 |
| ② win-300 증폭 (B) | **기각** — head100(윈도우 없음)에서도 abstain 0. excerpt가 원인 아님 |
| ③ 라벨 문구 무력 (A/C) | **재확인** — imp도 abstain 0 |

**→ stage48 "abstain 0/60"은 측정 오염이 아닌 시스템 실재로 최종 확정.**
원인은 C AI 구조 진단: **closed-set Choice(61-option softmax)에서 abstain 라벨은
calibrated answerability가 아니라 상대 경쟁의 잔여 확률** — 유사 이웃이 1개만 있어도
확률 질량이 후보 쪽으로 몰려 abstain_p가 0에 고정됨.

## 파생 결론

1. **soft gate τ(0.3)는 라이브에서 dead code 확정** — abstain_p max 0.24 전조건 공통.
   τ 조정 실험(0.1/0.05)은 정답까지 대거 걸릴 뿐 의미 없음 → 중단.
2. **해법은 "JEV가 abstain을 선택하게 만들기"가 아니라 "별도 answerability 신호"** —
   C AI 설계(winner-Noul soft risk / Noul top30 병행)가 다음 실험으로 확정.
3. A AI retrieval floor(0.25 컷)는 stage49a에서 기각됨 (no/yes 분리 불가).
4. 라이브 60은 이후 회귀 검증 셋으로 고정 (A AI 릴리스 게이트 제안 채택).

## 다음 단계 (3종 AI 공통)

- 라벨 보강: no 22건 해로움(VALID/PLAUS/IRREL) + yes 35건 top-5 정답 포함 여부
- Noul answerability 실험 (stage50)

## raw
- `data/stage49b_timeconsist.json` (9 runs × 60)
- `data/stage49b_pool_sizes.json`
- 전제: `STAGE49A_LEAK_DIAGNOSIS_20261006.md`
