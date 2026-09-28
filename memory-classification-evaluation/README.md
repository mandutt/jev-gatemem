# Mnemosyne 한국어 Agent Utterance Memory Classification 검증

## 목적

현재 Mnemosyne Memory + JEV recall 보정 플러그인의 **deterministic memory-type classifier**가 실제 한국어 에이전트 사용 상황에서 충분히 작동하는지 **측정·오류 분석**한다. 코드는 수정하지 않는다 (baseline 고정, 별도 보고서에 기록).

## 절대 변경하지 않는 것

- Mnemosyne core, 저장 schema, plugin 동작 코드, Hermes core
- JEV integration/recall 로직, 13개 MemoryType 정의, priority/decay/consolidation 정책, 한국어 regex/어미 규칙

## 평가 대상 classifier (실측)

- **경로**: `C:\Users\mandu\AppData\Local\hermes\installs\315db7b763fb0d0a\environments\746564964b1042b79add42260378503b\venv\Lib\site-packages\mnemosyne\core\typed_memory.py` (461줄, mnemosyne 3.15.1)
- **패턴 구성**: `TYPE_PATTERNS = _EN_PATTERNS(영어 40+) + _KO_PATTERNS(한국어 24) + F5_PATTERNS(한글 ERROR 6)` — 총 105개
- **한국어 패턴 24개**:
  - `_KO_QUESTION` (6): ~ㄴ지, ~ㄹ까, ~ㄴ가, ~냐/~나, ~ㄴ데, ~ㄹ게 → CONTEXT
  - `_KO_REQUEST` (5): ~줘, ~자, ~게, ~세요, ~었세요 → CONTEXT
  - `_KO_STATEMENT` (11): ~ㅆ다, ~ㅂ니다 등 → FACT
  - `_KO_DEFAULT` (2): 한글 폴백 → CONTEXT(0.30), ~어/~아/~지/~죠/~네요/~군요/~야/~이야 → CONTEXT(0.55)
- **F5_PATTERNS** (6): `오류|에러|버그)(가|를|는|은|도)?\s*(발생했|...` → ERROR (conf 0.70~0.75)
- **스코어**: `confidence * (1.0 + 0.1 * MemoryType.index)` — CONTEXT(인덱스 8)가 배율 1.8로 우세
- **폴백**: 단어<5 → FACT(0.3, default_short), ≥5 → CONTEXT(0.3, default_long)
- **중요**: 영어 PREFERENCE/DECISION/EVENT 등 패턴은 한글에 대응이 **없음** → 한국어는 CONTEXT/FACT/ERROR 3종만 반환 가능

## 실행 순서 (지시문 §26)

| 단계 | 상태 | 산출물 |
|---|---|---|
| 1. classifier 조사 | ✅ | harness.py, 위 요약 |
| 2~3. 데이터셋 탐색 | ✅ | DATASET_INFO.md |
| 4. calibration 구축 | ✅ | CALIBRATION_SET.jsonl (390) |
| 5. gold annotation | ✅ | GOLD_CALIBRATION_ANN1.jsonl (390) |
| 6. calibration 분석 | ✅ | METRICS.md, ERROR_ANALYSIS.md |
| 7. main evaluation 구축 | ✅ | EVALUATION_SET.jsonl (1500) |
| 8. main gold annotation | 🔄 진행 중 | GOLD_EVAL_ANN1.jsonl |
| 9. baseline 실행 | ✅ (cal) | BASELINE_CALIBRATION.jsonl (+EVAL 예정) |
| 10~11. metrics/confusion | ✅ (cal) | METRICS.md, CONFUSION_MATRIX.csv |
| 12. ending별 오류 | ✅ (cal) | ERROR_ANALYSIS.md |
| 13~14. NO_STORE FP/FN | ✅ (cal) | REPRESENTATIVE_CASES.md |
| 15. synthetic edge-case | ✅ | SYNTHETIC_EDGE_CASES.jsonl (85), BASELINE_SYNTHETIC.jsonl |
| 16. JEV 분리 기록 | 📋 | ingestion/recall 분리 기록 (실행 구조상 JEV 미사용) |
| 17~19. taxonomy/분석/보고 | 🔄 | ERROR_ANALYSIS.md → RECOMMENDATIONS.md |

## 핵심 파일

```
memory-classification-evaluation/
├── README.md              ← 본 파일
├── DATASET_INFO.md        ← 3개 데이터셋 구조
├── SAMPLING.md            ← 샘플링 방법
├── CALIBRATION_SET.jsonl  ← 390 (어미 층화 + 강제 보충 + 합성 8)
├── GOLD_CALIBRATION_ANN1.jsonl ← LLM gold 390
├── EVALUATION_SET.jsonl   ← 1500 (stratified)
├── BASELINE_CALIBRATION.jsonl  ← classifier 실측
├── BASELINE_SYNTHETIC.jsonl    ← synthetic 실측
├── SYNTHETIC_EDGE_CASES.jsonl  ← 85 (직접 gold)
├── METRICS.md             ← 정량 지표
├── CONFUSION_MATRIX.csv   ← 혼동 행렬
├── ERROR_ANALYSIS.md      ← 오류 taxonomy
├── REPRESENTATIVE_CASES.md ← FP/FN 사례
├── RECOMMENDATIONS.md     ← (예정) 권고
├── harness.py             ← 라이브 classifier import (read-only)
├── annotate_gold.py       ← LLM gold annotation (tokenharbor/qwen3.8-flash:free)
├── run_baseline.py        ← baseline 실행기
├── compute_metrics.py     ← 지표 계산기
├── analyze_errors.py      ← 오류 분석기
├── build_sets.py          ← calibration/main 구축
└── build_synthetic.py     ← synthetic edge-case 구축
```

## gold annotation 방법 (trusted labeling procedure)

- 모델: `tokenharbor/qwen3.8-flash:free` (라우터 정식 지원 경로, 사용자 지정)
- 온도 0.0, reasoning_effort=none, workers=4 (503 rate-limit 회피)
- 프롬프트: 사용자 메시지에 지시 포함 (이 경로는 system prompt 무시 — 실측)
- 원칙: 종결어미가 아니라 **의미 + 장기 기억 가치**로 판단, 2-stage 사고(dialog act → memory type), NO_STORE 허용
- 품질 검증: 25개 샘플 수동 검토 (98% 타당), 이상 2건 GOLD_AMBIGUITY/DATASET_ARTIFACT 기록

## 조건 (지시문 §15)

- Condition A (발화만): 기본 — 현재 classifier는 문맥 미사용 구조이므로 A/B 동일
- Condition B (문맥+발화): classifier 구조상 입력이 발화 단일 → 적용 불가 (기록만)