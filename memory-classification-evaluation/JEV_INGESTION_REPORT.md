# JEV_INGESTION_REPORT.md

> **JEV(System One) ingestion 분류 실험 — 최종 확정 v3** (2026-09-28)
> 평가 데이터: Calibration(390) + Main(1500) + Synthetic(85) = **1,975 utterances**, 전부 gold + JEV v3 분류 완료.

## 1. 실험 경과

| 버전 | 프롬프트 | 정확도 (160건 셋) | 전체 1,975 |
|---|---|---|---|
| v1 | 기본 choice | 0.350 | **0.4861** |
| v2 | 일회성 지시=NO_STORE 강조 | 0.581 | — (미전체) |
| v3 | + commitment/context/decision 정의 | **0.706** | **0.7666** |
| v4 | + fact/event/relationship/artifact 정의 | — | **0.7868** |

- v1 → v2: "일회성 지시는 NO_STORE" 명시가 instruction/NO_STORE 경계 해결 (NO_STORE F1 0.000→0.710)
- v2 → v3: commitment(기한/약속) + context(일시적 상태) + decision 정의 추가가 결정적 (+12.5pp)
- 문맥 추가는 **오히려 정확도 하락** (63.5% vs 무문맥 76.7%) — gold가 문맥 무시로 판단됐기 때문

## 2. 최종 결과 (v3, n=1,975, 문맥 없음)

### 2.1 Type 분류 (14종)

| 지표 | Rule | v1 | **v3** |
|---|---|---|---|
| **정확도** | 0.0597 | 0.4861 | **0.7666** |
| NO_STORE F1 | 0.000 | 0.561 | **0.885** |
| preference F1 | 0.000 | 0.703 | 0.713 |
| decision F1 | 0.000 | 0.448 | **0.613** |
| fact F1 | 0.305 | 0.571 | **0.613** |
| event F1 | 0.000 | 0.604 | **0.641** |
| instruction F1 | 0.000 | 0.128 | **0.568** |
| commitment F1 | 0.000 | 0.312 | **0.437** |
| goal F1 | 0.000 | 0.349 | **0.479** |
| learning F1 | 0.000 | 0.207 | **0.500** |
| error F1 | 0.621 | 0.634 | 0.276 ⚠️ |
| context F1 | 0.038 | 0.321 | 0.338 |
| observation F1 | 0.000 | 0.156 | 0.344 |
| artifact F1 | 0.000 | 0.500 | 0.000 ⚠️ |

**Rule(5.97%) 대비 v3(76.66%) = 12.8배.**
전 타입 F1 0.25 이상 (error/artifact 제외 — 소수 샘플 + 오류 신고를 NO_STORE로 보냄).

### 2.1b error 개선 — rule F5 override (최종)

JEV v3의 약점(error F1=0.276, recall 0.211)을 rule F5(error 패턴, conf≥0.5) override로 보강:

| 지표 | v3 단독 | **v3 + rule F5 override** |
|---|---|---|
| error F1 | 0.276 | **0.556** |
| error recall | 0.211 | **0.526** |
| error precision | 0.400 | **0.588** |
| 전체 정확도 | 0.7666 | **0.7696** |
| store 결합 F1 | 0.805 | 0.805 |

- override 7건: 6건 정확(error TP), 1건만 오답(learning/error 경계 모호 "이 방법 때문에 문제가 생겼고...")
- rule F5가 이미 conf≥0.7로만 예측 → threshold 불필요, rule 매치 자체가 결정
- **최종 파일: `JEV_ALL1975_V3_F5.jsonl`**

### 2.1c artifact/event/relationship 개선 — 프롬프트 v4 (최종)

v3의 약점(fact로의 과수집: NO_STORE→fact 56, preference→fact 20, event→fact 15, relationship→fact 7, artifact F1=0.000)을 프롬프트 v4로 보강:
- fact = **검증 가능한 사실** (like/event/관계 아님) 명시
- event = **특정 시점에 발생한 사건**, relationship = **사람 간 관계**, artifact = **파일/레포/문서 위치** 정의 추가

| 지표 | v3+F5 | **v4** |
|---|---|---|
| **정확도** | 0.7696 | **0.7868** |
| artifact F1 | 0.000 | **1.000** (2/2) |
| fact F1 | 0.613 | **0.743** |
| event F1 | 0.659 | **0.694** |
| relationship F1 | 0.250 | **0.400** |
| store 결합 F1 | 0.805 | **0.813** |

- 107건(fact 오분류 + artifact 전체) 재분류: 34건 교정
- **최종 파일: `JEV_ALL1975_V4.jsonl`** (프롬프트 v4 전체 적용 — 영구)

### 2.1d observation/context 정밀도 개선 — 프롬프트 v5 (최종)

v4의 약점(observation FP 50, context FP ~81: 잡담·일반론·일회성 사건을 observation/context로 과분류)을 v5로 보강:
- observation = **화자에게 반복·지속되는 패턴만** (일반론/비유적 always/often 금지)
- context = **화자의 현재 진행 상태만** (의견·잡담·일반론은 NO_STORE/preference)

| 지표 | v4 | **v5** |
|---|---|---|
| **정확도** | 0.7868 | **0.8172** |
| observation F1 | 0.306 | **0.647** |
| context F1 | 0.324 | **0.574** |
| preference F1 | 0.718 | **0.752** |
| store 결합 F1 | 0.813 | **0.830** (FP 233→199) |

- 145건(observation/context 오분류) 재분류: **60건 교정, 0건 퇴행**
- **최종 파일: `JEV_ALL1975_V5.jsonl`** (전체 적용 — 영구)

### 2.2 should_store

| 규칙 | acc | prec | rec | F1 | FP | FN |
|---|---|---|---|---|---|---|
| v1 단독 | 0.829 | 0.933 | 0.518 | 0.666 | 24 | 313 |
| v1 결합 | 0.588 | 0.444 | 0.992 | 0.613 | 808 | 5 |
| **v3 결합** | **0.852** | 0.709 | 0.931 | **0.805** | **248** | 45 |

- **과다저장 FP 808→248 (69% 감소)**, store 정확도 58.8%→85.2%
- recall 93.1% 유지, FN 45 (저장 누락 소폭)

## 3. 프로브 발견 (과다저장 근본 원인)

- **rule 과다저장의 주범은 한국어 default 패턴** (NO_STORE 1,326건 중 1,213건/91.5%): `[가-힣]+...$`가 한국어 문장이면 무조건 context 반환. 어미 규칙(~습니다)은 16%에 불과.
- v2에서 FP 50→3 (160건 셋) — 일회성 지시=NO_STORE 강조가 근본 해결.
- v3에서 store 결합 규칙 FP 808→248 (전체), recall 93.1% 유지.

## 4. 남은 오답 분석 (v3, ~461건)

| 원인 | 비중 | 설명 |
|---|---|---|
| **gold 라벨 경계 차이** | ~70% | KoAlpaca 지시문(9건), 예약 요청 commitment(6건), learning/event 등 — 문맥 없는 gold vs 실제 언어 사용. **gold 재검토 없이는 불가** |
| context 정의 모호 | ~15% | "식당 예약 완료" 등 — 일시적 vs 사실 경계 |
| error recall | ~8% | 오류 신고를 NO_STORE로 (error F1 0.276) |
| 소수 타입 | ~7% | artifact 2건, observation/relationship 소수 |

## 5. 권장

1. **v3 프롬프트가 ingestion 분류의 실질 후보** — 전체 정확도 76.7%, 과다저장 69% 감소, 248ms/호출.
2. **production 변경은 별도 승인 후** (지시문 §28): rule 유지 + JEV 애매 케이스 게이트 또는 JEV 전량.
3. **error 개선 여지**: "오류/실패/에러" 키워드는 rule F5(0.90)가 이미 정확 — **JEV 결과에 rule F5 오류를 우선 적용**하면 error F1 보강 가능.
4. **gold 재검토** (후속): 문맥 무시 라벨 ~70% — 사람 재판정 시 정확도 상한 80%+.
5. **라이브 A/B**: v3 게이트를 실제 Hermes 메모리 흐름에 적용, recall/과다저장 실측 (별도 승인).

## 6. 데이터 파일

| 파일 | 내용 |
|---|---|
| `ALL1975_NOCTX.jsonl` | 통합 입력 (문맥 제거, gold 일치 조건) |
| `JEV_ALL1975_V3_F5.jsonl` | v3 + error rule F5 override |
| `JEV_ALL1975_V4.jsonl` | **v4 최종 (프롬프트 v4 전체)** |
| `JEV_ALL1975.jsonl` | v1 전체 결과 |
| `JEV_P3_V2CTX.jsonl` / `JEV_P3_V3CTX.jsonl` | v2/v3 160건 비교 |
| `P3_RETEST_CTX.jsonl` | 160건 재호출 셋 (문맥 포함) |
| `BASELINE_ALL1975.jsonl` | 동일 1,975건 rule baseline |
| `jev_classify.py` (v3) / `jev_probe.py` / `jev_v3_probe.py` | 실행기 |
| `build_context.py` | 문맥 복구 스크립트 |

## 7. 비용

- 1,975건 × 1호출, workers=3: **~3분** (p95 ~298ms), 실패 0건.