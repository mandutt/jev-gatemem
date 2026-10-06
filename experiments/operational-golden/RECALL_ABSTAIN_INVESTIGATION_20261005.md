# recall-strengthening & abstain 병목 조사 — 2026-10-05 전체 리포트

SoT: `C:/Users/mandu/hermes-made/jev-memory-middleware/experiments/operational-golden/`
모든 raw: `data/` (아래 파일명 참조)
판정: 완료 (오염 발견 → 정상 재측정 → 다음 단계 선정)

---

## 0. TL;DR

- hippo-memory 비교에서 출발한 recall-strengthening 파일럿(Run R)과 abstain 원인 조사(stage16~18).
- **중대 방법론 결함 발견**: 실험 러너를 프로젝트 `.venv`(jev-memory-middleware/.venv)로 실행했는데, 이 venv의 fastembed가 `bench/bekko-a8m`을 **지원하지 않아 vec lane이 항상 0건**이었다. → abstain 27건·"gold pool 밖" 분석 전부가 **vec lane 죽은 상태의 오염 결과**.
- 데몬 venv(`AppData/Local/jev-mem/venv`, sitecustomize가 모델 강제)로 재실행하자:
  - **hit@3 61.1% → 77.8%** (op 90)
  - **abstain 27건 → 8건** (gold가 vec 40위 안에 이미 있다는 stage19 실측과 일치)
- stage18 Doc2Query(9router 일반 LLM)는 **원칙 위반(일반 LLM 간섭) + 오염 데이터 기반** → 폐기.
- **진짜 병목**: abstain 8건 중 3건은 gold가 pool에 있는데 JEV가 abstain을 고른 'abstain 오판' (upstream 404, gold50, S8). stage20~27에서 excerpt 확장 + abstain_p soft gate로 해결 → **win-300 + τ=0.3 채택** (2026-10-06 운영 반영).

---

## 1. 배경

- https://github.com/kitfunso/hippo-memory (bio-decay 메모리, 747★) 비교에서 채용 후보 도출:
  1. retrieval strengthening (recall_count 기반) ❌
  2. POOL_BUDGET 상향 ❌ (stage14/15 이미 기각, abstain 전수로 재확인)
  3. abstain 27건 = "gold가 pool 밖" → lane/임베딩 문제 → Doc2Query 후보
- 비교 상세: 스킬 `references/hippo-memory-comparison.md`

## 2. 실험 타임라인

| # | 실험 | venv | 결과 | 상태 |
|---|---|---|---|---|
| Run R | recall 가중 α 스윕 (180콜) | 프로젝트 .venv | hit@3 61.1%, abstain 27 | **오염 → 무효** |
| stage16 | abstain 27건 gold 위치 0콜 스캔 | 프로젝트 .venv | gold 풀밖 23건 | **오염 → 무효** |
| stage17 | lane별 원인 분해 (0콜) | 프로젝트 .venv | vec_rank=None → "vec 실패" | **오염 → 무효** (vec 죽음) |
| stage18 | Doc2Query 파일럿 (9router, 23콜) | 프로젝트 .venv | gold top-40 20/23 | **오염 + 원칙 위반 → 폐기** |
| stage19 | gold vec rank (0콜) | **데몬 venv** | 23건 전부 rank≤400, 21건 ≤40 | ✅ 정상 |
| Run R 재실행 | recall 가중 (180콜) | **데몬 venv** | **hit@3 77.8%, abstain 8** | ✅ 기준선 |

## 3. 방법론 결함 (가장 중요한 교훈)

- **증상**: 프로젝트 .venv의 fastembed가 `bench/bekko-a8m`·`hotchpotch/bekko-embedding-v1-a8m` 모두 미지원 (모델 37개, bekko 0건). 데몬 venv는 38개 + bekko 지원.
- **결과**: `emb_mod.embed()` 실패 → `_wm_vec_search`가 빈 결과 → **vec lane 0건** → build_lane_pool이 FTS/imp/graph만으로 구성.
- **오염 범위**: Run R, stage16, stage17, stage18 전부. abstain 27건은 "vec lane 0건" 상태의 정상 동작이었음.
- **교훈**: 벤치/실험은 **반드시 데몬 venv(`%LOCALAPPDATA%/jev-mem/venv`)로 실행**하라. 프로젝트 .venv에는 임베딩 모델이 없다. (스킬 `references/recall-experiment-lessons.md`에 기록)

## 4. 정상 기준선 (데몬 venv, op 90건)

| 지표 | 값 |
|---|---|
| hit@3 | **70/90 (77.8%)** |
| abstain | 8 |
| miss (비-abstain) | 11 |
| err | 1 (InterfaceError, 일시) |

### abstain 8건 상세

| 쿼리 | pool | 비고 |
|---|---|---|
| upstream 404 별칭 | 32 | gold pool 밖? |
| 리뷰 전용 턴 커밋 | 40 | gold pool 안 (abstain 오판 후보) |
| 구현 확인 규칙 | 40 | gold pool 안 |
| evidence 규칙 | 40 | gold pool 안 |
| gold50 기준선 수치 | 40 | gold pool 안 |
| shutdown API | 40 | gold pool 안 |
| S8 시나리오 실패 | 40 | gold pool 안 |
| Exa 왜 안 써 | 4 | gold pool 밖 (pool 자체가 작음) |

→ **6/8이 gold가 pool에 있는 abstain 오판** (JEV choice가 abstain 라벨을 과도하게 선택)

### miss 11건 상세

- gold_rank 4/5/7/17 (JEV가 다른 후보 선호): 4건 (키리스 웹, 프록시 모델, 데스크톱-텔레그램, X1 bekko, webdriver 숨김 → 5건)
- gold_rank None (pool 밖): camelAI 라우팅, provider, TimeoutExpired, 18080 프록시, 전환 전 문제 → 5건

## 5. 폐기된 접근

- **stage18 Doc2Query (9router)**: 일반 LLM(deepcombo)을 메모리 경로에 사용 = 사용자 원칙 위반 ("메모리에 일반 LLM 간섭 금지, JEV-only / JEV+임베딩"). JEV는 SystemOne decision 프로토콜이라 text 생성 불가(400 확인). → **Doc2Query는 구조적으로 부적합, 폐기.**
- stage18 결과(9router 재표현 → gold top-40 20/23)는 오염 데이터 기준이라 무의미.

## 6. excerpt 확장 조사 (stage20~24) — 최종 기각

### 동기
abstain 8건 중 gold가 pool에 있는 3건(upstream 404, gold50, S8)은 gold_len 329~436자로 **head-100 excerpt에서 답이 잘려** abstain했을 가능성.

### 실험
| stage | 내용 | 결과 |
|---|---|---|
| stage20 | excerpt 100→300 윈도우, 9건(abstain 3+rermiss 6) | **5건 gold 1위 회복**, 2건 악화 |
| stage21 | op 90 전체 win-300 | **hit@3 70→76 (+6)**, abstain 3→0, 악화 1건 |
| stage22 | noans hard 50건 win-300 | **오주입 13→20 (+7)** → 전체 적용 기각 |
| stage23 | 오주입 10건 원인 분해 | **전부 "과거 이력/시점" 질문이 주제 근접 미끼** (PLAUS/IRREL) |
| stage24 | 조건부 2콜 (1차 head-100 → abstain만 win-300 + pair 게이트) | noans 18 (게이트가 3건만 차단), gold 회복 2건 유지, gold50은 게이트가 정답 차단 → **순효과 -3, 기각** |

### 판정: excerpt 확장 단독 접근은 기각 (2026-10-05) — soft gate 결합으로 재채택 (2026-10-06)

- **1차 기각 (stage22~24)**: 골드 회복(+6~7)과 noans 오주입(+7~10)이 동일 메커니즘(excerpt 정보량)으로 충돌 — "순효과 0 이하"로 판정.
- **재판정 (stage25~27, B AI 지적)**: "op +6/90 vs noans +7/50"은 **분모가 다른 두 세트를 건수로 단순 합한 오류**. 실 운영 무답 비율 u=22.5% (query_log 실측)를 반영한 harm-가중 계산에서 **모든 h에서 기대 순이득 양수** 확인.
- **해결**: choice 응답의 abstain_p (probabilities) 활용 — abstain_p>0.3이면 빈 컨텍스트로 되돌리는 **soft gate**로 noans 비용 상쇄:
  - win-300 단독: noans 22 FP → **τ=0.3 적용 시 16 FP** (hard), 독립 easy 셋 0 FP
  - op 손실 0 (hit@3 77 유지)
- **1차 기각 원인**: abstain 라벨 확률(confidence)을 파기하던 `_jev_choice` — C AI가 지적한 "이미 받은 정보를 버림"이 noans 방어를 막고 있었음.

### 최종 상태 (2026-10-06 — win-300 + soft abstain gate 채택)

- **채택**: excerpt 전면 "쿼리 윈도우 300자" + abstain_p>0.3 soft gate (stage26/27 실측, 운영 반영 2026-10-06)
- op hit@3 77/90 (85.6%), hit@5 80/90 (88.9%), abstain 3
- noans: hard 16 FP (τ=0.3), 독립 easy 셋 0 FP
- stage22의 "순효과 0 → 기각"은 분모 다른 두 세트를 건수로 단순 합한 오류 — B AI 지적으로 harm-가중 재판정 후 채택

## 7. 파일 목록

- 러너: `run_r_recall_strength.py`, `stage16_abstain_gold_pos.py`, `stage17_poolout_23_lane_diag.py`, `stage18_doc2query_pilot.py`, `stage19_gold_vec_rank.py`, `stage20_excerpt300_pilot.py`, `stage21_excerpt300_op90.py`, `stage22_noans_excerpt300.py`, `stage23_noans_fp_inspect.py`, `stage24_conditional_win300_gate.py`
- raw: `data/runR_recall_strength_raw.json` (데몬 재실행분), `data/stage16_abstain_gold_pos.json`, `data/stage17_poolout_23_lane_diag.json`, `data/stage18_doc2query_pilot_9router.json` (폐기), `data/stage19_gold_vec_rank.json`, `data/stage20_excerpt300_pilot.json`, `data/stage21_excerpt300_op90.json`, `data/stage22_noans_excerpt300.json`, `data/stage24_conditional_win300_gate.json`
- 사람 판정: `data/stage16_poolout_23_verdicts.json` (22 ok / 1 ambiguous — 회수 실패 라벨 문제 아님 확정, 단 오염 기준)
- 로그: `data/runR_daemon_rerun.log`

## 8. 원칙 재확인

- 메모리 경로 LLM = **JEV만** (SystemOne), 보조 = 임베딩(bekko-a8m, 로컬 0원). 일반 LLM(9router 등) 사용 금지 — stage18은 위반 사례.
- 실험 venv = **데몬 venv만**. 프로젝트 .venv 금지 (임베딩 부재).

## 9. excerpt 윈도우 계열 전수 조사 (2026-10-06, stage47a~h) — **모두 기각**

3차 AI 검토(B) 제안 "150자 직접 윈도우·head+겹침"을 8단계 실측. **전부 3-run에서 붕괴**:

| 단계 | 변형 | 1-run | 3-run 판정 |
|---|---|---|---|
| 47a | win150 (겹침 150 직접) | hit@3 +1, FP -3 | WHY 구제는 1-run 착시 |
| 47b | win150 3-run | — | 마우스만 확정, gemini/codex 열위 → 기각 |
| 47c | improved+win150 | FP 12 | noans 최강 but op hit@1 -5 |
| 47d | head+겹침 | 전 지표 개선 | WHY abstain (겹침=head 겹침) |
| 47e | head+겹침 non-overlap | hit@1 75/@3 79/FP 14 | WHY 3건 3/3 구제 확정 |
| 47f | imphbn 3-run | — | gold50 0/3 abstain (improved 라벨 효과) |
| 47g | curhb (current+head겹침) | WHY+gold50 모두 해결 | 규칙형 noans 4건 FP |
| 47h | 최종 3-run 교차 | — | **둘 다 기각 — WHY 3건 vs 규칙형 4건+gold50 1건 = 순손실** |

- **결론**: 현행(300→150 절단 + current 라벨)이 유일한 균형. WHY 질문 구제는
  excerpt가 아닌 다른 레버로만. 이 계열 재실험 금지.
- **러너 교훈 3건**: ① POOL_BUDGET 캡 누락 → criteria 64+ 400 (47에서 75건 폐기)
  ② 장기 러너 stdout 파일 리다이렉트 필수 (백그라운드 kill 3회) ③ 1-run ±3~5는
  반드시 3-run 확인.

## 10. 라이브 60쿼리 교차 검증 (2026-10-06, stage48) — **abstain 무력 발견**

trace 실사용 쿼리 60건을 사용자 판정(yes/no/maybe)과 교차. **버그 3건 수정 후**:
- `_filter_and_rank` 기본값 (2, 0.30) → **(1, 0.0) 통일** (core만 완화돼 있던 것)
- 러너 row_factory 누락 → pool 2~9 (abstain 93% 오염)
- load_queries trace 재수집 → 시트 하드코딩

**최종 — 사용자 판정 교차 (cur)**:
- 답 있음 35건 → **pick 35 (recall 100%)** ✅
- 답 없음 22건 → **pick 22 (noans FP 100%)** ❌
- **abstain 0건** — abstain_p 전부 0.00~0.16
- **u_true = 38.6%** (사용자 판정, B 추정 범위 20~41%의 상단)

**결론**: 회수는 100%로 우수하나, **abstain 라벨이 라이브 쿼리에서 완전 무력** —
골든셋 하드 noans에서만 작동. 유사 메모리가 있으면 JEV가 무조건 답을 고름.
라이브 트래픽 ~39%(무답)에서 전부 오주입 중. improved 라벨도 abstain 1/60뿐 →
**라벨 문구가 아닌 abstain 메커니즘 재설계 필요**. 상세: `STAGE48_LIVE60_CROSS_20261006.md`.

## 11. 측정 유효성 진단 + 시점 일관 재실측 (2026-10-06, stage49a/b) — **무력 최종 확정**

v2 요청서에 대한 3종 AI 검토(10-06)에서 B AI가 stage48 자체의 측정 오염을 의심.
3축 진단 + 시점 일관 재실측으로 모두 기각됨.

### stage49a (0콜 진단) — `STAGE49A_LEAK_DIAGNOSIS_20261006.md`

| 가설 | 검사 | 판정 |
|---|---|---|
| 자기참조 누수 | near-dup(sim≥0.85)/문자열 복제: no 22·yes 35 전부 0건, 10월 생성 후보 0건 | **기각** |
| retrieval floor 컷(0.25) | floor<0.25: no 77% vs yes 49% — 분포 겹침, no만 잡지 못함 | **기각** |
| 라이브 abstain_p는 높았다 | trace 로테이션으로 쌍비교 불가 (잔존 2건은 0.13/0.12 저값) | 확증 불가 |

- 부수: 무답 표본 5건 모두 pool[0]이 동일 131자 프로필 규칙 행 (sim 0.23~0.27 저유사 무의미 상위 반환)

### stage49b (시점 일관 리플레이, 540콜 3조건×3-run, err 0) — `STAGE49B_TIMECONSIST_20261006.md`

`created_at < 2026-10-05` 필터(라이브 시기 135행 배제) 후 cur/head100/imp 3조건 재실측:

| cond | no(22) abstain | yes(35) abstain | abstain_p med/max |
|---|---|---|---|
| cur | 0/0/0 | 0/0/0 | 0.00 / 0.17 |
| head100 | 0/0/0 | 0/0/0 | 0.01 / 0.17 |
| imp | 0/0/0 | 0/0/0 | 0.01 / 0.24 |

- **자기참조 누수 기각** (필터 후에도 abstain 0) / **win-300 증폭 기각** (head-100에서도 0) / **라벨 무력 재확인**
- **최종 확정**: abstain 0/60은 실재. 원인 = closed-set Choice(61-option softmax)에서 abstain은
  calibrated answerability가 아니라 상대 경쟁의 잔여 확률 (C AI 구조 진단 채택)
- **soft gate τ=0.3은 라이브 dead code 확정** — τ 조정 실험 중단

### 다음 단계 (3종 AI 검토 수렴안)

1. 라벨 보강: no 22건 해로움(VALID/PLAUS/IRREL) + yes 35건 top-5 정답 포함 여부
2. **stage50: Noul answerability 실험** — winner-Noul soft risk(2콜) vs Noul top30 병행(1콜),
   200-query 벤치(op90+noans50+live60) 1-run → 생존자만 3-run. **Noul 자체는 stage32에서
   answerability 신호로 실측된 바 있음(noul_top<0.5로 FP 16→8) — 기각된 것은 pool30 축소 구조**
3. 라이브 60을 회귀 검증 셋으로 고정 (릴리스 게이트: 스냅샷 통과 + 라이브 교차 통과)

## 12. 라벨 보강 + pool-in-pool 스캔 (2026-10-06, stage49c/d) — 두 축의 실체 확정

### stage49c 라벨 보강 (사람 판정, `stage49c_label_booster.html`)

no 22건의 top-1 해로움 + yes 35건의 top-5 정답 포함 여부를 사용자가 판정:
- **no 22건 = IRREL 15 (68%) / PLAUS 2 (9%) / VALID 5 (23%)**
  - IRREL 68%가 실재 해로움 (B AI "오주입이 실제 해로운가" 의심에 대한 답)
  - **VALID 5건 = 기존 'no' 라벨이 틀렸음** — 전부 규칙/선호형 질문(#9 반말, #11 자동시작,
    #19 신규타입, #21 언어습관, #52 라벨언어)에 JEV가 프로필 규칙 행을 pick한 것이 옳은 동작
  - 판정 원칙 확립: **시트에 표시된 excerpt(400자)만으로 판정** (운영이 실제로 노출하는 것 기준)
    — 원문 뒷부분에 답이 있어도 에이전트는 못 받으므로 무효
- **yes 35건 = top-5 정답 포함 YES 16 (46%) / NO 19 (54%)** — C AI "recall 100%는 노출율" 지적 입증
- **u_true 보정: 38.6% → 29.8%** (IRREL+PLAUS 17/57; VALID 5건은 원래 답 있는 질문)

### 라이브 실태 최종 (57 유효 쿼리)

| 상태 | 건수 | 비율 | 원인 |
|---|---|---|---|
| 정답 노출 성공 | 21 | 37% | — |
| 해로운 오주입 (IRREL+PLAUS) | 17 | 30% | **abstain 무력** |
| 답 있는데 놓침 (yes-NO) | 19 | 33% | **rerank 실패** |

### stage49d pool-in-pool 스캔 (`stage49d_poolinscan.html`)

**"답 있는데 놓침" 19+2건의 rank 6~60 후보를 사용자 판정 → **IN 21/21 (100%)** —
retrieval ceiling이 아니라 rerank 실패로 해석했다. **단 ⚠️ 후속 실측(stage50c/d, 0콜)으로 정정**:
이 pool은 **시점 필터(created_at<10-05) 적용 평가용 pool**이고, 실운영 pool(필터 없음)에서는
**답이 RRF 1~3위**였다 (18건 중 15건, stage50d3). "rank 8~9"는 시점 필터 pool의 인공물 —
**실제 원인은 RRF가 아니라 JEV choice가 답(1~3위)을 못 고르는 rerank 실패**로 최종 확정.
상세: STAGE50CD_RRF_LANE_20261006.md

## 13. Noul answerability 실험 (2026-10-06, stage50/50b) — **기각·소진 확정**

### stage50 (200쿼리 × 1-run, `stage50_noul_answerability.py`, err 0)

choice+noul30 1콜/쿼리, 후처리로 4구조 비교. **cls별 noul_top 중앙값**:

| cls | noul_top |
|---|---|
| noans_hard (골든) | **0.26** — 완벽 분리 ✅ |
| **live_irrel** | **0.91** — 보호그룹과 완전 겹침 ❌ |
| live_valid / yes_miss / op | 0.92~0.94 |

- noul_top<0.5 게이트: **noans FP 50→8 (42건 차단)**, op abstain 5 — 골든셋 방어는 강력
- 그러나 **IRREL 차단 1/15 (합격선 5 미달)**, 희생 0
- 구조 변형(noul_top/noul_win/복합) 전부 동일 — **구조로 해결 불가**

### stage50b 프롬프트 3변형 (100쿼리 × 3 = 300콜, `stage50b_noul_prompt_variants.py`, err 0)

- v1 현행 / v2 구체성 강조("specific fact...same-topic is NOT an answer") / v3 부재 판정(역방향)
- **분리 간격(op−irrel): +0.03 / +0.03 / +0.07 — 프롬프트로 안 벌어짐**
- v2는 역전 발생: valid(0.83) < irrel(0.87) — 구체성 강조가 정답까지 깎음
- τ 게이트 어느 지점에서도 "IRREL ≥5 차단 + 희생 ≤1" 동시 만족 없음

### 판정 (stage50/50b 종합)

**라이브 무답 = "주제 근접 이웃이 존재하는 무답"이라 JEV가 (choice든 noul이든, 어떤
프롬프트로든) 0.85~0.94의 높은 점수를 부여** — relevance와 answerability의 구분이
모델 수준에서 불가. 골든 noans(이웃 부재형)만 분리 가능.

**소진 완료 레버 9종**: abstain 라벨 문구 2종 · excerpt 윈도우 8종(stage47a~h) ·
soft gate τ · noul 구조(1콜/2콜/하이브리드) · noul 프롬프트 3종 · retrieval floor ·
시점 필터 · 게이트 완화 · 쿼리 확장(write/read-path).

**남은 선택지**: ① 부분 채택 — noul_top<0.5를 골든셋 회귀 방어로만 추가 (noans FP 50→8,
op −5, 라이브 영향 미미) ② 판정자 교체 (일반 LLM 금지 원칙과 충돌) — **보류, 외부 AI 문의 예정**

### raw·재현
- `data/stage49c_label_booster_input.json` + 사용자 판정 JSON (Downloads)
- `data/stage49d_poolinscan_input.json` + 판정 JSON
- `data/stage50_noul_answerability.json` (200), `data/stage50b_noul_prompt_variants.json` (300)
- 러너: `stage49c`/`stage49d_poolinscan`/`stage50_noul_answerability`/`stage50b_noul_prompt_variants.py`
- 시트: `stage49c_label_booster.html`, `stage49d_poolinscan.html`
## §14. 미실측 3건 실측 (2026-10-06) — pool20/dual/two_call + op-90 회귀 + 풀 비교

### 14.1 stage53 — 3종 AI 미실측 3건 (500콜, err 0)

3종 AI 검토 요청서(v2)에서 "미실측"으로 남았던 3건을 100쿼리(live 60 + op 20 + noans 20) 동일 벤치에서 실측:

| 구조 | IRREL 차단(17) | 정답희생(38) | noans hard FP(20) |
|---|---|---|---|
| base (현행) | 0 | 0 | 13 |
| pool20 (A-7) | 0 | 0 | 8 |
| dual (B-4, 두 라벨) | 1 | 0 | 7 |
| two_call (C-4, 2콜) | 2 | 0 | 5 |

- **라이브 IRREL(이웃 존재형 무답) 차단은 3구조 모두 여전히 미미** (0~2/17) — abstain 무력의 구조적 한계 재확인.
- **정답희생 0** — 전부 안전.
- **하드 noans FP는 3구조 모두 절반 이상 개선** (13→5~8): pool20=softmax 집중(A AI 가설 지지), dual=라벨 분리(B 지지), two_call=winner 재검증(C 지지, 최강).
- **양분 확정**: 구조 개선은 "하드 noans(이웃 부재)" 방어엔 유효, "라이브 무답(이웃 존재)"엔 미미.

### 14.2 stage54 — op-90 회귀 1-run (360콜, err 0)

| 구조 | hit@1 | hit@3 | abstain |
|---|---|---|---|
| base | 79 | 80 | 3 |
| pool20 | 78 | 79 | 2 |
| dual | 77 | 78 | 6 |
| two_call | 76 | 77 | 7 |

- dual·two_call은 abstain +3~4 (과다거부) — op 손실 > FP 이득 → 기각.
- pool20만 -1 (비결정성 범위) — 유일한 후보.

### 14.3 stage55 — pool20 3-run (270콜, err 0)

3-run 전부 hit@1 78 / hit@3 79 / abstain 2 — **완전 동일, 비결정성 0**.
→ pool20의 -1은 "실질적·재현 가능"으로 보였으나, 이는 세션 분리 측정의 한계였음.

### 14.4 stage56 — 풀 비교 (같은 세션 3-run paired, 840콜, err 0) ★최종

| 구조 | hit@1 | hit@3 | abstain | noans FP(50) |
|---|---|---|---|---|
| base | 78/78/78 | 79/79/79 | 2·2·3 | 21/22/21 (평균 21.3) |
| pool20 | 78/78/78 | 79/79/79 | 2·2·2 | 13/13/13 (평균 13.0) |

- **op hit@1/3 완전 동일 (78/79)** — stage54 base 1-run 79/80은 세션 잡음. **pool20의 "-1 회귀"는 착시**.
- **noans FP 21.3 → 13.0 (−8.3, −39%)** 같은 세션 확정.
- **쿼리별 majority: 4건만 차이, 2:2 상쇄** (pool20 개선: #58 KoDialogBench·#72 pi 프록시 / 손실: #80 deepseek 장문·#87 camelai-serial-proxy) — **체계적 손실 없음**.
- **최종 판정: pool20 채택 근거 확정 — op 무회귀 + noans −39% = 일방 개선** (h 불필요).
- 부수 이득: criteria 61→21 → 토큰 ~35% 절감 + latency 감소.
- **단, 코드 반영 보류** — 다른 AI 검토 요청과 함께 진행 예정 (2026-10-06 사용자 지시).

### 14.5 방법론 교훈 (중요)

**세션 분리 1-run/3-run 비교는 비결정성에 취약** — stage54(base 1-run 79/80) vs stage55(pool20 3-run 78/79)
의 -1이 실제로는 세션 잡음이었음. **파이프라인 변경 평가는 반드시 같은 세션 paired 3-run** 으로.
(이전 stage49b "3-run majority 원칙"의 확장 — 비교 대상도 같은 세션.)

### 14.6 raw

- `stage53_missed3.py` + `data/stage53_missed3.json` + `STAGE53_MISSED3_20261006.md`
- `stage54_op90_regress.py` + `data/stage54_op90_regress.json` + `STAGE54_OP90_REGRESS_20261006.md`
- `stage55_pool20_3run.py` + `data/stage55_pool20_3run.json` + `STAGE55_POOL20_3RUN_20261006.md`
- `stage56_full_compare.py` + `data/stage56_full_compare.json` + `STAGE56_FULL_COMPARE_20261006.md`
- 로그: `data/stage53_run5.log`, `data/stage54_run2.log`, `data/stage55_run.log`, `data/stage56_run.log`

### 14.7 JEV API 키별 한도 (운영 교훈)

- 3종 한도(분당 240콜 / 시간당 0.5$=11.9M / 일일 2$=47.6M)는 **키별 독립**.
- 키1 소진 → 키2는 새 할당으로 사용 가능. 시작 전 두 키 1콜 probe → **잔여 키로 시작**.
- 429 본문 'daily free allowance' 확인 시 해당 키를 `rot.exhausted_until`에 넣어 정각까지 제외
  (on_429는 순환만, daily 제외는 명시적으로 해야 함).
- 키1 429 시에도 키2 200이면 실행 가능 (2026-10-06 stage53 실증).
