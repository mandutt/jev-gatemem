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