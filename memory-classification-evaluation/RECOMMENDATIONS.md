# RECOMMENDATIONS.md

> **최종 확정** — Calibration(390) + Main(1500) + Synthetic(85) = **1,975 samples**, 전부 gold annotation + live classifier baseline 완료 (2026-09-28).

## 결과 요약 (3개 셋 통합)

| 셋 | n | 정확도 | should_store precision | semantic 9종 F1 | 오분류율 |
|---|---|---|---|---|---|
| Calibration | 390 | 5.1% | 37.7% | 0.000 | 94.9% |
| **Main** | **1500** | **5.7%** | **28.7%** | **0.000** | **94.3%** |
| Synthetic | 85 | 15.3% | 84.7% | 0.000* | 84.7% |

\* synthetic은 error만 일부 인식 (F1 0.667), 나머지 semantic 타입 전부 0.000

- **통합 오분류: 1,881/1,975 = 95.2%**
- should_store recall 100% (전부 저장) — **과다저장 구조**
- Main에서 NO_STORE 1,070개 중 **878개(82%)가 context로, 192개(18%)가 fact로** 저장됨

## A. 현재 classifier가 실제로 잘 작동하는 부분

1. **영어 지향 문장**: 영어 패턴(74개)은 PREFERENCE/DECISION/EVENT 등 semantic 타입을 직접 지정. (기존 실측 828건 회귀 0)
2. **ERROR 특정 구문**: F5가 잡는 형태(`오류가 발생했어`, `버그가 생겼다`, `~실패했어`)는 error로 정확 — synthetic precision 0.90.
3. **FACT 종결형**: `~습니다`(0.8), `~다/~니다`는 안정적으로 fact 반환. 다만 과다 적용 (§B.4).
4. **결정론·저비용**: 제로 LLM 호출, 결정적 재현, 우선순위/decay/consolidation 연동 — 구조 자체 장점 유지 가치.

## B. 한국어 환경에서 명백히 취약한 부분

1. **semantic 타입 10종 전멸 (F1=0.000)**: preference/decision/commitment/goal/event/instruction/relationship/learning/observation/artifact에 대한 **한국어 패턴이 코드에 없음**. 한국어 발화는 CONTEXT/FACT/ERROR 3종으로만 분류됨.
2. **종결어미 오분류율 80~100%**: main에서 ~다 80%, 12개 어미 100% — 한국어 어미는 semantic type 정보량이 거의 0.
3. **과다저장 (False Store)**: NO_STORE 1,070개 중 전부가 13종 중 하나로 저장 (should_store precision 28.7%) — 일회성 대화가 전부 메모리에 남아 pollution.
4. **~습니다 → FACT(0.8) 과다**: 인사/감사/수긍·완료 통지(`영화 잘 보시기 바랍니다`, `모든 것 정말 감사합니다`, `차량 예약이 정상적으로 완료되었습니다`)가 fact로 — NO_STORE 192건이 fact 오분류.
5. **event/context 구분 불가**: `~습니다` 완료 통지가 event가 아닌 fact로 (PRIORITY_ERROR 5건 + RULE_ERROR 다수).

## C. 단순 rule 개선으로 해결 가능한 부분 (부분 개선)

1. **F5(ERROR) 커버리지 확장**: `에러가 또 났어`, `Docker 때문에 프로그램이 죽었어`, `이 오류는 지난번에도 발생했어`, `계속 같은 에러가 나` — F5 패턴 보강으로 error recall 개선 (synthetic에서 recall 0.529 → 목표 0.8+).
2. **~습니다 예외처리**: 인사/감사/수긍/완료통지 어휘(`감사합니다`, `알겠습니다`, `~바랍니다`, `~완료되었습니다`) → NO_STORE/context 전환. **효과 예상: False Store 192건 감소.**
3. **preference 어휘 추가**: `좋아해요`, `~면 좋겠어`, `마음에 들어`, `선호해요` → preference 키워드 (다만 어미 의존 한계로 완전 해결 불가).

**C는 전체 오분류의 ~20~25%만 커버** — 아래 D가 구조적 문제.

## D. semantic/context-aware classification (JEV) 도입 검토 근거

1. **어미 정보량 0 (정량 확정)**: main 1500에서 어미 오분류 80~100%. 규칙 추가로 해결 불가능한 **구조적 한계**.
2. **문맥 의존 발화**: `그걸로 가자`, `좋아 그렇게 해줘`, `진행해줘`, `서커스야` — 발화 단독으로 NO_STORE/decision/instruction 구분 불가. classifier는 단일 발화 입력 → 문맥 미사용.
3. **저장 판단(should_store) 계층 부재**: 13-type에는 NO_STORE가 없어 "저장 가치" 판단이 설계상 불가. 의미 판단이 필수.
4. **ontology 경계 문제**: preference vs instruction vs decision (`다음부터 이 방법은 사용하지 마` — instruction; `이 방법 때문에 문제가 생겼고 바꿨어` — learning+decision 혼합) — calibration에서 gold ambiguity 47건(12%) 확인. JEV 도입과 ontology 변경은 별개 문제로 기록.

### JEV 도입 판단 (Q15)

- **근거 충분**: 한국어에서 rule-based는 semantic 10종 표현 불가(0.000) + 저장 판단 부재 + 어미 정보량 0. JEV ingestion 실험을 진행할 **정당한 근거가 확보됨**.
- **단, 이번 실험 결과만으로 production 변경하지 않음** (지시문 §28). JEV 분류 실험은 **후속 작업**으로:
  1. 저장 여부(should_store) 판단 성능 측정 (NO_STORE 1070 vs 저장 430 이분 분류)
  2. semantic 타입 분류 성능 (13종, 문맥 포함 시)
  3. 비용: 지연/토큰 vs recall 이득, JEV recall 보정과의 상호작용
- **하이브리드 제안 (검토용)**: rule 고신뢰 확정(영어/F5/~습니다 fact) + JEV 모호 케이스/문맥 필요 발화. 단 이는 설계 제안이며 다음 단계 실험 대상.

## Q&A 최종 (지시문 §23, Main 1500 기준)

| Q | 답 |
|---|---|
| Q1. 13-type 충분한가 | 표현 자체는 가능하나 **저장 가치 판단(NO_STORE) 계층 부재**로 과다저장 불가피 |
| Q2. 가장 문제 어미 | ~세요, ~니까, ~시오, ~까요, ~가요, ~죠, ~네요, ~야, ~래요, ~게요 (100%) |
| Q3. ~줘/~자/~세요 등 구분 실패율 | 80~100% (문법-의미 대응 실패, 정량 확정) |
| Q4. PREFERENCE 규칙 | 한국어 패턴 없음 → F1 0.000 (149개 전부 context) |
| Q5. INSTRUCTION 일회성 vs 규칙 | 구분 불가 (둘 다 context) |
| Q6. DECISION 여러 어미 | 모두 context (F1 0.000) |
| Q7. F5가 오류 포착 | 부분적 (precision 0.90, recall 0.53 — synthetic) |
| Q8. ERROR/OBS/LEARNING 경계 | 구분 자체 불가 (obs/learning 한국어 패턴 없음) |
| Q9. FACT/CONTEXT 구별 | ~다/~니다 → fact, 나머지 context. ~습니다는 과다 fact (192건) |
| Q10. 장기 발화가 저가치로 | **100%** (preference 134/134, event 47/47 등 전부 context) |
| Q11. 일회성 명령이 저장됨 | **82%+** (NO_STORE 878/1070 → context, 192/1070 → fact) |
| Q12. 문맥 필요 발화 | gold ambiguity + 구조적 문맥 미사용 — 다수 (정량: calibration ambiguity 47건) |
| Q13. 단순 regex로 해결? | 부분만 (~20~25%: F5, ~습니다, preference 어휘) |
| Q14. semantic classifier 필요? | **필요** (D 참조) |
| Q15. JEV ingestion 실험 근거 | **충분** — 저장 판단 + semantic 타입 모두 현재 구조로 불가 |

## 28. 최종 4분할

- **A. 잘 작동**: 영어, F5 특정 오류 구문(precision 0.90), ~습니다 fact
- **B. 명백히 취약**: 한국어 semantic 10종 전멸(F1 0.000), 과다저장 82%+, 어미 의존 80~100%
- **C. rule 개선 가능**: F5 recall 확장, ~습니다 예외(False Store ~192건 감소), preference 어휘 — 전체의 ~20~25%
- **D. JEV 근거**: 어미 정보량 0, 문맥 미사용, 저장 판단 부재 → **semantic/context-aware 분류 실험 필수, 근거 충분**

## 실험 재현성

- seed 20260928, sample ID 보존 (CALIBRATION_SET/EVALUATION_SET/SYNTHETIC_EDGE_CASES JSONL)
- gold annotation: tokenharbor/qwen3.8-flash:free (온도 0, reasoning_effort=none, workers≤4, 503 시 재시도)
- classifier: 라이브 Hermes venv typed_memory.py (461줄, 105패턴) — read-only 호출
- 결과: BASELINE_*.jsonl 전부 보존