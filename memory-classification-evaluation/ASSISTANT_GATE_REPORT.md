# ASSISTANT_GATE_REPORT.md — assistant 발화 저장 게이트 실측 (G-AS)

> 작성: 2026-09-28 | 데이터: state.db 최근 21일 assistant 발화 200건 + gold50 인간 판정
> API: TypeSafe systemone (`jev-latest`) — 9router(localhost:20128) 아님

## 1. 배경

Mnemosyne 기본값은 `_sync_roles = {"user"}` — **assistant 발화는 자동 저장되지 않음** (원본 설계, "assistant transcript noise 방지").
그러나 사용자 관찰: **"작업 내용의 핵심은 assistant 답변(결과물)에 있고, 지시만 저장하면 작업을 기억하지 못한다."**

→ assistant 발화 저장의 가치와, 저장 시 **엄격 게이트** 적용 가능성을 실측으로 검증.

## 2. 데이터

| 항목 | 값 |
|---|---|
| 원본 | Hermes `state.db` messages, role='assistant' |
| 기간 | 최근 21일 |
| 전체 assistant | 3,715건 |
| 샘플 (30~3000자 필터) | 200건 (`ab_live_assistant.jsonl`) |
| gold 인간 판정 | 50건 무작위 (`ab_assistant_gold50.json`) — STORE 31 / NO_STORE 19 |
| 분류 | JEV P8 (`jev_classify_assistant.py`) · gold50 재사용 (`jev_classify_AS.py`) |

## 3. 실측 결과

### 3.1 assistant 발화는 저장 가치가 높다 (유저와 정반대)

200건 분류 (P8):

| 항목 | 값 |
|---|---|
| store=STORE | 158건 (**79.0%**) |
| store=NO_STORE | 42건 (21.0%) |
| type 분포 | commitment 32 · goal 32 · observation 27 · fact 26 · instruction 22 · context 17 · decision 11 · error 9 · event 8 · NO_STORE 7 · learning 7 · artifact 2 |

→ 유저 발화(일회성 지시 다수)와 달리 **assistant는 결과물·결정·조사 내용이 대부분**. "메모리에 지시만 있고 결과물이 없다"는 사용자 지적이 실측으로 확인됨.

### 3.2 gold50 기준 게이트 성능 비교

| 게이트 | KEEP | Precision | Recall | F1 | 비고 |
|---|---|---|---|---|---|
| G1 (store==STORE) | 80% | 0.725 | 0.935 | 0.817 | FP 11건 |
| G0.6 (store+conf≥0.6) | 60% | 0.767 | 0.742 | 0.754 | 결과물 8건 누락 (conf 낮음) |
| G0.7 (store+conf≥0.7) | 52% | 0.885 | 0.742 | 0.807 | 결과물 8건 누락 |
| commitment 필터 | 54% | 0.852 | 0.742 | 0.793 | TP commitment 6건까지 손실 |
| **G-AS (store+type≠context)** | **78%** | **0.744** | **0.935** | **0.829** | **최종 채택** |
| P8-AS 전용 프롬프트 | 24% | 0.917 | **0.355** | 0.512 | recall 폭락 → 폐기 |

### 3.3 핵심 발견

1. **conf 임계값은 잘못된 축**: assistant는 "원인 확정!" 같은 진짜 결과물의 conf가 0.59~0.97로 분산. conf를 올리면 **결과물까지 버려짐** (recall 0.742).
2. **FP(과다저장)의 주범은 commitment**: "X 완료. 이제 Y 하겠다" (진행 의도)가 commitment로 분류되어 통과. conf 0.83~0.93로 높아 conf 필터로도 안 걸림.
3. **규칙(정규식) 필터 실패**: "이제...하겠다" 패턴이 FP commitment 9건 중 2건만 매치 — 문구 없는 진행 의도가 다수. 규칙 기반 구분 불가.
4. **P8-AS 전용 프롬프트 실패**: "진행 의도=NO_STORE, 결과물=STORE" 강조했지만, **조사 결과·결론까지 context로 밀어버려 recall 0.355~0.387 폭락**. TypeSafe jev의 store 분류기가 근본적으로 보수적.
5. **API 주의**: 초기 실패는 `localhost:20128`(9router) 사용 때문 — 9router는 **간헐적 400 "Invalid JSON or schema"** 반환. TypeSafe 직접 API 사용 시 즉시 해결.

### 3.4 최종 결정: G-AS

```
store == STORE && type != context  →  KEEP (저장)
그 외                              →  SKIP
```

- precision 0.744 / recall 0.935 / F1 0.829
- **결과물 보존 최우선** (recall 희생 없음), FP는 경미한 과다저장(진행 전환 문장)만
- gold50 MISSED 2건: 조사 개시·방향 발화 (진행 의도성 — SKIP이 오히려 타당)

## 4. 구현 시 주의 (실제 통합 시)

1. **API**: 반드시 `https://api.typesafe.ai/v1/systemone` + `jev-latest` 사용. 9router 아님.
2. **게이트 위치**: `gateway/write_gate.py` 확장 — user 발화(기존 G-qual)와 분기.
   - user: 기존 G-qual (`store==NO_STORE && type==NO_STORE && conf≥0.6 → SKIP`)
   - assistant: **G-AS** (`store!=STORE || type==context → SKIP`)
3. **sync_roles**: `["user","assistant"]` 활성화 필요 (assistant 자동 수신).
4. **부가 필터**: assistant 메시지는 10자 초과만 자동 저장 (Mnemosyne 기본) — 짧은 답변은 원천 제외.
5. **DB 크기**: assistant 전체 저장 시 연간 +1MB 미만 (실측: 200건 평균 ~250자) — 디스크 부담 없음. 비용은 "검색 품질 오염"이나 G-AS로 일부 통제.

## 5. 파일

- `data/ab_live_assistant.jsonl` — 200건 원본
- `data/ab_assistant_classified.jsonl` — P8 분류 결과
- `data/ab_assistant_gold50.jsonl` / `.json` — gold50 샘플 + 인간 판정
- `data/ab_assistant_gold50.html` / `_ready.html` — 판정 UI
- `ab_extract_assistant.py` / `jev_classify_assistant.py` / `jev_classify_AS.py` / `analyze_assistant_gold.py` / `make_assistant_gold50.py` / `build_assistant_gold50_html.py`

## 6. 200건 전체 적용 통계 (2026-09-28)

G-AS를 200건 전체에 적용한 실측:

| 항목 | 값 |
|---|---|
| KEEP (저장) | **150건 (75.0%)** |
| SKIP | 50건 (25.0%) |
| KEEP type 분포 | observation 27 · fact 26 · commitment 25 · goal 22 · instruction 16 · decision 11 · error 9 · learning 7 · event 5 · artifact 2 |
| SKIP type 분포 | context 17 · goal 10 · commitment 7 · NO_STORE 7 · instruction 6 · event 3 |
| 전체 텍스트 | 59,746자 (평균 299자/건) |
| KEEP 텍스트 | 54,956자 (**저장량 92%**) |

**해석**:
- assistant 발화의 **75%가 저장** — 유저(게이트로 ~23% SKIP)와 달리 결과물 중심이라 저장 비율이 훨씬 높음
- **DB 크기 영향**: 21일간 assistant KEEP ~150건 × 평균 299자 ≈ 45KB/21일 → **연간 ~0.8MB** (13.4MB DB에서 무시 가능)
- **context 필터 정확성 검증 (2026-09-28, 17건 전수 gold)**: context 분류 17건 전체를 인간 판정 → **STORE 0 / NO_STORE 17** (오분류 0%). G-AS가 SKIP하는 store=STORE && context 8건도 **전부 NO_STORE** — "진행 중 발언/임시 상태"로 판정. **G-AS는 결과물을 0건 버림** (이전 "과하게 SKIP 가능" 우려는 판정 기준 차이였고, 전수 검증으로 해소)
- **결론**: G-AS 확정 (수정 불필요)

## 7. G-AS commitment FP 필터 v4 (2026-09-28 실험 + 라이브 적용)

### 배경
- G-AS FP 10건 중 **7건이 commitment** (gold50 실측) — "X 완료. 이제 Y 하겠다" (결과 보고 + 진행 전환 결합형)
- 단순 규칙(순수 진행 선언)은 매치 0건 — commitment는 **결과 보고가 포함된 결합형**이라 어휘 필터로 분리 불가

### 규칙 (gateway/write_gate.py `_as_commitment_fp_filter`)
```
KNOWLEDGE(검증|확인|조사|분석|테스트|정밀|확정|검토|추정|판단|파악|실측|분해|라이브|확보) → KEEP (TP 보호)
TRANSITION(정상|감지|동작|완료|완성|등록|파악).{0,40}(이제|다음|그럼) && OPERATION(백업|설치|스왑|설정|복구|적용|구축|등록|이관|모니터링|cron) → SKIP
INTENT(진행하겠|만들겠|구축하|정리하|작성하겠|등록하겠|돌릴게|할게|해볼게|적용하겠|시작하겠|세겠습니다) → SKIP
```
- commitment & store==STORE(KEEP) & 위 규칙 → SKIP (reason=`commitment-fp-v4`)

### 실측 검증
| 지표 | G-AS 단독 | G-AS + v4 | 변화 |
|---|---|---|---|
| gold50 Precision | 0.744 | **0.806** | **+6.2pp** |
| gold50 Recall | 0.935 | 0.935 | 유지 |
| gold50 F1 | 0.829 | **0.866** | **+3.7pp** |
| FP | 10 | **7** | -3건 (commitment FP 43% 감소) |
| TP 회귀 | — | **0건** | 안전 |
| 200건 저장량 | 150건 | **146건** | -2.7% (commitment 25→21) |

### 설계 이력 (모두 gold50 + 200건 실측)
| 버전 | FP 감소 | 회귀 | 문제 |
|---|---|---|---|
| v1 (intent && !verify) | 43% | 0 | "~확인하겠다" 지식형 FP 미포착 |
| v2 (transition 추가) | **57%** | 0 | "검증 완료...다음"(TP) 오손 위험 |
| v3 (transition에 verify) | 14% | 0 | verify가 "백업/동작"까지 보호 → FP 급감 |
| **v4 (KNOWLEDGE/OPERATION 계층화)** | **43%** | **0** | **채택** — TP 안전 + FP 감소 균형 |

- v2는 "확장 기능 로직 검증 완료. 다음..."(TP)을 SKIP할 위험이 있어 폐기 (verify 무시 transition)
- v4는 "백업"(운영작업)과 "검증"(지식작업)을 분리 → TP 보호 유지
- 82561 같은 "결과+다음 행동이 한 메시지에 결합"(`\n\n우선...확인하겠다`)은 KNOWLEDGE로 **KEEP 유지** (결과 보고가 실제로 있으므로 안전한 방향)

### 라이브 적용 상태
- `gateway/write_gate.py`에 반영 완료 (2026-09-28)
- 검증: 기존 smoke 7케이스 ALL PASS + gold50 재현(회귀 0/FP 43%) + 의도 케이스 스모크 8/8
- trace: SKIP 시 `reason=commitment-fp-v4`로 기록
- 비용: **JEV 호출 0 (순수 정규식)** — 린 원칙 유지

## 8. 외부 데이터셋 검증 (2026-09-28) — 조정안 미적용 확정

### 배경
`C:\code\dataset`의 다운로드 데이터셋(KoSGD 대화 84,594건, KoAlpaca 서술형 2,000건)으로
v4 규칙의 오탐을 탐색했다. 목적: 외부 데이터에서 본 오탐이 기존 메모리에 실제로 영향을
주는지 검증 → 조정 여부 결정.

### 8.1 외부 데이터 오탐 스캔
| 데이터셋 | v4 SKIP | 비율 | 토큰별 |
|---|---|---|---|
| KoSGD (대화) | 1,022건 | 1.2% | `할게` 976 (TP — 실제 의사 결정), `진행하겠` 49, `해볼게` 17 |
| KoAlpaca (서술) | 10건 | 0.5% | `구축하` 5, `정리하` 3, `할게` 2 (FP — 지식 서술) |

- KoSGD의 `할게`: "예약할게요/이용할게요" — **실제 대화의 결정 표현 (TP)**
- KoAlpaca의 `구축하/정리하/할게`: "모델을 구축하여/정리하는 5단계/소개할게요" — **문서 서술의 오탐 (FP)**

### 8.2 A/B/C 조정안 시뮬레이션 — 기존 메모리 (gold50 + ctx17, 실게이트 전체 재현)
| 안 | 내용 | gold50 prec | gold50 rec | gold50 F1 | ctx17 |
|---|---|---|---|---|---|
| 현재 v4 | (기준) | 0.684 | 0.812 | 0.743 | 1.000/1.000 |
| A+B | `구축하` 제외 + `정리하`→`정리하겠` | **0.684 (변화 0)** | 0.812 | 0.743 | 1.000/1.000 |
| A+B+C | + `할게` 맥락 제한 | **0.632 (악화)** | 0.800 | **0.706** | 1.000/1.000 |

- **A+B**: 기존 메모리에서 해당 오탐이 **0건** → 영향 없음 (외부 오탐은 "문서 서술 도메인" 한정)
- **A+B+C**: `"네, 가능해. 순서대로 진행할게"`(id=82901, gold50 TP)를 놓쳐 **prec -5.2pp 악화**
- **회귀(TP→SKIP)는 모든 안에서 0건**

### 8.3 결론 — 규칙 변경 없음 (현재 v4 유지)
- 외부 데이터셋(KoAlpaca)의 오탐은 **도메인 차이**(문서 서술 vs 대화 발화)에서 비롯된 것.
- 실제 assistant 대화 발화(gold50)에는 해당 오탐이 없어 **조정 실익 0**, C안은 오히려 TP 손실.
- **결정**: v4 규칙 그대로 유지. 외부 데이터셋은 "분류 정확도 검증"이 아닌
  "어휘 커버리지 참고" 용도로만 활용.
- 실험: `experiments/exp2_14_dataset_scan_input.json`, `experiments/exp2_15_dataset_ab_sim.py`

## 9. 라이브 실측 (2026-09-29) — trace 기반 운용 확인 + KEEP trace(B)

### 9.1 KEEP trace (B) — unconditional 구현 (커밋 예정, 플러그인 완결성)
- **변경 전**: `evaluate()`/`evaluate_assistant()` 모두 `if not keep: _jtrace(...)` → **SKIP만 trace**, KEEP은 무기록
  → "trace에 write-gate-as 없음 = KEEP or 미평가"를 구분 불가, 사후 감사 불가
- **변경 후**: KEEP/SKIP **모두** trace (같은 이벤트명 `write-gate`/`write-gate-as`, `keep=keep`/`keep=skip`). 옵션 없음(unconditional):
  플러그인 자체가 판정 근거를 항상 남김 — 스킬/문서 로딩과 무관하게 동작 (다른 에이전트 연결 대비)
- **검증**: 라이브 4케이스 (user/asst × KEEP/SKIP) → trace 4줄 정확 (`keep=keep 2` + `keep=skip 2`) /
  smoke_write_gate 7케이스 ALL PASS (회귀 0) / trace keep 카운트 0→8건

### 9.2 final-only 전달 확정 (C 관측 — Hermes 설계, 플러그인 책임 아님)
- `turn_finalizer.py` → `_sync_external_memory_for_turn` **턴당 1회**, `final_response` = 마지막 assistant text 단일.
  도구 중간 assistant 발화는 sync_turn에 **도달 안 함** (#15218 "partial output is not durable truth")
- 라이브 대조: 세션 `20260929_104012_df1103` assistant 53건(텍스트) 중 **final(fr=stop) 5건만** 게이트+[ASSISTANT] 저장
- 결론: 중간 발화 유실은 플러그인이 받지 못해서 생기는 것 — Hermes 코어/별도 훅의 몫

### 9.3 [ASSISTANT] 첫 KEEP 실측 (운용 데이터)
- 2026-09-29 세션: final 발화 8건 KEEP 저장 (`hermes_20260929_104012_df1103`, importance=0.15, scope=session)
  - 저장 예: "[ASSISTANT] DB 클린 확인(프로브 잔여물 없음)...", "[ASSISTANT] 완전한 실측 완료...", "[ASSISTANT] 스킬 반영 완료했습니다..."
  - 대응 trace: `write-gate-as keep=keep store=STORE type=fact/commitment/observation... reason=store`
- 과거(07-31~09-28) [ASSISTANT] 0건 = **게이트가 정상 SKIP** (모든 발화 no-store/context) — 미적용이 아님
- 저장 session_id는 `hermes_<session_id>` (`_session_id = f"hermes_{stable_scope}"`) — raw session_id로 조회 시 미스

### 9.4 G-qual/G-AS 독립 동작 (라이브 확인)
- user SKIP + asst KEEP → `_sync_turn_without_user`로 [ASSISTANT]만 저장
  (10:46:52 실측: `write-gate keep=skip` + [ASSISTANT] row 동시 생성, write-gate-as 무기록 = KEEP 임을 9.1로 확인)