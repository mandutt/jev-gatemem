# Winner Gate full-text 재실험 — excerpt 80자 vs 원문 전문 판정 비교 (2026-10-04)

> 스크립트: `experiments/operational-golden/run_exp7g_fulltext_gate.py` (43콜 FREE)
> 배경: 사용자 지적 — "100자 내외 excerpt로 사람도 판단 어려웠는데 게이트도 같은 한계 아닌가?"
>        → 동일 43건을 **원문 전문**으로 게이트 재판정, excerpt 판정과 비교.

---

## 1. 판정 변화 (43건)

| 변화 | 건수 |
|---|---|
| **CHANGED (NO → YES)** | **6건** |
| same | 37건 |
| err | 0건 |

변경된 6건: `9f04ed2c`, `1cef4743`, `d28786a0`, `09547ea4`, `0ea67a3b`, `5e8516d6` — 전부 **사람 VALID였던 케이스** (잘린 꼬리에 답이 있었음)

**→ excerpt 절단은 게이트 성능을 실제로 악화시킴** (6건 오탐 추가)

## 2. full-text 게이트 vs 사람 판정 (최종)

| 조건 | 사람 VALID 중 YES (보존) | 사람 PLAUS 중 YES (누출) |
|---|---|---|
| LGO | 19/32 (59%) | **0/5 (0%)** |
| noans | 0/5 (0%) | 0/1 (0%) |

**PLAUS 누출 0건** — full-text 게이트는 해로운 오주입을 완벽히 차단

## 3. excerpt vs full-text 과다거부 비교

| | excerpt (80자) | full-text |
|---|---|---|
| LGO VALID 차단 | 19 | **13** |
| noans VALID 차단 | 5 | **5** (변화 없음) |
| 합계 | 24 | **18** (-6) |

→ full-text로 **과다거부 24→18건 (-25%)**. 그러나 **noans 5건은 여전히 전부 차단** — noans는 점수가 낮아서가 아니라 **게이트가 "직접 답 아님"으로 보는** 문제.

## 4. 핵심 발견

1. **excerpt 절단 = 실측으로 악영향** → 프로덕션 `EXCERPT_LIMIT=120`도 재검토 필요 (게이트 전용으로는 상향 필수)
2. **full-text 게이트의 PLAUS 차단은 완벽** (0/6 누출) — 게이트 자체는 강력
3. **그러나 VALID 차단 18건이 여전히 존재** → 단독 게이트는 운영 hit@3를 크게 깎음 (보류)
4. **noans VALID 5건의 "선택된 메모리"가 pointwise top1일 가능성** — exp7d는 choice 선택 id 미저장, `top1_excerpt`는 pointwise top1. exp7f가 이걸 사용해 **게이트 판정 대상이 어긋났을 수 있음** (noans 6건 = choice 오주입이었는지도 재확인 필요)

## 5. 권고

- **게이트는 full-text 기준으로 재설계** (excerpt 사용 금지, `EXCERPT_LIMIT` 상향 또는 게이트 전용 full 전달)
- **단독 게이트 abstain은 부적합** — 이전 R2(gateNO+score<0.7)와 결합 시:
  * full-text 게이트 + score<0.7 → abstain 조합을 **오프라인 재시뮬레이션** (0콜)
- **noans 6건의 선택 대상 재검증** — exp7d의 choice id 복원 (후보 로그 재구성) 또는 원본 API 응답 확인

---

*실행: 2026-10-04 · 43콜 FREE · 저장: exp7g_gate_fulltext_raw.json*