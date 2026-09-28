# JEV_INGESTION_REPORT.md — JEV 생성 분류 (Ingestion Classification) 실측 리포트

> **2026-09-28 (P8+G0.6 최종)** · JEV System One (jev-latest) · 14종 분류 · 실측 1,975건 + live 142건

## 0. 명명 규칙 (이 문서에서 통일)

| 접두사 | 의미 | 예 |
|---|---|---|
| **P{번호}** | JEV **프롬프트(지시문)** 버전 | P8 = v8 지시문 (84.9%) |
| **G{신뢰도}** | **저장 게이트** 규칙 (SKIP 조건) | G0.6 = store==NO_STORE && 신뢰도≥0.6 |
| 조합 | 프롬프트 + 게이트 | **P8 + G0.6** (기존 "v12") |

> 과거 명칭 "v12"는 프롬프트 버전이 아니라 **P8과 G0.6의 조합**이었음. 이제부터 조합 표기만 사용.

## 1. 프롬프트 버전 (P) — 전체 1,975건 14-type exact accuracy

| 프롬프트 | 정확도 | 비고 |
|---|---|---|
| P1 | 48.6% | 초기 — 클래스 불균형(NO_STORE 67%)에 미적응 |
| P2~P7 | (단계적 개선) | 경계 정의·F5 오버라이드 반복 |
| **P8** | **84.9%** | **채택 (현행)** — commitment/learning/decision/goal/context/instruction 경계 확정 |
| P9 | 96% 저장 (과잉) | "모든 질문=STORE" 도메인 적응 → 저장 필터 붕괴, 폐기 |
| P10 | **68.4%** (▼16.5pp) | P9에 진행 명령 예외 추가 — type 분류 과잉 교정, 폐기 |
| P10-EN | 68.5% (400건) | 지시문 영어 — 노이즈 수준, 폐기 |

## 2. P8 vs P10 상세 비교 (1,975건)

| 지표 | P8 | P10 | 변화 |
|---|---|---|---|
| 14-type 정확도 | **84.9%** | 68.4% | **-16.5pp** ❌ |
| gold NO_STORE 정확도 | **87.7%** | 70.0% | -17.7pp |
| gold store 정확도 | **79.2%** | 65.2% | -14.0pp |
| store precision | **0.913** | 0.696 | -0.217 |
| store recall | 0.535 | **0.567** | +0.032 |
| 악화(right→wrong) | — | 353건 | ❌ |

**원인**: P10의 "소프트웨어 작업 맥락 질문=STORE" 규칙이 일반 대화(NO_STORE 67%)에 과잉 적용
- NO_STORE 235건이 저장으로 오분류, fact 50·event 10·context 8·commitment 5건 등 대량 오분류
- **도메인 적응은 게이트 규칙(G)에만 적용해야 하며, 프롬프트(type 분류)는 P8 유지가 정답**

## 3. 언어 A/B (지시문 언어 실측)

- 400건 층화 (NO_STORE 200 + store 200) 동일 모델 동일 샘플: KO 67.2% vs EN 68.5% (+1.3pp)
- **KO/EN type 일치 97%** — 언어는 지시 구조/예시 언어보다 영향 작음
- 게이트(live 142건): KO 누락 0/과다 11 vs EN 누락 0/과다 10 — 동일
- **결론: JEV는 '영어 최적화'가 아니며, 예시가 입력 언어와 같은 것이 지배적. 한국어 지시(P8) 유지.**

## 3.5 컨텍스트 주입 실험 (P8+CTX, 1,975건) — 전체 주입은 오히려 하락 ❌

| 지표 | P8 (무CTX) | P8+CTX | 변화 |
|---|---|---|---|
| 14-type 정확도 | **84.9%** | 76.8% | **-8.1pp** ❌ |
| with_ctx 1,335건 | 82.8% | 73.6% | -9.2pp |
| type 변경 | — | 264건 | 향상 19 / **악화 180** |

- 원인: 이전 턴(원시 1~2개) 주입으로 JEV가 "현재 발화"가 아닌 "대화 전체 맥락"에 반응
  — NO_STORE -47, preference -25, fact -21, commitment -14 (100%→57.6%)
- P3(160건 subset)에서 context가 도움이 된 건 **정제된 관련 턴**이었기 때문 — 원시 이전 턴은 분류 방해
- **결론: 실운용에서도 무컨텍스트(P8) 유지. context 주입 시 정제된 턴만 허용.**

## 3.6 P11 실험 — store 오분류 근본 원인 규명 (302건 subset)

- **문제**: gold store 649건 중 302건(46.5%)을 store=NO_STORE로 오분류 (store recall 0.535)
- **P11-b (store 단독 재호출)**: 회수 2.3% (7/302) → **store 질문 자체가 "저장할 가치 없음" 편향** (분류력 문제 아님)
- **P11-a (type 주입 후 store)**: 회수 85.1% (257/302) → type이 저장타입임을 알려주면 즉시 회수
  - gold type별: commitment/observation/error/learning/artifact 100%, preference/fact/context 85~92%
- **결론**: 
  1. store 오분류의 근본 원인 = **store 지시문이 저장타입을 store로 인식 못 하는 프롬프트 구조**
  2. type 주입(P11-a) or type 이중확인(G-qual)이 해법
  3. **G-qual이 최선**: 기존 1호출 + type 이중확인으로 같은 이득(88% vs 85.1%), 추가 비용 0

## 4. 게이트 규칙 (G) — live A/B 검증 (state.db 142건, 사용자 판정 83건)

| 게이트 | SKIP 조건 | store recall (1975) | live 누락(bad) | live 과다(ok) |
|---|---|---|---|---|
| G0.6 | store NO & conf≥0.6 | 0.656 | 0 | 11 |
| **G-qual** | store NO & type NO & conf≥0.6 | **0.951** | **0건** ✅ | **5건** |
| G-qual2 | store NO & type NO (conf 무관) | 0.945 | 0 | 5 |

```
G-qual 규칙 (최종 채택):
  store==STORE                              → KEEP
  type이 저장타입 (≠NO_STORE)                → KEEP (type 이중확인)
  store==NO_STORE && type==NO_STORE && conf<0.6 → KEEP (저신뢰 보존)
  store==NO_STORE && type==NO_STORE && conf≥0.6 → SKIP (저장 생략)
```

**채택 사유**:
- **G-qual vs G-qual2**: live 142건 동일(SKIP 5, 누락 0, 과다 5). 1975건에서 G-qual이 recall +0.6pp (0.951 vs 0.945). conf 조건 제거(G-qual2)는 저신뢰 NO_STORE까지 SKIP해 recall을 약간 깎음 → **G-qual의 저신뢰 KEEP 보수성이 recall을 살림**
- store recall 0.656→**0.951** (+45%): P11이 규명한 store 지시문 편향을 type 이중확인으로 해결 (추가 호출 0)
- 누락 0건: 사용자 bad 14건 전부 KEEP
- 원칙: **JEV가 확신(conf≥0.6)할 때만 SKIP, 의심되면 KEEP** (누락보다 과다저장이 안전)
- G-type&store (구 v4게이트)는 type도 NO_STORE만 SKIP이라 너무 많이 걸러 누락 14건 — 폐기

## 6. 쓰기 게이트 실장 (P8 + G-qual) — 2026-09-28

**실제 쓰기 경로 확인 (코드 실측)**:
- Hermes 턴 종료 → `mnemosyne_hermes.MnemosyneMemoryProvider.sync_turn()`이
  `[USER] {발화}` (importance 0.5) + `[ASSISTANT] {응답}` (importance 0.15)를 **무조건 2건 저장** (len>5, 필터 통과 시)
- `harnesses/hermes_j1.py`는 prefetch(읽기)만 오버라이드 — 쓰기는 base 그대로 → **과다저장의 실체**

**적용 위치**: `harnesses/hermes_j1.py`의 `JevRerankProvider.sync_turn()` 오버라이드 (옵션 A)
- user 발화: `[USER] ` 접두사 제거 → JEV store/type 분류 1회 → **G-qual** → SKIP 시 remember 생략
- assistant 발화: 게이트 없이 base 그대로 (정책 변경 아님)
- JEV 실패/타임아웃/비활성 → KEEP (기존 저장, 누락 방지)
- 킬스위치 `JEV_WRITE_GATE=0` → base sync_turn (기존 100% 저장)
- 로깅: `jev_trace.log`에 `write-gate SKIP/KEEP conf type`
- Hermes core / Mnemosyne core 무수정 (기존 원칙 유지)

**설계 근거**: P8+G-qual 실측 (store recall 0.951, live 누락 0, 과다 5)

**한계**:
- 판정이 context 없이 단독 발화 기준 — 실제 운용(history context 주입)과 차이 가능
- 83건 판정도 사용자 기준 불확실 (단, bad 14건 패턴은 일관: 기술 질문)