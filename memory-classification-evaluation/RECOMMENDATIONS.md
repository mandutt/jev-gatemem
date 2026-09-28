# RECOMMENDATIONS.md

> 상태: **초안** — Calibration(390) + Synthetic(85) 확정 기준.
> Main evaluation(1500) gold annotation 완료 후 최종 갱신 예정 (2026-09-28).

## A. 현재 classifier가 실제로 잘 작동하는 부분

1. **영어 지향 문장**: 영어 패턴(74개)은 PREFERENCE/DECISION/EVENT 등 semantic 타입을 직접 지정 — 영어 발화는 타입 분류가 작동 (이번 평가의 한국어 발화 밖, 다만 기존 실측 828건에서 회귀 0 확인됨).
2. **ERROR: 특정 오류 구문은 정확** — F5가 잡는 형태 (`오류가 발생했어`, `버그가 생겼다`, `~실패했어`)는 error로 정확. Synthetic에서 error precision 0.90.
3. **FACT: 명사형/형용사형 종결** — `~다/~니다`(특히 `~습니다` 0.8)는 안정적으로 fact 반환 (`비용은 3,650,000달러입니다` → fact ✓). 다만 과다 적용됨 (§B 참조).
4. **actionability**: 결정적 규칙, 제로 LLM 비용, 결정론적 재현 — 이 구조 자체의 장점은 유지 가치 있음.

## B. 한국어 환경에서 명백히 취약한 부분

1. **semantic 타입 9종 전멸**: preference/decision/commitment/goal/event/instruction/relationship/learning/observation에 대한 한국어 패턴이 **코드에 존재하지 않음** → calibration에서 해당 타입 전부 F1=0.000. 한국어 발화는 CONTEXT/FACT/ERROR 3종으로만 분류됨.
2. **종결어미 오분류율 75~100%**: 모든 한국어 어미(~줘/~세요/~좋겠어/~했어/~다...)가 semantic type을 대표하지 못함. 최선 ~다도 75% 오분류.
3. **과다저장 (False Store)**: NO_STORE 243개 중 216개(89%)가 context로 저장 — 일회성 대화가 전부 메모리에 남음. should_store precision 37.7%.
4. **~습니다 → FACT(0.8) 과다 적용**: 인사/감사/수긍(`좋은 하루 보내시기 바랍니다`, `알겠습니다`)이 fact로 잘못 저장. 격식 어미가 fact를 오버라이드.

## C. 단순 rule 개선으로 해결 가능한 부분

1. **F5(ERROR) 커버리지 확장**: `에러가 또 났어`, `Docker 때문에 프로그램이 죽었어`, `이 오류는 지난번에도 발생했어`, `계속 같은 에러가 나` — F5 패턴 보강으로 error recall 개선 가능 (synthetic에서 error recall 0.529).
2. **~습니다 한정**: 인사/수긍 감지(`감사합니다`, `알겠습니다`, `좋은 하루 보내시기 바랍니다`) → NO_STORE/context 전환 가능.
3. **일부 preference 어휘**: `좋아해요`, `~면 좋겠어`, `마음에 들어` → preference 키워드 추가 (다만 C.4 한계로 완전 해결 불가).

**단, C.1~3은 부분 개선일 뿐** — 아래 D가 구조적 문제임.

## D. semantic/context-aware classification (JEV) 도입을 검토할 근거

1. **동일 어미 → 다른 의미 비율 75~100%** (§11): 한국어 종결어미는 semantic type의 **정보량이 거의 0**이다. rule 추가로 해결 불가능한 구조적 한계.
2. **문맥 의존 발화 다수**: `그걸로 가자`, `좋아 그렇게 해줘`, `진행해줘` — 발화 단독으로 NO_STORE/decision/instruction을 구분 불가. classifier는 입력이 단일 발화라 문맥 미사용.
3. **NO_STORE 판단 자체가 없음**: 현재 13-type에는 NO_STORE가 없어 "저장 가치" 판단 계층이 부재. 이는 rule로는 **설계상 불가능** (의미 판단 필요).
4. **ontology 경계 문제**: preference vs instruction vs decision (`다음부터 이 방법은 사용하지 마` — instruction; `이 방법 때문에 문제가 생겼고 바꿨어` — learning+decision 혼합) — 사람도 ambiguity 표기한 케이스 47건(12%).

### 결론 (Q15)

- **JEV ingestion 분류 실험 진행 근거 충분**: 한국어에서 rule-based는 semantic 타입 9종을 아예 표현 못 하고(0.000), 저장 판단도 없음. JEV를 저장 단계에서 분류기로 쓸 경우 최소한 저장 여부(should_store) 판단은 가능할 것으로 기대.
- **단, JEV 도입 전에** (1) 13-type ontology가 agent utterance에 적합한지 (NO_STORE 계층 분리) (2) JEV 분류 비용(지연/토큰)과 recall 보정과의 상호작용을 별도 실험으로 검증 필요.
- **하이브리드 제안**: rule(빠른 소거/확정) + JEV(모호 케이스/문맥 필요 발화) — 단 이번 실험은 baseline만 측정했으므로, JEV 분류 실험은 **후속 작업**으로 명시.

## Q&A 요약 (지시문 §23)

| Q | 답 |
|---|---|
| Q1. 13-type 충분한가 | 표현 자체는 가능하나, **저장 가치 판단이 없어** NO_STORE가 빠진 ontology로는 과다저장 불가피 |
| Q2. 가장 문제 어미 | ~세요, ~줘, ~좋겠어, ~했어, ~네요, ~죠 (100% 오분류) |
| Q3. ~줘/~자/~세요 등 구분 실패율 | 75~100% (문법-의미 대응 실패) |
| Q4. PREFERENCE 규칙 | **한국어 패턴 없음** → F1 0.000 |
| Q5. INSTRUCTION 일회성 vs 규칙 | 구분 불가 (둘 다 context) |
| Q6. DECISION 여러 어미 | 모두 context (F1 0.000) |
| Q7. F5가 오류 포착 | 부분적 (precision 0.90, recall 0.53) |
| Q8. ERROR/OBS/LEARNING 경계 | 구분 자체가 불가 (obs/learning 한국어 패턴 없음) |
| Q9. FACT/CONTEXT 구별 | ~다/~니다 → fact 편향, 나머지 context. ~습니다는 과다 fact |
| Q10. 장기 발화가 NO_STORE/CONTEXT로 | **100%** (preference/decision 등이 전부 context로) |
| Q11. 일회성 명령이 저장됨 | **89%** (NO_STORE 216/243 → context) |
| Q12. 문맥 필요 발화 비율 | gold ambiguity 47/390 (12%) + 그 외 다수 |
| Q13. 단순 regex로 해결 가능? | 부분만 (F5, ~습니다). semantic 9종은 규칙 추가로 불가 |
| Q14. semantic classifier 필요? | **필요** (D 참조) |
| Q15. JEV ingestion 실험 근거 | **충분** (저장 판단 + semantic 타입 모두 현재 구조로 불가) |

## 28. 최종 4분할 (Calibration 기준, Main 확정 후 갱신)

- **A. 잘 작동**: 영어, F5 특정 오류 구문, ~습니다 fact
- **B. 명백히 취약**: 한국어 semantic 타입 전멸, 과다저장 89%, 어미 의존 100%
- **C. rule 개선 가능**: F5 recall, ~습니다 예외, 일부 preference 키워드
- **D. JEV 근거**: 어미 정보량 0, 문맥 필요 12%+, 저장 판단 부재 → semantic 분류 실험 필수