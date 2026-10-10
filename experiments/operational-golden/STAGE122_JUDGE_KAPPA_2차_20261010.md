# STAGE122: 판정 모델(haiku) κ 확장 — 2차 54건 (stage104) → 통합 κ=0.157 (2026-10-10)

> b-ai 지적 "사람 라벨 ≥100으로 κ" — 1차 46건(stage102p) + 2차 54건(stage104, dedupe 45) = **91건**
> 2차 셋: haiku 생성 응답, no 16건 일부러 과대표집 (κ 정밀 측정용)

## 1. 2차 판정 결과

| 항목 | 값 |
|---|---|
| 시트 | 54건 (no 16 + yes 38 층화) |
| **사용자 판정** | **전부 yes (54/54)** |
| dedupe ((query,sample) 중복 제거) | **45건** — 같은 응답이 framing만 달리해 9건 중복 |
| dedupe 후 일치 | 34/45 = 76% |
| **dedupe 후 κ** | **0.000** (사용자 yes 100% → κ 공식이 우연 일치로 계산) |

## 2. 중복 문제 (사용자 지적)

- 54건 중 **고유 query 31개** ("Mnemosyne repo 주소" 6회, "file_content" 4회 등)
- **(query, sample) 기준 9건 중복** — 동일 응답이 framing(fF/fT)만 달리해 2회 등장
- **영향**: κ를 부풀림 (같은 응답 2회 일치 계산) → **κ 계산은 dedupe(45건) 버전이 정확**
- **교훈**: 라벨링 시트 생성 시 (query, sample) 중복 제거를 사전에 — 같은 응답을 2번 물으면 안 됨

## 3. 통합 κ (1차 + 2차 dedupe = 91건)

| 셋 | n | 일치 | κ |
|---|---|---|---|
| 1차 (stage102p, deepcombo 응답) | 46 | 40 (87%) | **0.355** |
| 2차 (stage104, haiku 응답, dedupe) | 45 | 34 (76%) | **0.000** |
| **통합** | **91** | 74 (81%) | **0.157** |

- 통합 분포: haiku no 19 / yes 72 · 사용자 no 2 / yes 89
- **불일치 17건 전부 haiku=no → 사용자=yes** — 과소판정 편향 100% 단일 방향

## 4. 해석 (중요)

1. **haiku의 no 판정은 실질적으로 전부 오판** — 2차 셋(no 16건 과대표집)에서 사용자가 1건도 no로 안 봄
   → haiku가 "일반 지식 대체 가능"으로 판정한 것들이 **사용자 기준 전부 메모리 인용**
2. **κ=0.157 (통합) — "거의 일치 없음"** — 이전 0.355는 1차 셋의 no 2건(사용자)이 희석시킨 것
3. **사용자 기준으로는 k=5 fF no율(2.9%)이 사실상 0에 가까울 것** — haiku가 no를 과다 생성
4. **stage104(p=0.0078)은 완전히 신뢰 불가** — haiku의 no 과다 생성 편향이 프레이밍 차이로 읽힘
5. **2차 셋의 no 16건은 stage104의 전체 no 16건 전수** — 즉 stage104의 no 16건 전부가
   사용자 기준 yes였음 → **stage104 "fT가 fF보다 no 많음(12 vs 4)"은 haiku의 오판 분포일 뿐**

## 5. 후속

- [ ] 3축 설계(일반지식대체+구체성신호) 검증 — v9 외부 AI 검토 후
- [ ] 판정 프롬프트에 "플랫폼(에이전트) 공개 지식 ≠ 일반 지식" 경계 명시 (Q1-d)
- [ ] 라벨링 시트 생성 시 (query,sample) dedupe 사전 적용

## 6. raw

- 1차: `judge_kappa_label84.json` · `judge_kappa_labeled62.json`
- 2차: `judge_kappa_label54_stage104.json` · `judge_kappa_verdicts2.json` (Downloads)
- 시트: `judge_kappa_label_sheet.html` · `judge_kappa_label_sheet2.html`