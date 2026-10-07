# 외부 AI 검토 요청서 v4 — jev-mem 메모리 파이프라인 종합 개정판 (stage49a~82 전수, 2026-10-07)

- 작성일: 2026-10-07 (v3 2026-10-06의 개정판 — **10-06 밤~10-07 낮 신규 실측 17개 커밋 전수 반영**)
- 대상: 메모리 파이프라인 (jev-mem) — SQLite + 로컬 임베딩(bekko-a8m, 384차원) + FTS5/vec/importance/graph 4-lane RRF
  + JEV(SystemOne API) choice rerank 1콜 + soft abstain gate
- **경위**: v2 요청서 → 3종 AI 답변 → v3(10-06 23:33) → **3-AI v3 검토 반영(7f34920) + stage57~82 실측(16커밋)**
  → 본 v4에서 **최신 실측 전수 보고 + 재판정 요청**.
- **v4.1 수정 (2026-10-07, 3종 AI v4 검토 반영)**: stage61~66 실험의 confound(후보 수 60→5) 정정 —
  아래 §1.4·§4에 "production-pipeline retrieval + experimental k=5 candidate exposure"로 명시.
  "10-06 abstain 무력 = 모델 인공물" 표현 삭제, u_true/abstain율 용어 정정, 구체 수치 오기재 수정.
- **전제**: 전 수치는 실측(raw JSON·러너 경로 포함, err 0, 데몬 venv 고정, 스냅샷 고정).
  **추가 정보 요청 없이 답변 가능**하도록 자족적으로 기술.
- **구성**: §0 시스템 요약 → §1 실험 함정 → §2 사안 1~4 최종 상태(10-07 갱신) →
  §3 사안 5(pool20, 조건부 채택) → §4 사안 6(abstain 역전, 신규·핵심) → §5 사안 7(임베딩/정렬) →
  §6 사안 8(레버 소진 13종) → 부록.

---

## 0. 시스템 요약 (판단 공통 배경)

| 항목 | 값 |
|---|---|
| 저장소 | SQLite `mnemosyne.db` (working_memory 1,721행 + episodic 113행, **스냅샷 2026-10-06 동결**) |
| 임베딩 | **`bench/bekko-a8m` (384차원, 로컬 fastembed)** — 운영. gemma2 대체 후보 아래 §5 |
| 검색 | 4-lane RRF: FTS5 + vec + importance + graph → 게이트(어휘 overlap≥1, coverage 0.0) → **POOL_BUDGET=60** 컷 |
| rerank | JEV SystemOne `choice` 1콜/쿼리 — "최고 증거 1개 선택" + abstain 라벨(cN, 마지막) |
| excerpt | 전 후보 **쿼리 인지 300자 윈도우 → 150자 절단** (win-300, 10-06 채택) |
| soft gate | choice 응답의 **abstain 라벨 확률(abstain_p) > 0.3** → 빈 컨텍스트 (τ=0.3, 운영) |
| abstain 라벨(현행) | `"No candidate is usable evidence for answering the question"` — **current, 동결** |
| 실노출 | **`rows[:5]` Top-5** (jev_mem_core/pipeline.py `_render`) |
| 평가지표 | op 90 (gold 회수): hit@1/3 · noans 50 (hard): FP — 스냅샷·current·pool60 기준 |
| 평가 프로토콜 | **3-Run Majority Vote + 같은 세션 paired 비교 + production-exact** (10-07 확립) |
| 실험 환경 | JEV 호출은 `EXPLABS_API_KEY` SET 터미널/데몬 venv(`%LOCALAPPDATA%/jev-mem/venv`) 고정 |

**핵심 구조**: 코퍼스 → lane 검색 → pool 60 → JEV choice(1콜) → pick 1개 lift → **context 노출**
(abstain 시 빈 컨텍스트). 단 실제 노출은 `rows[:5]` 최대 5개 — **Top-5**.

## 1. 실험 함정 (수치 해석의 전제 — 반드시 읽기)

### 1.1 venv 오염 사건 (10-05) — 최우선 전제
- 프로젝트 `.venv`의 fastembed가 `bench/bekko-a8m` 미지원 → vec lane 0건 → abstain 27건 급증(오염)
- 데몬 venv 전환 후: abstain 27→8, hit@3 61.1%→77.8% — **이후 모든 실험은 데몬 venv 고정**

### 1.2 JEV 비결정성 → 3-Run Majority
- 동일 쿼리셋 재실행 시 ±3~5건 차이 실측 → 두 문구/두 구조 비교는 3-run majority(2/3)로 판정
- **단, 10-07 stage62에서 3-run 0플립**(아래) — 모델이 결정적으로 변함. "비결정성"은 10-06 모델 기준일 수 있음

### 1.3 ★세션 분리 측정의 함정 (10-06, stage54~56)
- stage54(base 1-run) 79/80 vs stage55(pool20 3-run) 78/79 → "-1 회귀"로 보였으나
- stage56 같은 세션 3-run paired: base도 78/79 → 차이 0 (세션 잡음)
- **교훈: 파이프라인 변경 평가는 반드시 같은 세션 paired 3-run**

### 1.4 ★모델/서버 상태 의존성 + 후보 수 confound (10-07, 3종 AI v4 검토 반영 — 최우선 전제)
- 10-06 stage48: abstain 0/60, abstain_p 0.00~0.16 → **"abstain 무력" 결론** (JEV 후보 60개 입력)
- 10-07 stage61: abstain 36/38 (94.7%), abstain_p 중앙 0.86 — **단, 러너가 `rows[:5]`로
  JEV에 후보 5개만 전달** (stage61/63/66 모두 동일)
- ⚠️ **confound**: 10-06(60개) vs 10-07(5개)는 후보 수가 다름 — "모델 변경"과 "후보 수 60→5"를
  **분리할 수 없음** (c-ai 지적, 코드 확인). stage62 3-run 결정성은 5개 조건에서의 안정성일 뿐.
- stage65/66 cap1도 "render 정책"이 아니라 **JEV 입력 후보 구성 변경 실험** (c-ai).
- **정확한 표현**: 10-07 실험 = "production-pipeline retrieval + experimental k=5 candidate exposure".
  "10-06 abstain 무력은 모델 인공물" — **삭제** (causal attribution 불가).
- **해결**: 같은 세션 60 vs 5 control (360콜) — 60도 abstain 많으면 모델 변경,
  60=0/5=36이면 후보 수 효과 (아래 §8).
- **교훈: 실험 결론은 (모델 상태 × 후보 수)에 귀속** — 러너의 JEV 입력 후보 수를 운영과 일치시켜야 함.

### 1.5 운영 무답 비율 u
- u=22.5% (query_log 87건, 10-05) → 라이브 60 사람 라벨링 → **u_true=29.8%** (10-06 보정, VALID 5건 재판정)
- 38.6%는 폐기 (B AI 지적 수용) — "~39% 무답" 문구 사용 금지

### 1.6 하드 noans FP는 실트래픽보다 해석 주의
- noans FP는 "하드-네이버" 셋 기준. 라이브 무답(이웃 존재형 IRREL)은 메커니즘이 다름 (아래 §2.4)

---

## 2. 사안 1~4 최종 상태 (10-07 갱신)

### 사안 1: abstain 라벨 문구 — **current 동결 (3-way 합의, 유지)**
- improved/v3/v4/변형 전수 기각 (stage45·47a~h). 문구 튜닝 종료 — 하단 §4에서 "노출 구조"로 이관.

### 사안 2: IDF(로컬 식별자) 필터 — **보류 + specificity risk detector로 재정의 (C AI)**
- v2 ⊇ v3 "상위호환" 표현 **철회** (별도 휴리스틱, C AI 지적 수용 — 0콜 확인: dot형 browser.backend는 v2로도 포착)
- **hard veto 금지** (Top-5에서 2~5위 식별자 있는 경우까지 죽임) → **"질문이 구체 식별자 요구 + winner가 전혀 포함 안 함" → 위험 점수만 상승**으로 재정의
- v2 세 정책 0콜 재계산 (10-07, stage57): **top5-any = winner-absent&top5-absent = 12구제·0오차단 / winner-only 13구제·1오차단** → C 설계(winner-only)가 근거

### 사안 3: noans 셋 시점 변질 + 평가 인프라 — **스냅샷 채택 (3-way 합의)**
- `mnemosyne_snapshot_20261006.db` 표준 유지
- **B-5(eval 세션 제외)는 "운영 코퍼스 위생"으로 재분류 → 구현 불필요, 우선순위 낮음** (B AI).
  실험 대화가 이웃 존재형 무답을 키울 가능성 [추측] — 월간 라이브 샘플 라벨링으로 모니터.

### 사안 4: 라이브 무답(IRREL) — **"구조적 한계" → "표현 완화 + 10-07 실험은 k=5 조건"** ★수정
- **10-06 결론 "abstain 무력·구조적 한계 확정"**: JEV 60개 후보 입력 기준 — 유효
- **10-07 stage61/62**: abstain 36/38 (94.7%) — **단, k=5 후보 입력** → 모델 변경 여부 미분리 (§1.4)
- **현재는 두 해석 모두 확정 불가** — 같은 세션 60 vs 5 control로 분리 필요 (아래 §8)
- 오주입 ~30% → ~2% 가능성 ([추측], 10-07 k=5 조건 한정 — production 적용 전 검증 필수)
- 3-AI v3 재정의 (C AI): "Jev Choice는 relative best-candidate selection에 강하나 open-set rejection에 충분한 신호 제공 못 함" — **유지** (10-07 실험으로 "거부 신호" 존재는 확인, 단 k=5 조건 한정)

---

## 3. 사안 5: pool20 — **조건부 채택 (3-AI v3 반영, "일방 개선" 철회)**

### 3.1 3-AI v3 검토 반영 (10-06, 7f34920)
1. **op-90 gold 중 rank 21~60에 2건 존재** → pool20에서 **구조적 회수 불가**:
   - `#80 deepseek 장문` gold rank 41 · `#87 camelai-serial-proxy` gold rank 36
2. **"동일 78" = 구조적 손실 2 + 우연 개선 2의 상쇄** — pool20 실질 op = **76/90**
3. **noans도 일방 아님**: 개선 10 / 동일 39 / **악화 1** (#41 web_extract)
4. 50d3 실운영 RRF에서도 rank 5·9 각 1건 (18건 중) — pool20 경계 밖 2건 추가

### 3.2 트레이드오프 (현재 실측)

| | base | pool20 |
|---|---|---|
| op hit@1 (실질) | 78 | **76** (구조적 손실 2) |
| noans FP (50, 3-run) | 21.3 | 13.0 (−39%, 개선 10·악화 1) |
| abstain | 2~3 | 2 |

### 3.3 C AI 최종 게이트 (채택 조건)
1. **production-exact live60 paired 3-run (360콜)** — stage56의 `created_at<10-05` 시간 필터 **제거**,
   production과 동일 pool 구성. `answer-protect` 추가 희생 0 + `answer-support rank>20` 0건.
2. **answer-support rank>20이 1건이라도 발견되면 pool20 전면 채택 금지 → 30/40 재평가** (롤백 규칙)
3. B AI rank-veto 시뮬(0콜) 결과 확인 (**완료**: deep pick 6건 중 gold 3건 → veto 시 정답 3 손실 → 기각)

### 3.4 A AI 주장 검증
- "op 회귀 0 + 일방 개선" → **반증** (구조적 손실 2 존재)
- "토큰 65% 압축" → criteria 수 65.6% 감소는 맞으나 **토큰 실측값 아님** (C AI) — 추정치로 명시

---

## 4. 사안 6 (신규·핵심★): "abstain 폭증" 미스터리 → 정직 abstain + 노출 한계 → 캡 트레이드오프 (10-07, stage60~66)

### 4.1 stage60~63 — abstain 폭증 미스터리 해소 (URL·모델 문제 아님) — **k=5 조건 한정**
- stage60(k 실험): abstain_p 중앙 0.86~0.94로 폭등 (어제 0.0) — **k 효과 해석 불가 → 무효**
  (단, 이 실험은 "노출 k"가 아니라 **JEV 입력 후보 수 k**로 구현 — 설계 혼동, b-ai 지적)
- stage61(base 재확인): block abstain **36/38**, abstain_p 중앙 0.86 — **rows[:5] (k=5) 입력**.
  **"어제 stage48과 동일 조건" docstring은 오류** (stage48은 60개 입력)
- stage62(3-run): 완전 결정적 (36/38·0플립) — **5개 후보 조건에서의 안정성** (모델 결정성 증거 아님)
- stage63(op+noans): op hit@1 **19** (66 abstain)·noans FP 1/50 — **k=5 조건에서의 결과**
- **원인 해석 (k=5 조건 한정)**: abstain된 사실 질문의 gold가 top5 밖 (rank 8·14·36·41) +
  top5가 규칙/프로필 행 도배 (90쿼리 중 73~89회)
- **"어제 hit 78은 규칙 행 오답 포함 과대평가" → 삭제** — hit는 gold id 일치로 계산
  (규칙 행을 골랐다고 hit가 되지 않음, b-ai 지적)
- **결론**: "정직 abstain + 노출 한계"는 **k=5 후보 입력에서의 가설** — production(60개) 적용 전 control 필수

### 4.2 stage64~65 — 규칙 행 캡 1 (op 회복, 180콜) — **JEV 입력 후보 구성 실험** (c-ai)
- 0콜 시뮬: importance 축소(0.05→0) +17, **캡 1 +35** (52/90), 캡 2 +30, 전체 제거 +32
- **분류기 없이 빈도 기반 캡** (도메인 무관 — 사용자 우려 해소)
- JEV 검증(stage65, 180콜, **k=5 입력**): **hit@1 19→66 (+47), abstain 66→14, 오차단 0** — 49건 회복
- ⚠️ **단, 이건 "최종 Top-5 노출 정책" 실험이 아니라 JEV에 전달되는 후보 집합을 5개로 축소·재구성한 실험**
  (c-ai). production은 JEV가 60개를 보므로 동일 효과 보장 없음
- 신규 abstain 4건은 gold가 캡 top5에 없어 정상 (오차단 아님)

### 4.3 stage66 — 캡 1은 라이브 방어 붕괴 (트레이드오프 확정, 220콜)

| | noans FP | 라이브 block abstain | valid/yes 오차단 |
|---|---|---|---|
| base (규칙 5) | **1/50** | **36/38 (94.7%)** | 2/22 |
| cap1 (규칙 1) | 4/50 | **4/38 (10.5%)** | 3/22 |

- **원인**: abstain은 "규칙 행 5개 경쟁"에서만 작동 — 규칙 1개면 유일 주제 일치로 pick (오주입)
- **캡 1 단독 채택 불가**: op hit 66 vs 라이브 방어 10.5% — 양립 불가 트레이드오프

### 4.4 후보 방향 (미실측)
1. **혼합 노출**: 규칙 2~3 + 사실 2~3 (규칙 경쟁 유지 + 사실 hit)
2. **decision-time 조건부**: 분류기 (도메인 한계)
3. **2콜 구조**: 규칙 5 abstain 판정 → abstain이면 사실 행만 hit (비용 2배)
4. **abstain 라벨 강화**: 규칙 5 + 사실 행 별도 신호

### 4.5 판단 요청
1. "정직 abstain + 노출 한계" 재해석이 타당한가 (vs 10-06의 "abstain 무력")
2. 캡1 트레이드오프 — 위 4개 후보 중 무엇을 먼저 실측할 가치가 있는가
3. **사실 질문 recall 병목** (top5 규칙 도배) — retrieval이 아니라 노출 정책 문제인가

---

## 5. 사안 7 (신규): EmbeddingGemma 2 평가 + 게이트 재정렬 (10-07, stage74~82)

### 5.1 EmbeddingGemma 2 (onnx-community, q4f16/q8, 768차원)
- stage74(180콜): bekko hit@1 79 vs gemma2 67 — gemma2 열위로 보였으나
- **stage76/76b/77 (교정)**: stage74는 **768d vec lane 차원 미스매치**(384d 고정 vs 768d 쿼리)로 폐기.
  work DB에 768d vec_working 재구축 후 재실측: **gemma2-q8 76/90 vs bekko 78/90 (2건 차이)**, abstain 2(≤bekko 3)
- stage78: 잔여 4건 lane 분해 — 2건은 `_filter_and_rank` 재정렬이 RRF 1위를 8~9위로 강등 (**파이프라인 정책 문제, 모델 아님**)
- **잠정 결론: gemma2는 bekko와 유사(2건 차이) — 채택/기각 미확정**. RAM/retrieval/hybrid/JEV 경로 자료: `experiments/embeddinggemma2-eval/`

### 5.2 게이트 재정렬 A/B (stage79~82)
- stage79(0콜): cur/adjusted-score 재정렬이 RRF 1위 gold를 8위 중앙값으로 강등.
  **A(RRF 순서 보존) 10→44, B(평균 순위) 10→43, C(quality 제거) 무효**
- stage80/81/82(실측): A hit@1 78 (시뮬 레버 현실화 안 됨), B hit@1 79 동률·hit@3 +1·abstain -2이나
  **noans FP 25 (현행 20~23 초과)** → **둘 다 기각, 현행 유지 확정**
- **do-not-re-run: 재정렬 정책 변경** (e20015e)

### 5.3 판단 요청
1. gemma2 추격(2건 차이) — 교체 검증을 계속할 가치가 있는가 (비용: 재구축·reindex)
2. `_filter_and_rank` 재정렬이 RRF 1위를 8~9위로 강등하는 **파이프라인 정책 문제** — 수정 방향 자문

---

## 6. 사안 8 (신규): 13번째 레버 소진 — read-path·허브 조작 전부 기각 (10-06~07)

| 레버 | 실측 | 결과 |
|---|---|---|
| 허브 행 집중도 (stage57 0콜) | **block 38건**의 pick이 단 3개 고유 id — 'default 프로필 규칙' 행 32/38 (84%) | 확인 (다운웨이트 레버 유망) |
| 허브 다운웨이트 (stage58 0콜) | hub 제거 시 다른 규칙 행 4종이 항상 대체 (38/38), VALID 5건 hub 의존 | **기각** (개별 행 조작 불가) |
| read-path meta 라벨 (stage59 120콜) | criteria '[USER-RULE]' 접두 추가 — block abstain 0/38 동일, choice_idx 1건만 변경 | **기각** (13번째 레버 소진) |
| rank-veto (stage57 0콜) | deep pick 6건 중 gold 3건 (rank 8·41·36) — **rank 8은 pool20 안쪽** (b-ai 정정) | **기각** (정답 3 손실) |
| hit@k (stage57 0콜) | k=2 = k=5 (80/90) — 노출 축소 지지 | A의 "노출 축소" 실측 지지 |
| 문형 분리 (stage57) | 라이브 60 전부 질문형 — 표본 부재 | 기각 |

- ⚠️ **용어 정정 (b-ai)**: "IRREL 38건"은 혼용 — IRREL은 **15~17건**, 38은 **block** (IRREL+PLAUS+NO).
  32/38=84%는 block 기준. IRREL 단독 abstain 비율은 현재 미보고.
- **결론: read-path·retrieval 조작으로 라이브 IRREL 해결 불가 재확인** — 남은 경로는 노출 축소(k=2~3)·
  소비 측 프레이밍뿐. **단, 10-07 k=5에서 abstain이 작동**한 것은 후보 수 효과일 수 있어 (§1.4)
  control 후 재평가.

---

## 7. 잔여 사안 우선순위 (갱신)

1. **후보 수 곡선 {5,10,20,40,60}** (b-ai) — pool20 판정 + abstain-후보수 관계 일괄 (≈2,100콜)
2. **candidate diversification** (c-ai·a-ai): 60 유지 + 규칙 2~3 + 사실 2~3 (0콜 시뮬 → ~600콜)
3. **production-exact live60 paired 3-run (360콜)** — pool20 최종 게이트 (C AI, 미실측)
4. **소비 측 프레이밍 (~57콜)** — "참고용" 블록 헤더 (B·A 수렴, 메모리 경로 밖)
5. **일일 canary (40콜/일)** (b-ai) — 모델 drift 감시
6. **월간 라이브 샘플 라벨링** (u_true·FP율·h 추적, B-5 재분류 반영)
7. **gemma2 채택 여부** — 3-way 기각 (bekko 유지) 확인. 재개 조건: RAM 압박 또는 의역 쿼리 증가

---

## 8. ★사안 9 (신규): 60 vs 5 candidate control — confound 분리 확정 (2026-10-07, stage83, 360콜)

> 3종 AI v4 검토(c-ai 최우선 제안)를 즉시 실행한 control 결과. **v4의 사안 4·6을 해소한다.**

### 8.1 결과 (live60, 같은 세션 3-run, err 0)

| 조건 | block abstain (3-run) | valid+yes 오차단 | abstain_p 중앙 |
|---|---|---|---|
| **k60** (production) | 0 / 0 / 0 (**0/38**) | 0 / 0 / 0 | **0.00** |
| **k5** (stage61~66) | 36 / 36 / 36 (**36/38**) | 2 / 2 / 2 | 0.84~0.86 |

- same snapshot / same query / same prompt / same model / **only candidate count 60 vs 5**
- 3-run 전부 0플립 — 결정적

### 8.2 판정 (사안 4·6 해소)

1. **"10-07 모델/서버 변경" → 기각** — k60에서 abstain 여전히 0/38. **모델 불변, 운영 정상**
2. **abstain 유발 요인 = JEV 입력 후보 수 60→5** (b-ai 추측 실측 입증)
3. **10-06 "abstain 무력"(60 후보 기준) 결론 유지**
4. **stage60~66(k=5) 전부 인공물** — "정직 abstain"·"노출 한계"·"캡1 트레이드오프"는
   production(60 후보)에 적용 불가
5. **러너 원칙**: JEV 입력 후보 수 = 운영(60)과 일치 — rows[:5] 실험 설계 금지

### 8.3 함의 (차기 레버)

- **pool20 채택 시 "후보 축소 → abstain 증가" 효과 동반 평가 필수** (b-ai: 후보 수 곡선 {5,10,20,40,60})
- **candidate diversification** (c-ai): 60 유지 + 규칙 2~3 + 사실 2~3 (k=5 인공물 아님, 60 기반 재설계)
- 10-07 실험들이 남긴 유효한 실측: "candidate count → abstain" 관계 (b-ai), 규칙/프로필 행의
  top-5 도배·IRREL 집중 (a-ai 슬롯 분리 설계의 근거)

### 8.4 raw

- `data/stage83_60vs5_control.json` (360 레코드), 러너 `stage83_60vs5_control.py`

---

## 부록 A: raw 자료 (전부 커밋·푸시됨, `mandutt/jev-gatemem`)

| 파일 | 내용 |
|---|---|
| `docs/review/2026-10-06_external-ai-review-request_v3_종합.md` | v3 (10-06 23:33, 사안 1~5) |
| `docs/review/2026-10-06_3AI-v3_종합+0콜검증.md` | 3-AI v3 종합 + 0콜 재검증 (7f34920) |
| `experiments/operational-golden/STAGE57_ZEROCALL_20261006.md` | stage57 0콜 검증 5종 |
| `experiments/operational-golden/STAGE58_HUB_DOWNWEIGHT_20261006.md` | stage58 허브 다운웨이트 (기각) |
| `experiments/operational-golden/STAGE59_META_LABEL_20261006.md` | stage59 meta 라벨 (기각) |
| `experiments/operational-golden/STAGE60_63_ABSTAIN_MYSTERY_20261007.md` | stage60~63 abstain 미스터리 |
| `experiments/operational-golden/STAGE64_RULE_CONDITIONAL_20261007.md` | stage64 0콜 시뮬 |
| `experiments/operational-golden/STAGE65_CAP1_20261007.md` | stage65 캡1 JEV 검증 (180콜) |
| `experiments/operational-golden/STAGE66_CAP1_TRADEOFF_20261007.md` | stage66 캡1 트레이드오프 (220콜) |
| `experiments/embeddinggemma2-eval/README.md` | gemma2 평가 전체 + 교정 기록 |
| `experiments/embeddinggemma2-eval/stage74~82_*.{py,json}` | gemma2/게이트 재정렬 raw |
| `experiments/operational-golden/RECALL_ABSTAIN_INVESTIGATION_20261005.md` §14~16 | 통합 기록 |
| `experiments/operational-golden/STAGE83_60VS5_CONTROL_20261007.md` | stage83 control 정리 |
| `experiments/operational-golden/data/stage{53~66,74~83}_*.json` | 10-06~07 전 실측 raw |

## 요청 형식
사안별로: **① 판정 (채택/기각/수정/보류 유지) ② 근거 (실측 인용) ③ 권장 다음 단계 (콜·비용·실험 설계 포함)**
를 답변해 주시면 됩니다. 반대 의견 환영. 실측 신뢰성 한계(§1, §3.3, §4.4, §5.3) 지적도 별도 부탁드립니다.
특히 **10-06 vs 10-07 모델 상태 차이**가 결론에 미치는 영향(사안 4·6)을 중점 검토 부탁드립니다.