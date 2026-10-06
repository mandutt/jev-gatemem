# STAGE32~35: Noul+Choice Hybrid → 2콜 구조 — 실측 기록 (2026-10-06)

## 배경
세 AI 검토서(C AI) 제안: "choice의 relative selection과 noul의 absolute answerability를
분리해서 1콜로 동시에 얻을 수 있는가?" — 스킬 메모리엔 "1요청 1질문 하드 제약"으로 기록돼
있었으나, 이는 **choice+entails 조합**에만 해당. choice+noul 병렬은 미검증이었음.

## stage29: API 조합 검증 (1콜)
- choice + noul 2 = 3질문 → **200** (answers에 choice+noul 동시 반환)
- choice + noul 1 = 2질문 → 200
- noul 3개만 → 200 (기존 패턴)
- **결론: choice+noul 병렬 1요청 가능** — C AI 주장 실측 확인. 스킬 메모리의 "1요청 1질문"
  제약은 choice+entails(또는 다른 조합)에만 해당하며 noul과는 병렬 가능.

## stage30/31: API 한도
- 61질문(choice 1 + noul 60) → **400** ("Invalid decision request")
- 스윕: noul 30(질문 31) → 200, 40(41)부터 400
- **한도: noul ≤ 30 (choice 포함 총 질문 31)** — MAX_QS 32와 일치

## stage32: hybrid pool30 (op 90 + noans 50 = 140콜)
- POOL_BUDGET 30 + choice 1 + noul 30 = 31질문 1요청
- 파이프라인: build_lane_pool → filter → pool[:30] → hybrid call
- **결과:**
  - op: hit@1=74, hit@3=77, hit@5=81, abstain 4 (pool60 choice-only 77/80과 비교 → pool 축소로 hit@1 +4)
  - noans: FP=16 (동일)
- noul 분포: min 0.05, max 0.96, mean 0.76

### 정책 스윕 (0콜 후처리)
- [noul_top < τ] or [margin < δ] → abstain
  - **margin(δ) 게이트는 치명적**: δ=0.1 → op hit@3 77→52 폭락 (noul 변별력 약함)
  - **τ 게이트 유효**: τ=0.5 → op 75(-2), noans 16→8 ✅ (+6 순효과)
- winner_noul(choice가 고른 후보의 noul) 기준 τ=0.5: op 73, noans 7 (+5)
- abstain_p>0.3 결합: op 76, noans 12 / +noul τ=0.5 → op 75, noans 8
- **noul-only pick(choice 대체)는 열위**: gold@1=65 (choice 74보다 9 낮음)

## stage33: 2콜 구조 (noul top-5 재choice)
- 1콜째: hybrid pool30 (choice + noul)
- 2콜째: noul top-5만 추려 **choice 재실행** (criteria 6개뿐 — 토큰 1콜째의 ~1/5)
- **결과:**
  - op: hit@1=73, hit@3=**79**(+2), hit@5=79, s2-abstain 8
  - noans: FP=14 (τ 게이트 후 12, noul τ=0.5 후 9)
- 최적 게이트: [noul_top<0.3] or [s2 abstain_p>0.3] → **op 79, noans 12** (순효과 +6)
- 0콜 상한 분석: op miss 11건 중 **9건(82%)이 pool 밖 (retrieval 병목)** — 3콜째로 살릴 수 없음

## stage34: 라이브 스모크
- op gold 2건 → 선택 top1 (지연 2.2~2.7초)
- noans 2건 → abstain (빈 컨텍스트) ✅

## stage35: op90+noans50 전체 회귀 (2콜 운영 코드)
- **결과: hit@1=70, hit@3=74, hit@5=80, abstain 5, noans FP=17, err 0**
- stage33 파일럿(hit@3 79, FP 12)과 불일치 — 원인: ①JEV 비결정성(무작위 choice) ②noul 게이트가
  **과거사 질문의 관련 메모리(noul 높음)를 통과**시켜 오답 유도 (FP 17건 중 noul_top 0.68~0.81 다수)
- stage32 1콜 hybrid와 비교 시 hit@3 -3, noans -1 → **2콜 이점 미재현**

## stage36: 2콜 3회 반복 재검증 — **기각 확정**
- RUN1~3: hit@3 75/75/76, noans FP 17/16/19 → **majority hit@3 75, FP 18**
- stage33 파일럿 hit@3 79는 비결정성 착시 (운 좋은 run)
- 2콜째 재choice는 정보 증분 없음 (noul top-5는 1콜째가 이미 본 후보)

## stage37: 1콜 hybrid(pool30) 3회 반복 — **기각 확정**
- RUN1~3: hit@3 77/77/77 (동일), noans FP 18/20/20 → **majority hit@3 77, FP 20**
- stage32의 noans 12는 비결정성 착시. noul 게이트(τ=0.3)는 과거사 질문의
  관련 메모리를 통과시켜 **noans 방어에 비효과** (오히려 FP 증가)

## 최종 판정 (하이브리드/2콜 전체)
- **2콜, 1콜 hybrid 모두 기각** — 3회 반복에서 현행(pool60, win-300, soft gate) 대비
  hit@3 동등 이하, noans FP 열위
- **현행 구조(pool60 choice-only + win-300 + abstain_p soft gate)가 최적** (2026-10-06 확정)
- `TWO_CALL` 기본 off (env `JEV_TWO_CALL=1`로 실험 재현 가능), `_jev_hybrid`/1콜 hybrid 경로는
  재검증용으로 코드에 유지
- 남은 병목: **retrieval (pool 밖 miss 9건)** — rerank가 아닌 lane/임베딩 문제

## 최종 판정
- **2콜 구조 채택**: op hit@3 79(+2 over 1콜 hybrid), noans 12(-4), abstain 8
- 콜 2회/쿼리 but 토큰 +20% (2콜째 criteria 6개) — 사용자 원칙(토큰 비용) 부합
- 3콜째는 상한 +1~2에 그침 (miss 82%가 pool 밖) → **스톱**
- 다다음 병목: **retrieval (pool 밖 9건)** — rerank가 아닌 lane/임베딩 문제

## 구현 (gateway/j1_pipeline.py)
- `_jev_hybrid()`: choice + noul N 병렬 1요청
- `HYBRID_MAX_CANDIDATES=30`, `NEXT_CALL_TOP_N=5`, `_NOUL_TAU=0.3`, `_NEXT_ABSTAIN_TAU=0.3`
- `TWO_CALL` (env `JEV_TWO_CALL=0`으로 1콜 폴백)
- 2콜 경로: pool>30 → hybrid(30) → noul top-5 재choice → 게이트([noul_top<τ] or [s2 abstain_p>τ])
- hybrid 실패 시 1콜 choice 폴백

## 파일
- stage29_noul_choice_api_probe.py / stage30_hybrid_limit_probe.py / stage31_hybrid_scan.py
- stage32_hybrid_pool30.py / stage33_2call_noul5.py / stage34_2call_smoke_live.py / stage35_2call_full_regression.py
- stage38_abstain_label.py / stage39_abstain_label_poolfixed.py
- data: stage32_hybrid_pool30.json / stage33_2call_noul5.json / stage35_2call_full_regression.json
- data: stage38_abstain_label.json / stage39_abstain_label_poolfixed.json

---

## stage38/39: abstain 라벨 문구 개선 실측 — **보류 (채택 여부 추후 결정)**

### 배경
세 AI(A·B·C) 공통 제안: "same topic is not evidence" + 시점·버전 불일치 배제 명시.
- 현행: "No candidate is usable evidence for answering the question"
- 개선: "No candidate contains the specific fact, value, version, or decision the
  question asks for — same-topic mention alone is not evidence"

### stage38 (live DB 현재 시점, 70콜×2: noans 50 + op-sample 20)
- current: noans FP 25/50 (50.0%), op-sample hit@3 11/20
- improved: noans FP 28/50 (56.0%), op-sample hit@3 15/20
- **그러나 current FP 25는 기존 실측(stage26/35: 16)과 큰 차이** — 원인: **DB 시점 변화**
  (working_memory 1701행 — 시간 경과로 noans 하드셋의 "답 없음" 전제가 깨짐:
  새 메모리가 hard-neighbor 생성). stage38 FP 8건은 stage35에선 abstain이던 쿼리
  (예: 임베딩 모델 버전, deepseek 스트림 오류, skip_shadow 누락 — 실제 답을 담은
  메모리가 DB에 추가됨)

### stage39 (stage32 raw pool 고정 — 비결정성·DB 시점 격리, 50콜×2)
- current: noans FP 22/50 (44.0%)
- improved: noans FP **20/50 (40.0%)** — **-2 FP** ✅
- 개별 변화 2건이 정확히 의도한 패턴 (current FP → improved abstain):
  - "exa 검색이 키리스로 작동하던 기간이 언제야?" (p 0.17 → 0.32)
  - "diag63이 pointwise 대신 choice를 쓰는 옵션?" (p 0.22 → 0.32)

### 판정 (2026-10-06)
- **보류** — 채택 여부 추후 결정 (사용자 결정)
- 신호: pool 고정 -2 FP (긍정) vs live DB +3 FP (부정, 그러나 DB 변질 때문)
- 두 결과 모두 비결정성 범위(±3~5) 안 — 확정적 우위/열위 없음
- 개별 사례는 세 AI가 지적한 실패 모드(과거 시점 질문)를 정확히 차단하는 방향
- 후속 조치: 채택 시 `gateway/j1_pipeline.py`의 `ABSTAIN_LABEL` 교체 (0콜 추가, 무비용).
  noans 셋 재구성(시점 고정/신선 셋) 후 재검증 권장.

---

## stage40: evidence-span scratch index 0콜 검증 — **기각 확정**

### 배경
C AI Q4-3 제안: 800자 초과 memory를 문단/문장 단위 span으로 분할해,
검색 단위를 "원문 row"가 아닌 "span"으로 바꾸면 long-memory truncation을
retrieval 문제로 해결할 수 있다는 가설.

### 실측 (0콜, bekko-a8m 로컬 임베딩)
- 데이터: working_memory 1708행 (median 380자, >800자 494건 28.9%, 최대 44,779자),
  episodic 113행 — **그러나 op-90 gold 중 >800자는 0건** (최장 687자)
- gold>300자 58건에 대해: gold 내부 top-span sim vs 기존 pool(10개 샘플) max sim 비교
  → **gold-span 유리 11/58 (19%)**
- 그 11건 중 **실제 pool 밖 miss는 1건뿐** ("shutdown API 어떻게 만들었지?") —
  나머지 10건은 이미 pool 안 rank=1 (회수 성공, span으로 개선할 문제 없음)
- pool 밖 miss 11건 전체에서 gold-span 유리 = **1건 (9%)**
- pool 밖 miss의 실제 원인: 어휘/의미 단절 ("전환 전 어떤 문제", "Exa 왜 안 써",
  "provider가 뭐지") — **span 분할로 해결 불가**

### 판정 (2026-10-06)
- **기각** — 회수 개선 상한 1건 (hit@3 +1.1%p 최대) 대비 구현 비용(span 인덱스,
  문단 분할, 재검색 인프라) 과다
- op-90 retrieval 병목(pool 밖 11건)은 **write-path 태그 보강(A AI Q5)** 또는
  **lane 확장** 영역 — span 분할이 아닌 문제
- C AI의 "long memory를 evidence 단위로" 직관은 gold>300자 58건에서 대부분
  이미 pool 안에서 해결됨 (win-300 excerpt가 동일 효과) — 실측으로 반증

---

## stage41: 로컬 식별자/IDF 필터 0콜 실측 — **보류** (채택/기각 추후 결정)

### 배경
B AI Q1(c) 제안: "쿼리의 숫자·버전·영문 식별자가 JEV pick 원문 전체에 있는지
로컬에서 확인 — 없으면 abstain" (0콜, noans 값 불일치 오주입 방어).

### 실측 (stage39 pool 고정 FP 대상, 0콜)
쿼리 식별자 추출 규칙 3종 비교 (noans FP 차단 / op-90 오차단):

(정정: 아래 수치는 2026-10-06 전수 재검증에서 **스냅샷 코퍼스 DF + stage32 raw 재계산으로 정정**됨.
기존 9/2/7·오차단 1/0/0은 계산 기준 오류 — 실제는 v1 7/2, v2 5/0, v3 4/0. 상세 §13 재검증 규칙)

| 규칙 | noans FP 차단 | op-90 오차단 | 순효과 |
|---|---|---|---|
| v1 영문 식별자 전부 (`[a-z][a-z0-9_.-]{3,}`) | 7 | 2 ("API", "repo") | +5 |
| v2 underscore/숫자 혼합만 | 5 | 0 | +5 |
| **v3 IDF 드문 단어 (DF≤10)** | **4** | **0** | **+4** |

- v3 차단 4건: `browser.backend`·`JEV_API_URL`·`diag6`·`diag63` — 모두 쿼리에만 있고
  pick 원문에 없는 드문 식별자 (기존 목록의 `skip_shadow`·`pool_rank`·`golden_eval_v2`·
  `v0.19.x`·`config.yaml`은 쿼리에 없거나 pick에 존재해 실제 차단 안 됨)
- v3 오차단 0건 — "repo" 등 일반명사는 DF가 높아 필터 대상 제외
- 남은 FP: `ddgs`·`camofox`·`web_extract` — pick 원문에 식별자가 실제 존재해
  필터로 차단 불가 (애초에 값 일치)

### 시간 의존성 검증 (사용자 지적)
- v3가 잡은 4건 중 **숫자/버전/날짜 패턴으로도 잡히는 건 0/4** — 전부 순수
  영문 식별자. "드물다" 판정은 **코퍼스 DF 통계에만 의존**
- **메모리 성장 시 DF 상승 → 필터 무력화** (기존 식별자가 보편화), 반대로
  **신규 주제 식별자는 DF 낮아 과민 반응 → 정상 gold 오차단 위험**
- 패턴 기반(버전/날짜/포트) 필터는 드리프트가 없으나 이번 커버리지 0건 (효과 없음)
- → **IDF 필터는 시간에 따라 성능 표류하는 휴리스틱.** 재평가(DF 임계 조정)는
  메모리가 불어날수록 곤란 (검토·유지보수 부담 증가)

### 판정 (2026-10-06)
- **보류** — 채택/기각 추후 결정 (다른 AI 검토 예정)
- 근본 해법 후보: IDF 통계 대신 **abstain 라벨 문구 개선**(stage38/39 보류,
  코퍼스 비의존·성장해도 무력화 없음) — 두 보류 안건을 함께 재검토 권장
- 운영 반영 시 지연 수 ms / 콜 추가 0 (필터만으로는 채택 가능하나 드리프트 리스크)

---

## stage42: soft abstain 노출 0콜 시뮬레이션 — **기각 확정**

### 배경
B AI Q3 신규 제안: "abstain일 때 빈 컨텍스트 대신 pool 상위 1~3개를 낮은 신뢰
태그([LOW_CONF])와 함께 노출 — `format_block`의 trust_tier 슬롯 활용, 일반 LLM
금지 원칙과 무관, abstain의 gold 회수 기회".

### 실측 (0콜, stage26/32 raw 재계산)
- **op abstain(win-300 적용 후) = 0건** — 기존 abstain 3건이 win-300으로 이미
  회복됨 → **soft abstain 노출의 gold 회수 이득이 현재 운영엔 존재하지 않음**
- noans abstain 34건(stage32)에서 상위 3 노출 시 **주제 겹침(유해 후보) 50%**
  (4/8 샘플): "임베딩 모델 전 버전?" → top-3에 "설계 확정 ADR"·"임베딩 벤치 S3"
  등 **관련 있지만 답이 아닌 메모리** — 소비 에이전트가 앵커링할 위험
- abstain은 "답 없음"의 정직한 신호(noans easy 0 FP의 근거) — 노출은 이를 훼손

### 판정 (2026-10-06)
- **기각** — 이득 0건(현재 abstain은 이미 정직한 빈 컨텍스트) vs 리스크 50%
  유해 노출. B AI의 실패 기준(IRREL 노출 > gold 회수)을 충족하는 방향
- abstain = 빈 컨텍스트 유지 (현행 최적)

## stage47a~h: excerpt 윈도우 계열 (win150/head+겹침) — **전부 기각** (2026-10-06)

3차 AI 검토(B) 제안(150자 직접 윈도우, head+겹침) 8단계 실측. 전체 요약:
- 1-run은 유망(win150 hit@3 +1·FP -3, head+겹침 전 지표 개선)했으나 **3-run에서
  규칙형 noans 붕괴 또는 gold50 손실** — WHY 3건 구제 대가가 더 큼 (순손실)
- **현행(300→150 절단 + current 라벨) 유지 확정**, 재실험 금지
- 상세: `STAGE47H_FINAL_20261006.md` (47a~h 연쇄)

## stage48: 라이브 60쿼리 교차 — **abstain 무력** (2026-10-06)

- 실사용 60건 + 사용자 판정 교차: recall 100%(35/35) vs **noans FP 100%(22/22)**,
  **abstain 0건** (abstain_p 전부 0.00~0.16)
- 버그 3건 수정: `_filter_and_rank` 기본값 (2,0.30)→(1,0.0), 러너 row_factory,
  load_queries 시트 고정
- **u_true=38.6%** — 라이브 ~39%가 무답인데 전부 오주입. abstain 메커니즘 재설계 필요
- 상세: `STAGE48_LIVE60_CROSS_20261006.md`
