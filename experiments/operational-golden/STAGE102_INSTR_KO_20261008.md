# STAGE102: 한국어 지시문 A/B — KO vs EN paired 실측 (2026-10-08, 400콜)

## 배경

core.today 6편 실측: Jev rerank에서 한국어 지시문이 영어보다 미세 우위
(0.929→0.933, 정답1등 89.4→90.6%, n=85, 잡음 가능). 우리 INSTR·abstain 라벨은
전부 영어(`m48.INSTR`, `ABSTAIN_CURRENT`). 한국어 지시문이 우리 데이터에서도
유효한지 same-session paired로 판정.

## 설계

- cond en: 현행 영어 (INSTR_EN + ABSTAIN_EN)
- cond ko: 한국어 (INSTR_KO + ABSTAIN_KO)
  - INSTR_KO = "질문에 가장 직접적으로 답하는 후보를 하나 고르세요. 쓸 만한 근거가 없으면 마지막 abstain 선택지를 고르세요."
  - ABSTAIN_KO = "질문에 답하는 데 쓸 수 있는 근거가 되는 후보가 없습니다"
- 셋: op-90 + noans-50 + live-60 = 200쿼리 × 2 cond = 400콜
- 같은 세션 alternate (paired), 같은 pool (cond 간 동일)
- 판정: hit@1/3·abstain·FP + flip 대조표 (stage54 gold_after 정의)

## 결과

| 지표 | en (현행) | ko (후보) | delta |
|---|---|---|---|
| op hit@1 | 77/86 | 77/86 | 0 |
| op hit@3 | 78/86 | 78/86 | 0 |
| op abstain | 2 | 2 | 0 |
| noans FP | 24/50 | 23/50 | −1 |
| live abstain | 0/60 | 0/60 | 0 |
| err | 0 | 0 | 0 |

**flip (op): 0건** — both=77, en_only=0, ko_only=0. 같은 쿼리·같은 pool에서
지시문 언어는 op 결과를 **하나도 바꾸지 않았다** (77/86 완전 동일).

**noans 미세 차이**:
- ko 방어 3건 (FP→abstain): diag6 오프라인, 커밋 메시지 규칙, API 키 하드코딩 — **규칙/사실 질문 계열**
- ko FP 2건 (abstain→pick): deepseek 스트림("~적이 있어?"), web_extract JS("~옵션이 있어?") — **과거사/기능 질문 계열**
- 순 −1 FP (잡음 범위)

## 판정 — 보류 (채택 근거 없음)

- 외부 6편의 '한국어 지시문 우위'(+0.004)는 우리 데이터에서 **재현되지 않음**
- 단, **손해도 없음** (op 완전 동일) — 1/50 FP 차이는 잡음
- noans 3건 방어가 규칙/사실 질문에, 2건 FP가 과거사 질문에 몰린 패턴은 흥미롭지만
  n=5라 확정 불가 — **이 패턴을 추가 검증하려면 규칙/과거사 질문 셋으로 별도 실측 필요**
- **코드 미변경. `m48.INSTR`·`ABSTAIN_CURRENT`는 현행 영어 유지.**

## 산출물

- `experiments/operational-golden/stage102_instr_ko.py` — 러너
- `experiments/operational-golden/data/stage102_instr_ko_raw.json` — 400콜 raw
- 본 문서 (STAGE102)