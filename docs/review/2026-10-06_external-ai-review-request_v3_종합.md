# 외부 AI 검토 요청서 v3 — jev-mem 메모리 파이프라인 종합 (stage49a~56 전수, 2026-10-06)

- 작성일: 2026-10-06
- 대상: 메모리 파이프라인 (jev-mem) — SQLite + 로컬 임베딩(bekko-a8m, 384차원) + FTS5/vec/importance/graph 4-lane RRF
  + JEV(SystemOne API) choice rerank 1콜 + soft abstain gate
- **경위**: v2 요청서(`2026-10-06_external-ai-review-request_보류3건+abstain무력_v2.md`)에 대한
  3종 AI 답변(a/b/c-ai-보류3건-abstain무력-검토.md) 수령 → 지적사항 전부 실측 수행(stage49a~56)
  → 본 v3에서 **전수 보고 + 최종 판정 요청**.
- **전제**: 전 수치는 실측(raw JSON·러너 경로 포함, err 0, 데몬 venv 고정, 스냅샷 고정).
  **추가 정보 요청 없이 답변 가능**하도록 자족적으로 기술.
- **구성**: §0 시스템 요약 → §1 실험 함정 → §2 지적 실측 전수 보고(사안 1~4 최종 상태) →
  §3 사안 5(pool20, 신규) → §4 잔여 사안 → 부록(raw).

---

## 0. 시스템 요약 (판단 공통 배경)

| 항목 | 값 |
|---|---|
| 저장소 | SQLite `mnemosyne.db` (working_memory 1,721행 + episodic 113행, **스냅샷 2026-10-06 동결**) |
| 임베딩 | `bench/bekko-a8m` (384차원, 로컬 fastembed) — 전체 전용 |
| 검색 | 4-lane RRF: FTS5 + vec + importance + graph → 게이트(어휘 overlap≥1, coverage 0.0) → **POOL_BUDGET=60** 컷 |
| rerank | JEV SystemOne `choice` 1콜/쿼리 — "최고 증거 1개 선택" + abstain 라벨(cN, 마지막) |
| excerpt | 전 후보 **쿼리 인지 300자 윈도우 → 150자 절단** (win-300, 10-06 채택) |
| soft gate | choice 응답의 **abstain 라벨 확률(abstain_p) > 0.3** → 빈 컨텍스트 (τ=0.3, 운영) |
| abstain 라벨(현행) | `"No candidate is usable evidence for answering the question"` — **current, 동결 상태** |
| 실노출 | **`rows[:5]` Top-5** (jev_mem_core/pipeline.py `_render`) |
| 평가지표 | op 90 (gold 회수): hit@1/3 · noans 50 (hard): FP — 스냅샷·current·pool60 기준 |
| 평가 프로토콜 | **3-Run Majority Vote + 같은 세션 paired 비교** (2026-10-06 확립, §1.3) |
| 실험 환경 | JEV 호출은 `EXPLABS_API_KEY` SET 터미널/데몬 venv(`%LOCALAPPDATA%/jev-mem/venv`) 고정 |

**핵심 구조**: 코퍼스 → lane 검색 → pool 60 → JEV choice(1콜) → pick 1개 lift → **context 노출**
(abstain 시 빈 컨텍스트). 단 실제 노출은 `rows[:5]` 최대 5개 — **Top-5**.

## 1. 실험 함정 (수치 해석의 전제 — 반드시 읽기)

### 1.1 venv 오염 사건 (10-05) — 최우선 전제
- 프로젝트 `.venv`의 fastembed가 `bench/bekko-a8m` 미지원 → vec lane 0건 → abstain 27건 급증(오염)
- 데몬 venv 전환 후: abstain 27→8, hit@3 61.1%→77.8% — **이후 모든 실험은 데몬 venv 고정**

### 1.2 JEV 비결정성 → 3-Run Majority
- 동일 쿼리셋 재실행 시 ±3~5건 차이 실측 → 두 문구/두 구조 비교는 3-run majority(2/3)로 판정

### 1.3 ★세션 분리 측정의 함정 (10-06, stage54~56에서 확립)
- stage54(base 1-run, 오전) 79/80 vs stage55(pool20 3-run, 오후) 78/79 — "-1 회귀"로 보임
- **stage56 같은 세션 3-run paired**: base도 78/79 → "-1"은 세션 간 잡음, 차이 0으로 정정 (상세 §3)
- **교훈: 파이프라인 변경 평가는 반드시 같은 세션 paired 3-run** — 세션 분리 1-run/3-run 비교는 착시 가능

### 1.4 운영 무답 비율 u
- u=22.5% (query_log 87건, 10-05) → B AI 지적(abstain율≠무답율) → 라이브 60 사람 라벨링
- **1차 u_true=38.6% (stage48) → 2차 보정 29.8% (stage49c, VALID 5건 재판정)** — §2.4

### 1.5 하드 noans FP는 실트래픽보다 해석 주의
- noans FP 27/50=54%는 "하드-네이버" 셋 기준. 라이브 무답(이웃 존재형 IRREL)은 메커니즘이 다름 (§2.4·사안 5)

---

## 2. 직전 3종 AI(a/b/c) 지적 → 실측 전수 보고 + 사안 1~4 최종 상태

> v2 요청서에서 제기된 사안 1~4와, 3종 AI 답변에서 나온 지적의 **모든 후속 실측**을 정리.
> 각 사안: [v2 상태] → [v2 이후 실측] → [최종 상태].

### 사안 1: abstain 라벨 문구 (improved vs current) — **최종: current 유지 확정**

- **v2 상태**: 보류 — improved는 noans FP 27→22(-5)이나 op hit@3 78→76(-2, WHY 2건 오판). 손익분기 h에 의존.
- **v2 이후 실측**:
  - **stage47a~h** (excerpt 변형 8종 3-run): improved+win150(47c)는 noans 최강(FP 12)이나 **op hit@1 -5** → 기각.
    imphbn(47f)은 gold50 abstain 3/3 → 기각. curhb(47g)는 규칙형 noans 4건 FP → 기각. **현행(cur) 유지 확정**(§2.2 표).
  - **3종 AI 답변 공통**: "문구 튜닝 종결, current 동결, 사안 4로 이관" — 당사도 동의.
- **최종 상태**: **current 동결** (improved·v3·v4·변형 전수 기각). 프롬프트 문구 실험 종료.

### 사안 2: IDF(로컬 식별자) 필터 — **최종: v2 채택 대기 (보류 유지)**

- **v2 상태**: v2(형태 기반 `_`/숫자) 5차단·0오차단 / v3(DF≤10) 4차단·0오차단. B AI: "v3 드리프트 기각, v2 재검토".
  후속: v2·v3는 **별도 휴리스틱** (v2=형태 기반 underscore/dot, v3=DF 기반) — v2가 v3를 포함한다는 "상위호환"은 **아님** (C AI 지적 수용, 2026-10-06). v2 regex에 dot형이 있어 `browser.backend`는 잡지만, DF 기반 v3 고유 포착분(드문 식별자)은 별개. v2는 DF 비의존·드리프트 없음이 장점.
- **v2 이후 실측**: 추가 실측 없음 (운영 반영 전 타 사안 대기).
- **최종 상태**: **보류 유지** — 채택 시 `_filter_and_rank` post-choice sanity check로 구현 (0콜, τ_eff 결합 불필요 —
  stage48 실측상 abstain_p≈0이라 τ 조정 무력). 판단 재요청 (Q-잔여).

### 사안 3: noans 셋 시점 변질 + 평가 인프라 — **최종: 스냅샷 채택, B-5 eval 세션 제외 미실측(대기)**

- **v2 상태**: 스냅샷 고정(`mnemosyne_snapshot_20261006.db`, 1,721+113행, integrity OK), spoiled 5건 제외,
  신규 5건 보충(nans3_001~005, top-1 sim 0.11~0.16 검증). **B-5 "eval 세션 코퍼스 제외"는 미구현** (스냅샷으로 실질 대체).
- **v2 이후 실측**: **stage49a/B AI "13건 플립 중 8건 미설명" 지적 → 0콜 진단**: 자기참조 누수(복제 0건)·
  retrieval floor(no/yes 분포 겹침)·라이브 abstain_p(잔존 2건 저값) — **전부 기각**.
  부수: noans pool[0] = 동일 131자 프로필 행 (sim 0.23~0.27).
- **최종 상태**: 스냅샷 채택 유지. **B-5(eval 세션 제외)는 운영 코드 변경이라 별도 승인 대기** — 우선순위 판단 요청.

### 사안 4: abstain 무력 (라이브 무답 차단 불가) — **최종: 구조적 한계 확정 (레버 전수 소진)**

- **v2 상태**: stage48 라이브 60 — abstain 0/60, noans FP 100%(22/22). u_true 38.6%.
  abstain_p 0.00~0.16 (median 0.00) → soft gate τ=0.3 라이브 dead code.
- **v2 이후 실측 (3종 AI 지적 대응)**:
  - **stage49a/b (누수·측정오염 의심 3축)**: B AI "자기참조 누수? retrieval floor? 라이브 abstain_p?" →
    시점 일관 리플레이 (created_at<10-05 + cur/head100/imp 3조건 × 3-run 540콜) — **9조건 전부 abstain 0/60**.
    누수·win-300 증폭·라벨 문구 모두 기각. **원인 = closed-set Choice 구조** (C AI 진단 채택).
  - **stage49c (사람 판정 보강)**: no 22건 = IRREL 15 / PLAUS 2 / **VALID 5** (기존 라벨 오류 — 규칙형 질문에
    프로필 규칙 행이 실제 답) → **u_true 보정 38.6%→29.8%**. yes 35건 top-5 정답 포함 = YES 16(46%)/NO 19
    → C AI "recall 100%는 노출율" 입증. 라이브 실태 3분할: 정답노출 37% / 오주입 30% / **답 놓침 33%**.
  - **stage49d (pool-in-pool 스캔)**: "답 놓침" 21건 전부 **IN** — 답이 pool 60 안 rank 6~60에 존재(표본 rank 8~9).
    → **retrieval ceiling이 아니라 rerank 실패 확정**.
  - **stage50/50b (Noul answerability 500콜)**: noul은 골든 noans(0.26) 완벽 분리(FP 50→8)하나
    **라이브 IRREL(0.91)과 보호그룹(0.92+) 분포 겹침** — 구조 4종·프롬프트 3변형(v2/v3, 간격 +0.03~0.07) 전부 미달.
    → **라이브 무답(이웃 존재형) 차단은 JEV 단일 모델 판정 불가** 실증.
  - **stage50c/d (RRF lane 분해)**: "답 rank 8~9"가 시간 필터 평가 풀의 artifact임을 증명 —
    실운영 RRF는 답을 rank 1~3에 배치(15/18). **실패 지점 = JEV choice 선택, retrieval/RRF 아님**.
- **최종 상태**: **라이브 IRREL 차단은 구조적으로 불가 확정** — 소진 레버: 라벨 문구 2종·excerpt 8종·τ 스윕·
  noul 구조 4종·noul 프롬프트 3변형·retrieval floor·시점 필터·게이트 완화·쿼리 확장(write/read-path) = **9종 +
  이번 3구조**(§3) = 12종. 남은 선택지 판단 요청 (§4).

---

## 3. 사안 5 (신규): v2 미실측 3건 실측 + pool20 채택 판단 ★본 요청의 핵심

> v2 요청서에서 "미실측"으로 남았던 3건(A-7 pool20 / B-4 dual / C-4 two_call)을 전부 실측.
> 결과: **pool20만 유일한 실용 후보** → 채택 판단 자문.

### 3.1 stage53 — 3건 실측 (100쿼리 {live 60 + op 20 + noans hard 20}, 500콜, err 0)

| 구조 | IRREL 차단 (17) | 정답희생 (38) | noans hard FP (20) |
|---|---|---|---|
| base (현행) | 0 | 0 | 13 |
| pool20 (A-7) | 0 | 0 | 8 |
| dual (B-4) | 1 | 0 | 7 |
| two_call (C-4) | 2 | 0 | 5 |

- **라이브 IRREL 차단은 3구조 모두 여전히 미미** (0~2/17) — 사안 4의 한계 재확인.
- **정답희생 0** — 전부 안전.
- 하드 noans FP는 3구조 모두 절반 이상 개선 (13→5~8): pool20=softmax 집중(A 지지), dual=라벨 분리(B 지지),
  two_call=winner 재검증(C 지지, 최강).

### 3.2 stage54 — op-90 회귀 1-run (360콜, err 0)

| 구조 | hit@1 | hit@3 | abstain |
|---|---|---|---|
| base | 79 | 80 | 3 |
| pool20 | 78 | 79 | 2 |
| dual | 77 | 78 | 6 |
| two_call | 76 | 77 | 7 |

- dual·two_call은 **abstain +3~4 (과다거부)** → op 손실 > FP 이득 → 기각.
- pool20만 -1 → 유일한 후보 (단, 세션 분리 1-run이라 잡음 가능 — §1.3).

### 3.3 stage55 — pool20 3-run (270콜, err 0)

- 3-run 전부 hit@1 78 / hit@3 79 / abstain 2 — **완전 동일, 비결정성 0**.
- → "-1"이 실질로 보였으나, **세션 분리 측정의 한계**였음 (§1.3).

### 3.4 stage56 — ★풀 비교 (같은 세션 3-run paired, op 90 + noans 50, 840콜, err 0)

| 구조 | hit@1 (3-run) | hit@3 | abstain | noans FP (3-run) |
|---|---|---|---|---|
| base | 78 / 78 / 78 | 79 / 79 / 79 | 2·2·3 | 21 / 22 / 21 (평균 **21.3**) |
| pool20 | 78 / 78 / 78 | 79 / 79 / 79 | 2·2·2 | 13 / 13 / 13 (평균 **13.0**) |

- **op hit@1/3: 두 구조 완전 동일 (78/79)** — stage54 base 1-run 79/80은 세션 잡음. **pool20의 "-1"은 착시**.
- **noans FP: 21.3 → 13.0 (−8.3, −39%)** 같은 세션 확정.
- **쿼리별 majority 대조: 차이 4건뿐, 2:2 상쇄** (pool20 개선: #58 KoDialogBench·#72 pi 프록시 / 손실:
  #80 deepseek 장문·#87 camelai-serial-proxy) — **체계적 손실 없음**, 무작위 변동 수준.
- 참고: stage53 noans 20 base 13 vs stage56 noans 50 base 21.3 — **noans 셋 크기 의존성** 확인.

### 3.5 요청 사항 (사안 5)

1. **pool20 채택 타당성** — 같은 세션 paired 3-run에서 op 무회귀(78/79 동일) + noans FP −39%. 다만:
   - (a) pool 60→20은 **retrieval 커버리지 상한을 낮추는 구조 변경** — 답이 rank 21~60에 있는 케이스는
     이전엔 choice가 건질 기회가 있었으나 이제 영구 소실. stage49d("답 놓침 21건 전부 pool 안 rank 6~60,
     표본 rank 8~9")와 stage50c/d("실운영 풀 답 rank 1~3, 15/18")를 종합하면 실손실 0~2건 추정이지만,
     **op-90 셋 기준 "답 rank 21~60" 케이스가 0건이어서 실측에서 드러나지 않았을 수 있다**는 우려.
     이 셋 바깥에서의 위험을 어떻게 평가해야 할까?
   - (b) noans FP "개선"이 실질 이득인지 — base FP 21.3건은 "답 없는데 메모리 노출". 표본 50의 하드 noans는
     **라이브 무답(이웃 존재형 IRREL)과 메커니즘이 다름** (§3.1: IRREL 차단 여전히 0~2/17).
     **하드 noans FP 감소가 라이브 오주입 감소로 이어질 근거가 있는지**, 아니면 격리된 이득으로 봐야 하는지.
   - (c) 채택한다면 릴리스 게이트 요건 — 같은 세션 paired 3-run + 라이브 60 교차 외 추가 검증이 필요한지.
2. **dual/two_call 기각 확정에 이견이 있는지** (op abstain +3~4가 결정적).
3. **부수 이득 평가**: criteria 61→21 → 토큰 ~35% 절감 + latency 감소. 비용 관점에서도 채택을 지지하는지.

---

## 4. 잔여 사안 우선순위

1. **라이브 IRREL(이웃 존재형 무답) 차단 불가** — 12종 레버 소진. 남은 선택지 (부분 채택 noul<0.5 /
   판정자 교체 / 상위 1~3 [LOW_CONF] 노출) 중 실측상 유망한 것이 있는지, 아니면 **완전 포기**하고
   "하드 noans 방어만 있는 구조"로 갈지 판단 요청.
2. **B-5 eval 세션 코퍼스 제외** — v2의 미실측 건 (평가 쿼리·실험 대화가 메모리에 쌓여 noans 셋을 변질).
   스냅샷 고정으로 실질 대체 중 — 별도 구현 없이 수용해도 되는지 (우선순위 낮음 판단 포함).
3. **사안 2 (IDF v2) 채택 여부** — 0콜 구현, 오차단 0, 드리프트 없음. 채택 가치 판단.
4. **사안 1 (라벨) current 동결** — 이견 없는지 (3종 AI 공통 권고와 일치).

---

## 5. 부수 교훈·운영 (참고용)

- **JEV 키별 한도 독립 실증**: 키1 일일 소진(47,618,188/47,619,047) 시에도 키2는 새 할당으로 동작.
  시작 전 두 키 1콜 probe → 잔여 키로 시작. 429 본문 'daily free allowance' → 해당 키를
  `rot.exhausted_until`에 넣어 정각까지 제외 (on_429는 순환만, daily 제외 명시 필요).
  분당 240콜 / 시간당 0.5$=11.9M / 일일 2$=47.6M — 3종 한도 모두 키별.
- 메모리 경로 LLM = JEV 전용 원칙 유지 (일반 LLM 간섭 없음).

---

## 부록 A: raw 자료 (전부 커밋·푸시됨, `mandutt/jev-gatemem`)

| 파일 | 내용 |
|---|---|
| `docs/review/2026-10-06_external-ai-review-request_보류3건+abstain무력_v2.md` | v2 요청서 (사안 1~4 전체) |
| `a/b/c-ai-보류3건-abstain무력-검토.md` | 3종 AI 답변 (2026-10-06, 사용자 제공) |
| `experiments/operational-golden/STAGE53_MISSED3_20261006.md` | stage53 (미실측 3건) |
| `experiments/operational-golden/STAGE54_OP90_REGRESS_20261006.md` | stage54 (op-90 1-run) |
| `experiments/operational-golden/STAGE55_POOL20_3RUN_20261006.md` | stage55 (3-run) |
| `experiments/operational-golden/STAGE56_FULL_COMPARE_20261006.md` | stage56 (풀 비교) |
| `experiments/operational-golden/RECALL_ABSTAIN_INVESTIGATION_20261005.md` §12~14 | 전체 통합 기록 |
| `experiments/operational-golden/data/stage{53,54,55,56}_*.json` | raw (500/360/270/840콜) |
| `experiments/operational-golden/stage{53,54,55,56}_*.py` | 러너 (재현 가능) |
| `experiments/operational-golden/*` (stage49a~50d raw·문서) | 사안 4 후속 실측 전체 |

## 요청 형식
사안별로: **① 판정 (채택/기각/수정/보류 유지) ② 근거 (실측 인용) ③ 권장 다음 단계 (콜·비용·실험 설계 포함)**
를 답변해 주시면 됩니다. 반대 의견 환영. 실측 신뢰성 한계(§1, §3.5) 지적도 별도 부탁드립니다.