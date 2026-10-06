# STAGE56 — base vs pool20 풀 비교 (같은 세션 3-run paired, 2026-10-06, 840콜, err 0)

> stage54(1-run)/stage55(3-run)는 **세션이 달라 비결정성이 섞였다** (base 79/80 vs pool20 78/79 의 -1).
> 같은 세션에서 두 구조를 각 3-run으로 paired 비교해 확정.

## 결과 (op-90 + noans-50, 각 구조 3-run)

| 구조 | hit@1 (3-run) | hit@3 | abstain | noans FP (3-run) |
|---|---|---|---|---|
| base | 78 / 78 / 78 | 79 / 79 / 79 | 2·2·3 | 21 / 22 / 21 (평균 **21.3**) |
| pool20 | 78 / 78 / 78 | 79 / 79 / 79 | 2·2·2 | 13 / 13 / 13 (평균 **13.0**) |

## 핵심 발견

1. **op hit@1/3: 두 구조 완전 동일 (78/79)** — stage54 base 1-run의 79/80은 세션 잡음.
   **pool20의 "op 회귀 -1"은 착시** — 같은 세션에서는 회귀 0.
2. **noans FP: 21.3 → 13.0 (−8.3, −39%)** — 같은 세션에서 확고한 개선.
   - 참고: stage53 noans 샘플 20의 base 13은 이번 50건 전체 21.3과 다른 값 — 셋 의존성 재확인.
3. **쿼리별 majority 대조: 차이 4건뿐, 2:2 상쇄**:
   - pool20 개선 2 (#58 KoDialogBench, #72 pi 프록시)
   - pool20 손실 2 (#80 deepseek 장문, #87 camelai-serial-proxy)
   - → **체계적 손실 없음**, 무작위 변동 수준.

## 최종 판정 — pool20 채택 근거 확정

- **op 회귀 0 + noans FP −39%** — 트레이드오프가 아닌 **일방 개선**.
- h(해로움 가중치) 계산 불필요 (정답 손실이 없으므로).
- 단순화 부수 효과: JEV criteria 수 61→21 → **토큰 ~35% 절감 + latency 감소** (A AI 원래 제안 이유).

## 채택 시 반영 사항

- `gateway/j1_pipeline.py`: `POOL_BUDGET = 60 → 20`
- 릴리스 게이트(§protocol): base와 동일 세션 회귀 확인 후 반영
- 주의: retrieval ceiling에는 영향 없음 (답이 pool 20 안에 있는 케이스만 대상 — stage50c/d에서
  실운영 pool 답 rank 1~3 확인, pool20 안전)

## raw

- `data/stage56_full_compare.json` (2구조 × 3-run × 140 = 840 레코드)
- 러너: `stage56_full_compare.py`
- 로그: `data/stage56_run.log` (err 0, 429 0)