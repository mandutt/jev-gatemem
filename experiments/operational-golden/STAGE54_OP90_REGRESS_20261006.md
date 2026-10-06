# STAGE54 — op-90 회귀: base vs pool20 vs dual vs two_call (2026-10-06, 360콜, err 0)

> stage53에서 noans hard FP가 3구조 모두 개선(13→5~8)된 것을 확인하고,
> **op-90 전체 회귀**를 검증. 전제: 파이프라인 구조 변경 채택은 op 회귀 없음이 필수.

## 결과 (스냅샷, 시점 필터, op-90)

| 구조 | hit@1 | hit@3 | abstain | noans FP(20, stage53) |
|---|---|---|---|---|
| **base (현행)** | **79** | **80** | 3 | 13 |
| pool20 | 78 | 79 | 2 | **8** |
| dual | 77 | 78 | 6 | **7** |
| two_call | 76 | 77 | 7 | **5** |

## 종합 트레이드오프

| 구조 | noans 개선 | op hit@1 손실 | op hit@3 손실 | 정답 abstain 추가 | 판정 |
|---|---|---|---|---|---|
| pool20 | −5 | −1 | −1 | 0 | **균형 최적** (회귀는 비결정성 범위) |
| dual | −6 | −2 | −2 | +3 | op 손실 > FP 이득 |
| two_call | −8 | −3 | −3 | +4 | op 손실 > FP 이득 |

## 판정

1. **pool20만 실용 후보**: noans FP −38%에 op hit@1/3 각 −1 — ±3~5 비결정성 안이라
   **"회귀 없음"으로 볼 수 있는 유일한 구조**.
2. **dual·two_call은 기각**: noans 이득(−6~8)보다 op 손실(−2~3)·abstain 증가(+3~4)가 큼.
   특히 two_call의 winner-noul 게이트(τ=0.5)는 op 정답 일부를 abstain시켜(7건) 과다거부.
3. **최종**: 구조 변경 시 pool20(또는 현행 유지) — 단 pool20은 **hit@1 -1이 비결정성**이라
   3-run 재검증이 필요. 현행 base(79/80/FP13)가 기준선 유지도 방어 가능.
4. **IRREL(라이브 이웃형 무답)은 3구조 모두 여전히 미차단** (stage53: 0~2/17) — 기존 한계 재확인.

## raw

- `data/stage54_op90_regress.json` (4구조 × 90 = 360 레코드)
- `data/stage53_missed3.json` (noans/live 축)
- 러너: `stage54_op90_regress.py`, `stage53_missed3.py`

## 후속 (권장)

- pool20을 채택하려면 **3-run majority로 hit@1/3 동일성 확인** (비결정성 제거) — 270콜.
- 또는 현행 유지 + noans hard 방어는 포기 (라이브 IRREL이 어차피 미해결이라 실익 제한).