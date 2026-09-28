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
- **context SKIP 17건 중 8건은 store=STORE였음** — 검토 결과 8건 중 5건(1·2·3·4·5)은 실질 결과물 포함 (진단/세션 상태)으로 **context 필터가 과하게 SKIP할 수 있음**. gold50(작은 표본)에선 이 패턴이 없어 recall 0.935 유지됐으나, **실운용에서 결과물 일부 누락 가능** — 추후 gold 확장 시 재평가 권장