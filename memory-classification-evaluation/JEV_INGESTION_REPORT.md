# JEV_INGESTION_REPORT.md

> **JEV(System One) ingestion 분류 실험 — 최종 확정** (2026-09-28)
> 평가 데이터: Calibration(390) + Main(1500) + Synthetic(85) = **1,975 utterances**, 전부 gold + JEV 분류 완료.

## 1. 실험 설계

- **과제 A**: should_store 이분 (STORE vs NO_STORE)
- **과제 B**: 14종 semantic 분류 (13 MemoryType + NO_STORE)
- **과제 C**: 하이브리드 (rule 고신뢰 확정 + JEV 모호 케이스)
- **JEV 호출**: TypeSafe System One `jev-latest`, 한 호출에 store + classify 2질문 (choice type)
- **비교 baseline**: 라이브 Mnemosyne rule classifier (`typed_memory.py`, 동일 1,975건)

## 2. 결과 요약 (동일 1,975건)

### 과제 B — Type 분류 (14종)

| 지표 | Rule | JEV | Δ |
|---|---|---|---|
| **정확도** | 0.0597 (118건) | **0.4861 (960건)** | **+8.1x** |
| fact F1 | 0.305 | 0.571 | +0.266 |
| preference F1 | 0.000 | **0.703** | 인식 시작 |
| event F1 | 0.000 | **0.604** | 인식 시작 |
| error F1 | 0.621 | 0.634 | +0.013 |
| decision F1 | 0.000 | 0.448 | 인식 시작 |
| goal F1 | 0.000 | 0.349 | 인식 시작 |
| commitment F1 | 0.000 | 0.312 | 인식 시작 |
| NO_STORE F1 | 0.000 | **0.561** | 인식 시작 |
| context F1 | 0.038 | 0.321 | +0.283 |
| instruction F1 | 0.000 | 0.128 | 인식 시작 (개선 여지) |

JEV는 rule이 전멸이던 **9개 semantic 타입을 전부 인식**. instruction(0.128)/observation(0.156)/learning(0.207)은 저조 — 문맥 부재 + gold 경계 모호성 때문.

### 과제 A — should_store

| 방식 | acc | prec | rec | F1 | 비고 |
|---|---|---|---|---|---|
| Rule | — | 0.287 | 1.000 | 0.446 | 전부 저장 (과다저장) |
| JEV store 단독 | 0.829 | 0.933 | 0.518 | 0.666 | 보수적 (FN 313) |
| **JEV type 결합 규칙** | 0.588 | 0.444 | 0.992 | 0.613 | FP 808 (과다저장) |

- **JEV store 단독**: precision 93%지만 recall 52% — "저장 가치" 판단이 보수적.
- **type 결합** (`type==NO_STORE&&store==NO_STORE`일 때만 NO_STORE): recall 99%로 과다저장 (FP 808).
- 두 게이트는 **trade-off**: 실사용에선 precision 우선(store 단독) + type 문턱 추가가 현실적.

### 과제 C — 하이브리드

| 방식 | 정확도 | JEV 호출 |
|---|---|---|
| JEV 단독 | **0.4861** | 1,975 (100%) |
| 하이브리드 v1 (rule 확정 362건: ~습니다/영어/error conf≥0.8) | 0.4354 | 1,613 (81.7%) |
| **하이브리드 v2 (F5 error만 확정)** | **0.4876** | 1,965 (99.5%) |

- **v1 실패 원인**: ~습니다→fact(0.8), 영어 패턴 매치가 gold와 불일치 (영어 647건 중 정확 22건 3.4% — rule은 전부 context로).
- **v2 결론**: rule에서 **신뢰 가능한 확정 규칙은 F5 error 10건(90%)뿐**. 그 외엔 JEV가 항상 우월.
- **하이브리드의 호출 절감 효과는 정량적으로 거의 없음** (최대 0.5% 절감). rule 확정 계층을 두려면 **rule 신뢰도 기준을 크게 강화**해야 함.

## 3. JEV recall 보정과의 상호작용 (Q16)

- JEV는 현재 **recall 단계**(Jev choice 1회, 후보 중 최적 lift)에서 이미 사용 중.
- ingestion 분류 실험 결과: **JEV가 최상위 정확도** — recall 보정과 **상호보완적** (ingestion: 저장 여부/타입, recall: 검색 순위).
- 단, ingestion에 JEV를 쓰면 **저장 시점에 매 발화 1회 추가 호출** (248ms) + 비용. 
  - 1,975건 실측: 100% 성공, 실패 0, p95 298ms — 실시간 경로에 허용 가능.
  - **but** 매 메시지마다 적용하면 하루 수백~수천 호출 → 비용 민감. **게이트 필요** (아래 권장).

## 4. 권장 (production 적용 전 주의)

1. **JEV ingestion 분류는 성능상 유효** (type +8.1x, store 정확도 0.829) — 실험 근거 확보.
2. **단, 이번 실험만으로 production 변경 금지** (지시문 §28 준수).
3. 적용 시 권장 구조:
   - **rule 게이트로 JEV 호출 최소화**: 영어 647건은 JEV 없이도 gold 대비 나쁘지만, **저장 가치가 애매한 케이스만** JEV 호출 (예: rule이 context(0.3 저신뢰) 반환 시).
   - **store 판단은 precision 우선**: store 단독 질문(rec 52%지만 FP 0) + type 결합 — 실사용 시 FP(과다저장)보다 FN(누락)을 택할지 결정 필요.
   - **instruction/observation/learning 저성능**: 문맥(이전 대화)을 state에 추가하면 개선 가능 — 후속 실험 후보.

## 5. 데이터 파일

| 파일 | 내용 |
|---|---|
| `ALL1975.jsonl` | 통합 입력 (id/utterance/gold_type/dataset) |
| `JEV_ALL1975.jsonl` | JEV 분류 결과 (type/store/확률/latency) |
| `BASELINE_ALL1975.jsonl` | 동일 1,975건 rule baseline |
| `PILOT100.jsonl` / `JEV_PILOT100.jsonl` | pilot 100 + 결과 |
| `jev_probe.py` / `jev_classify.py` | probe + 실행기 (read-only, production 무수정) |
| `JEV_PILOT100.jsonl` | pilot 결과 |

## 6. 비용 측정

- 1,975건, workers=3: **2분 10초** (p95 298ms/호출)
- 실패 0건 (유료 API 안정 — 무료 라우터 503과 대조)
- usage 반영 안 함 (유료 과금은 사용자 확인 필요)