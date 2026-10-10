# STAGE116 — LongMemEval 재판정 (claude-haiku) + 판정 모델 가설 기각 (2026-10-10)

## 배경
- LongMemEval-S 500문항 Full 결과가 24.1% (stage112/113, deepcombo judge)
- 사용자 지적: "다양한 도메인에서 무력하다는 이야기 아닌가?"
- 가설: hypothesis가 정답을 말하는데 deepcombo가 no 판정한 케이스가 다수 (샘플 2건 발견)
  → 판정 모델 교체(deepcombo→haiku)로 점수가 오를 수 있다는 가설

## 실측
- **설계**: stage112 결과(hypothesis)를 claude-haiku로 재판정. JEV 콜 없음 (hypothesis 이미 생성됨)
- **소량 검증(5건)**: "What degree" 정답 그대로 → yes 등 판정 정확해 보임 (착시였음 — 대표 케이스 2건이셔서)

## 결과
| 판정 모델 | 전체 정확도 |
|---|---|
| deepcombo (기존, 494건) | 24.1% (119) |
| **claude-haiku (재판정, 500건)** | 18.6% (93) |
| **claude-haiku (abstention 보정, 500건)** | **23.0% (115)** |

### 모델 간 비교 (보정 후)
- **일치율 97.2%** (486/500)
- deepcombo vs haiku(보정) 실질 동일 수준 (24.1% vs 23.0%)

### abstention 30건 처리 (stage117 보정)
- deepcombo: 30건 전부 yes (100% — "정직하게 거부=정답" 규칙 반영)
- haiku (초기): 1건만 yes, 29건 no (판정 프롬프트에 abstention 규칙이 **없었음**)
- haiku (보정, stage117): **28/30 yes (93.3%)** — 규칙 추가 후 정직 거부 인정
- 보정 후에도 no 2건은 **실제 오답** (거부 없이 지어냄: "10년"·"4명") — 설계 의도대로 판정됨

## 결론 — 가설 기각 (확정)
1. **"판정 모델 교체로 점수가 오른다"는 가설 기각** — 두 모델 모두 ~23~24% (97.2% 일치)
2. **LongMemEval 24%는 진짜 read-path(JEV choice) 한계** — 판정 노이즈 아님
3. oracle(정답 세션 제공)에서도 25.1%였던 것과 일치 — "pool에 답 없음"이 아니라
   **JEV choice가 답 있는 메모리를 usable evidence로 인정하지 않는 구조적 한계**가 확증됨

## 사용자 질문에 대한 답 (LongMemEval 저점수)
- "다양한 도메인에서 무력하다" — **부분적으로 맞음 (절반만)**:
  - 맞는 부분: multi-session 9%·temporal-reasoning 9%는 oracle에서도 바닥 — **합성/시간 추론 질문에 구조적 한계** (단일-best pick)
  - 틀린 부분: abstain 52%는 라이브(7%)와 환경 차이 (filler 중심 haystack vs 실제 운영 대화) — "무력"이 아니라 **환경 부적합**에 가까움
  - 정직 거부(abstention 93~100%)는 설계 강점 유지

## 파일
- 러너: `stage116_lmev_rejudge_haiku.py`, `stage117_lmev_abstention_rejudge.py`
- 결과: `data/stage116_lmev_haiku_judged.jsonl`, `data/stage117_lmev_abstention_haiku.jsonl`
- 로그: `stage116_run.log`