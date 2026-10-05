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
- **진짜 병목**: abstain 8건 중 3건은 gold가 pool에 있는데 JEV가 abstain을 고른 'abstain 오판' (upstream 404, gold50, S8). stage20~24에서 excerpt 확장으로 시도했으나 **noans 오주입과 trade-off로 최종 기각** → **현행 head-100 유지 확정**.

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

### 판정: excerpt 확장 접근 전부 기각, 현행 head-100 유지

- **골드 회복(+6~7)과 noans 오주입(+7~10)이 동일 메커니즘(excerpt 정보량)으로 충돌** — 순효과 0 이하.
- win-300이 "답이 뒤에 잘린 골드"는 살리지만, "주제 근접 미끼(과거 이력 질문)"도 300자 텍스트에서 답처럼 보이게 만들어 오주입.
- pair 게이트(exp7f)는 미끼 차단에 부분 효과(3건)지만 **정답도 차단**(gold50 gate=NO) — 과다거부 문제 재현 → 단독/2콜 구조 모두 채택 불가.
- **abstain fallback(A)도 불필요**: abstain 3건 중 2건(upstream, S8)은 excerpt로 회복 가능했으나 noans 비용이 더 큼 → 현행(abstain 시 빈 컨텍스트) 유지가 noans 방어상 최적.

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