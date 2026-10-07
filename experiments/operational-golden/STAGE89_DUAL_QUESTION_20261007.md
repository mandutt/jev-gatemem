# STAGE89 — 2질문 분리 구조 실측 (2026-10-07, 400콜, err 0, 273s)

> b-ai 제안 — 하나의 요청에서 규칙 질문 + 사실 질문 각자 choice+abstain.
> API 2질문 동시 전송은 1콜 probe로 확정 후 실측.

## 설계

- rule_q: RULE_IDS 6개 + abstain (규칙 답용 — 소후보로 abstain 유도)
- fact_q: 비규칙 상위 20개 + abstain (사실 gold 회수용)
- 결합: abstain_all(둘 다 abstain) → 빈 컨텍스트

## 결과 (op90 + noans50 + live60, base vs dual)

| 지표 | base (현행) | dual (2질문) | Δ |
|---|---|---|---|
| op hit@1 | **78**/90 | 67/90 | **-11** |
| abstain_all | 2 | 1 | — |
| noans FP | 22/50 | **19/50** | -3 |
| live block abstain (합산) | 0/38 | 0/38 | 0 |
| **live block: rule_q abstain** | — | **29/38 (76%)** | ★ |
| live block: fact_q abstain | — | 0/38 | 0 |

## 발견

1. **rule_q abstain 76% (29/38)** — 규칙 6개만 보여주니 무답에서 abstain이 살아남 (k=5 효과와 동일).
   **b-ai 가설 실측 확인**: "규칙 질문은 규칙 행만 보면 abstain 작동"
2. **fact_q는 abstain 0/38** — 20개 후보에선 abstain 안 생김 (stage84 곡선과 일치: k=10~20 abstain 붕괴)
3. **결합(abstain_all)으로는 무답 방어 0** — fact_q가 절대 abstain 안 해서
4. **op hit@1 -11 (78→67)** — fact_q 20개 후보에서 gold 회수력이 60개보다 약함
   (gold rank≤20 84/90인데도 67/84 ≈ 80% 회수 — JEV가 20개에서 고르는 능력이 60개보다 낮음)

## 함의

- "abstain 살리기 + 사실 회수 분리" **원리는 검증** (rule_q abstain 76%)
- 그러나 "fact_q 20개 + abstain_all 결합"은 **무답 방어 0 + op -11** — 구조 개선 필요
- **다음 변형 후보**:
  1. rule_q abstain이면 fact_q에 **60개 전체**를 주는 2단 구조 (조건부)
  2. fact_q 후보 20→10 (abstain 유도) — 단 op 회수 추가 하락 위험
  3. 결합 규칙을 rule abstain 우선 (rule abstain → 빈 컨텍스트, fact 무시) — rule 오차단 위험
  4. rule_q만 abstain 여부 보고, fact_q는 항상 실행 — "rule abstain이면 규칙 노출만 제거" (사실은 계속)

## raw

- `data/stage89_dual_question.json` (400 레코드)
- 러너: `stage89_dual_question.py`
- 로그: `data/stage89_run.log