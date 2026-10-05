# Choice Probability 활용 실측 (stage25) + 세 AI 검토 판정 — 2026-10-06

SoT: `C:/Users/mandu/hermes-made/jev-memory-middleware/experiments/operational-golden/`
raw: `data/stage25_choice_probability.json`, 로그 `data/stage25_run3.log`

---

## 1. 배경

- 외부 AI 3종 검토(C/A/B)에서 **C AI가 "JEV choice 응답의 probabilities/confidence를 코드가 파기한다"** 고 지적.
- 실측 확인: `gateway/j1_pipeline.py::_jev_choice()`가 `answers.best.choice`의 index만 반환, `probabilities`·`confidence` 파기. **지적 정확.**

## 2. stage25: probability 로깅 (140콜, free lane 0원)

- op 90건 + noans hard 50건에 대해 head-100 excerpt로 choice 호출, **응답 전체(choice/confidence/probabilities) 저장**.
- 버그 수정 1회: 정상 경로에 `out.append(rec)` 누락 (records=[] → 수정 후 정상).
- 결과:
  - **op hit@1=69 (76.7%), hit@3=72 (80.0%)**, abstain 9~10
  - **noans 오주입 13 (26.0%), abstain 37** — 기존 head-100 baseline과 동일 (회귀 0)

## 3. abstain probability 분석 (핵심)

### op abstain 10건의 abstain_p 분포

| abstain_p | 건수 | 쿼리 | 의미 |
|---|---|---|---|
| 0.87~0.97 | 2 | shutdown(0.97), Exa(0.90) | **강한 abstain** — gold pool 밖, 정당 |
| 0.30~0.49 | 7 | 구현(0.30), gold50(0.37), 감사(0.39), 리뷰커밋(0.40), provider(0.39), S8(0.49) | **확신 없는 abstain** — top 후보와 abstain이 경합 |
| 0.73~0.79 | 1 | evidence(0.79) | 중간 |

### gold pool 내 abstain 3건의 gold probability

| 쿼리 | abstain_p | gold pos | gold_p | fallback 효과 |
|---|---|---|---|---|
| 감사 보고서 섹션 | 0.39 | pos 1 | **0.25 (=top)** | ✅ fallback 시 gold 1위 |
| gold50 기준선 | 0.37 | pos 5 | 0.10 (top 0.33) | ❌ fallback해도 gold 아님 |
| S8 시나리오 | 0.49 | pos 7 | 0.02 (top 0.34) | ❌ fallback해도 gold 아님 |

### noans abstain 37건의 abstain_p

- abstain_p < 0.5: 5건 (14%), < 0.6: 8건 (22%) — **τ fallback 시 이만큼 오주입 위험 증가**

## 4. 확률 기반 abstain fallback 시뮬레이션 (0콜)

| τ (abstain_p < τ → top lift) | op 회복 | noans 추가 오주입 위험 | 판정 |
|---|---|---|---|
| 0.4 | +1 (감사) | +3 | 순효과 마이너스 |
| 0.5 | +1 (감사) | +5 | 순효과 마이너스 |
| 0.6 | +1 (감사) | +8 | 순효과 마이너스 |

**판정: 단순 probability threshold fallback 기각** — excerpt 확장(stage22)과 동일하게 noans 오주입 비용이 gold 회복을 압도.

## 5. 세 AI 검토 최종 판정

| AI | 제안 | 판정 | 근거 |
|---|---|---|---|
| C | Choice probability/confidence 로깅 | ✅ **채택** | 파기하던 정보가 abstain 진단의 핵심. abstain_p 분포로 "확신 없는 abstain 7건" 식별 |
| C | Batched Noul + Choice hybrid | ⏸️ 보류 | 1요청 다질문 가능 여부는 API 실측 필요 (이전 "1요청 1질문" 제약과 상충) |
| C | evidence-span index | ⏸️ 보류 | 구현량 큼, offline 검증 가능 |
| B | hit@5 = 82.2% 지표 | ✅ **확정** | top-5 노출 코드와 정합. hit@3는 보수적 지표였음 |
| B | "pool 밖 5건" 이중 집계 | ✅ **지적 수용** | abstain pool밖 5건 + miss pool밖 5건 별개 (10건) |
| B | soft abstain 노출 | ⏸️ 보류 | gold top-5 3건 회복 vs noans 노출 위험 — τ와 동일 trade-off |
| B | harm-가중 재계산 (op +6/90 vs noans +7/50) | ⏸️ 보류 | u(무답 비율)·h(오주입 해로움) 추정 필요 |
| A | POOL_BUDGET 30 + 400자 메타데이터 | ⏸️ 보류 | gold 31~40위 0건 확인 (축소 안전). 단 noans 400자 오주입 미검증 |
| A | hit@1 = 74.4% | ✅ **확정** | 실사용 정직 지표. JEV 기여 +48.8pp (pool-only 25.6%) |

## 6. 확정된 지표 (0콜, 데몬 venv, op 90)

| 지표 | 값 |
|---|---|
| hit@1 (JEV winner==gold) | 67~69/90 (74.4~76.7%) |
| hit@3 | 70~72/90 (77.8~80.0%) |
| hit@5 (top-5 노출 정합) | 74/90 (82.2%) |
| abstain | 8~10 |
| noans hard FPR | 13/50 (26.0%) |

## 7. 다음 단계 후보

1. **abstain 라벨 문구 강화** (확신 없는 abstain 7건 타깃): "주제 유사하나 시점/버전/수치 불일치 시 abstain" — 50콜(noans) + op 회귀 확인
2. **C의 hybrid 검증**: 1요청에 choice+noul 동시 가능 여부 API 실측 (1콜)
3. **A의 budget 30 + 400자 메타데이터**: 140콜
4. **B의 harm-가중 재계산**: 0콜 (op/noans raw 활용)

## 8. 파일

- 러너: `stage25_choice_probability.py` (pool_ids 저장 포함)
- raw: `data/stage25_choice_probability.json` (140건, probability 포함)
- 로그: `data/stage25_run3.log`