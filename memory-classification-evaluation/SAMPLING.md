# SAMPLING.md

## Calibration Set (390)

**목표**: 어미/발화 형태 다양성 + semantic class 후보 포함 (300~500 권장).

1. **후보 풀**: KoDialogBench 193,080 / KoSGD 84,594 / KoAlpaca 49,592 (한국어 발화)
2. **어미 버킷**: 28개 종결 클래스 (~줘 ~자 ~게 ~세요 ~해 ~해요 ~합니다 ~했어 ~했다 ~했는데 ~하자 ~하지마 ~좋겠어 ~ㄴ지 ~ㄹ까 ~ㄴ가 ~냐 ~ㄴ데 ~다 ~니다 ~어 ~아 ~지 ~죠 ~네요 ~군요 ~야 ~이야)
3. **층화**: 출처 비율 KoDialogBench 45% / KoSGD 35% / KoAlpaca 20%, 어미별 최소 2개
4. **강제 보충**: 희귀 어미(줘/자/했어/좋겠어/하자/하지마/했는데/세요/해요)는 실데이터 부족 시 합성 발화로 4~6개 보충 (agent 맥락)
5. 결과: 390개 (KoDialogBench 258 / KoSGD 97 / KoAlpaca 27 / synthetic 8)
6. seed: 20260928 (고정, 재현 가능)

## Main Evaluation Set (1500)

**목표**: 1,000~3,000 권장 — 자연 분포 stratified.

1. Calibration에 사용된 ID 제외
2. 출처별 할당: KoDialogBench 675 (45%) / KoSGD 525 (35%) / KoAlpaca 300 (20%)
3. 각 출처에서 무작위 순차 추출 (rng fixed seed)
4. 결과: 1500개

## Synthetic Edge Cases (85)

**목표**: 공개 데이터셋에 없는 agent-specific 사례 (300~500 권장, 여기서는 집중 85개).

- §10 카테고리 A~H: 일회성 명령(A), 장기 instruction(B), preference(C), decision(D), error(E), learning(F), observation(G), context(H)
- §16 paraphrase: 같은 의미 다른 어미 (error 10개 변형, preference 4개 변형)
- §15 context-dependent: 문맥 없이 판단 어려운 발화
- §11 ending 의존성: 같은 어미(~줘) 다른 gold (NO_STORE / instruction)
- §17 예시: 기술/에이전트 맥락
- **gold는 직접 작성** (LLM 아님) — trusted labeling by human curation

## KoAlpaca 주의

- instruction 필드만 사용 (output 제외)
- 지시문이 "~하세요" 형태라 화자 지향이 agent가 아닌 **일반 사용자 질문**일 수 있음
- DATASET_ARTIFACT 오분류 유발 가능 (예: "시가 주어지면 미터 유형을 식별하고 설명을 제공하세요" → relationship로 잘못 gold됨)
- main set에서 KoAlpaca 비중 20%로 제한 — agent 발화와 거리감 반영

## Deduplication

- KoDialogBench: dialogue ID 기준 (파일#라인#턴)
- KoSGD: dialogue_id#turn
- KoAlpaca: instruction 텍스트 MD5 — 중복 제거 (49,592 유니크 확인)

## 원본 데이터

수정하지 않음. 추출물(JSONL)만 evaluation 디렉터리에 저장.