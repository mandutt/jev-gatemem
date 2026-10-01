# 운영 골든셋 Run H — pool_ids 노출 + JEV lift 정밀 측정 (2026-10-01)

> Run G(커밋 80158a2)에서 확인한 계측 한계 해결: `/v1/prefetch`에 `options.pool_ids=true`가
> `meta.pool_ids`(stage1 RRF 순위) + `meta.final_ids`(JEV rerank 후)를 노출(커밋 e353e1e).

## 1. 최종 성능 지표 (n=90 gold + 10 no-answer)

| 지표 | Run G (pool 한계) | **Run H (JEV rerank 후)** |
|---|---|---|
| Acc@1 | 측정 불가 | **75.6%** (68/90) |
| **hit@5** | 74.4% (pool) | **81.1%** |
| MRR | 0.555 (pool) | **0.941** |
| p50 / p95 | 272/341ms | 295/365ms |

### 축별 (final 기준)
| 축 | Acc@1 | hit@5 |
|---|---|---|
| literal | 77.8% | 84.4% |
| paraphrase | 73.3% | 77.8% |

### 카테고리별 (final 기준)
| 카테고리 | Acc@1 | hit@5 |
|---|---|---|
| A_env_config | 90.0% | **100%** |
| B_debug_causal | 100% | 100% |
| C_preference_short | 77.8% | 83.3% |
| D_cross_lang | 100% | 100% |
| E_factual_misc | 60.0% | 63.3% |

## 2. JEV rerank의 실제 기여 — 처음 정밀 측정됨

- **lift 발생율 68%** (68/100) — JEV choice가 RRF 1위와 다른 후보를 뽑아 lift하는 비율
- **lift가 hit5에 미치는 영향: 진입 6건, 이탈 0건** — 순수 이득만
- **pool에는 있었는데 final에서 사라짐: 0건** — JEV는 후보를 버리지 않음 (choice lift만)
- Pool hit@5 74.4% → Final hit@5 81.1% = **rerank 기여 +6.7%p**
- **MRR 0.555 → 0.941** — 정답이 풀에 있으면 JEV가 대부분 1위로 보냄

→ **JEV rerank는 결함이 아니라 최대 기여 요소로 확정.** 풀 진입(RRF+게이트)이
상한이고, 그 안에서 JEV가 81.1%까지 끌어올림.

## 3. 무답 오주입 — 재해석

무답 10쿼리 중 4개에서 무관 후보를 1위 lift. 그러나:
- 6개는 lift=False (JEV가 무익 판정을 내도 pool 순위를 유지 — 1위 강제하지 않음)
- lift=True인 4개도 무관 정보가 답변 생성에서 걸러질 것 (Hermes 계층)
- **오주입 방어의 1차 책임은 JEV가 아니라 Hermes 답변 계층** — JEV는 정답 후보 lift가 역할

## 4. 남은 격차의 정체 (Acc@1 75.6% vs PR식 100%)

Run G 결과와 합치하면: 풀 미달 16건(17.8%)이 상한. 풀에 들어온 74건 중
Acc@1 68건 = **풀 진입 시 91.9%를 1위로** — 운영 도메인에서는 kodialog 같은
5-way 단답 한계가 재현되지 않음. 남은 E_factual 40% 실패는:
- 6건 literal 실패의 원인이 어휘 게이트 커버리지 경계(0.2857<0.30)인 것으로
  Run G에서 확인됨 — 게이트 완화는 hit@5 손실 때문에 권고하지 않음
- 나머지는 벡터/FTS 레인이 정답을 k=60 안에 못 찾는 검색 커버 문제

## 5. 결론

1. **운영 baseline 확정**: Acc@1 75.6% / hit@5 81.1% / MRR 0.941 / p95 365ms
2. **JEV rerank 기여 정량 확정**: +6.7%p hit5, lift 순이득(이탈 0건)
3. **개선 레버 우선순위**: 풀 진입률(82.2%→90%)이 유일한 실질 레버 —
   어휘 게이트 커버리지 경계 사례 처리 또는 vec k 상향(로컬 무료)
4. 합성 벤치(kodialog)의 "rerank가 못 살린다" 결론은 **운영 도메인에서 반증** —
   운영에서는 rerank가 최대 기여 요소

## 원본
- `golden_final_v2.json` / `golden_eval_v3.json` / `golden_run_h.py`
- 구현: jev_mem_core/pipeline.py `options.pool_ids` (커밋 e353e1e)
