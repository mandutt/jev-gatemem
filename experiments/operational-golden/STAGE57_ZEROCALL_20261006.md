# STAGE57 — 0콜 검증 5종 (2026-10-06, 3-AI v3 후속)

> B AI 0콜 점검 4종 + C AI v2 세 정책 + B 문형 분리 — 전부 기존 raw 재분석 (0콜).
> 원칙: stage49c human verdicts(60)를 ground truth로, stage54/56 raw로 op-90·noans를 보조.

## 1. 허브 행 집중도 — **B AI 예측 실측 확정 (가장 중요한 발견)**

- 49c 라이브 60에서 block(IRREL+PLAUS) 38건의 **pick(cands[0])이 단 3개 고유 id에 몰림**:
  - **131자 "default 프로필 규칙" 행: 32/38건 (84%)** (created 2026-09-28)
  - ADR Final 규칙: 3건, 설계 리뷰 규칙: 3건
- → **라이브 IRREL 오주입의 대부분이 "항상 1위로 떠오르는 프로필 규칙 행" 하나에서 발생**
- 함의:
  - B AI의 "상시 주입 행을 choice 후보에서 빼거나 다운웨이트" 레버가 **유효할 가능성 높음**
  - ⚠️ 단 VALID 5건의 답이 바로 그 프로필 행 (B 지적) — 단순 제거 금지
  - **별도 검증 필요**: 이 행을 제외/다운웨이트 시 block 32건 중 몇 건이 abstain/다른 행으로 바뀌는지 (0콜 시뮬 가능 — cands 순서만으로는 한계, JEV 재호출 필요할 수도)

## 2. v2 세 정책 재계산 (49c 라이브 60, cands=노출 top5 기준) — **C AI 설계 채택 근거**

| 정책 | 발동 | block 구제 | valid/yes 오차단 |
|---|---|---|---|
| winner-only | 14 | 13 | **1** (`Hermes_With_Watchdog.cmd` yes) |
| top5-any | 12 | 12 | **0** |
| winner-absent & top5-absent | 12 | 12 | **0** |

- **top5-any·winner-absent&top5-absent가 최적**: 오차단 0, 구제 12/38 block.
- C AI의 "winner-absent & top5-absent"가 "top5-any"와 동일 결과 — (교집합이 같음)
- ⚠️ 단 오차단 0의 한계: 대상 12건 기준 (0/12 → 95% 상한 ~22%) — 실트래픽 별칭 변형 리스크 유지.
- **winner-only도 13 구제 + 오차단 1** — stage51의 "winner-only 0건"과 다른 결과 (셋 차이).

## 3. rank-veto 시뮬 (B) — **정답 손실 3건으로 기각**

- op-90 base에서 choice_idx≥20 (deep pick) **6건**:
  - gold 포함 3건: KoDialogBench(rank 8)·deepseek(41)·camelai(36) → **veto 시 abstain → 정답 손실 3**
  - gold 없음 3건: WHY 2 + pi 프록시(이미 abstain) — veto 영향 없음
- **"pick rank>20 → abstain"은 op 정답 3건을 희생** — pool20과 결합해도 deepseek·camelai는 pool 밖이라 동일 손실.
- **기각**: 정답 손실 3 vs block 구제 (noans 기준 시뮬 불가 — raw에 pick rank 미저장).
- ⚠️ raw 한계: stage56 noans에 choice_idx 미저장 → noans 기준 veto 구제량은 미확인.

## 4. hit@k 노출 구조 (B/C 공통) — **k=2~5 동일, 노출 축소는 정답 손실 0**

- op-90 base choice lift 후: **hit@1 79 / hit@2 80 / hit@3 80 / hit@5 80**
- → **k=2로 줄여도 hit@2 = 80 (현행 k=5의 80과 동일)** — 상위 2개 안에 정답이 있는 경우가 80/90.
- 노이즈 관점: block 38건 × 노출 5 = 190개 무관 → k=2면 76개 (**60% 감소**).
- **A AI의 "rows[:2~3] 축소"가 op 정답 손실 0 + 무관 노출 60% 감소로 실측 지지** — 단 FP가 "노출 2~5에 정답 아닌 행"에서 발생하는 경우(abstain 무력)는 k=2도 동일 FP (정답만 1위에 있으면). **k=2 채택 시 abstain 동작은 JEV 재실험 필요** (0콜로는 hit@만 확인 — FP 감소는 미보장).

## 5. 문형 분리 (B) — **라이브 60 전부 질문형, 분리 불가**

- 49c 라이브 60은 **전부 '?' 질문형** (60/60, block 63%) — 지시문형 0건.
- u·FP를 문형별로 나눌 표본 자체가 없음. **기각 (표본 부재)**.
- 골든 noans 50은 지시문형 위주일 가능성 — 골든 vs 라이브 분포 차이의 한 요인일 수 있으나, 실측 재료 부족.

---

## 종합 판정 (0콜 검증 5종)

| 항목 | 결과 | 영향 |
|---|---|---|
| 허브 행 집중도 | **확정 (84% 한 행)** | B의 다운웨이트 레버 — 가장 유망한 신규 방향 |
| v2 세 정책 | **top5-any = winner-absent&top5-absent = 12구제·0오차단** | C 설계 채택 근거 — post-choice veto로 구현 가능 |
| rank-veto | **기각** (정답 손실 3) | pool20과 결합해도 동일 손실 |
| hit@k | **k=2 = k=5 (80)** | A의 노출 축소 실측 지지 — 단 FP 감소는 미보장 |
| 문형 분리 | 기각 (표본 부재) | — |

## 후속 (권장 순서)

1. **허브 행 다운웨이트 0콜 시뮬** — 131자 프로필 행을 choice 후보에서 제외 시 block 32건의 pick 변화 (49c raw로 시뮬 — JEV 재호출 없이는 pick 재계산 불가, 근사만)
2. **v2 post-choice veto 구현 검토** — top5-any 정책, 오차단 0 확인 후
3. **k=2 노출 실험** (JEV 재호출 필요 — abstain 동작 확인)
4. **production-exact live60 paired 3-run (360콜)** — pool20 최종 게이트 (C AI)

## raw

- 재분석: `stage49c_label_booster_input.json` + `Downloads/stage49c_label_booster_verdicts.json` (human)
- 보조: `stage54_op90_regress.json`, `stage56_full_compare.json`, `stage49d_poolinscan_input.json`
- 러너: `stage57_zerocall_checks.py`