# 외부 AI 검토 요청서 — jev-mem 메모리 파이프라인 보류/결정 대기 사안 3건 (보강판)

- 작성일: 2026-10-06
- 대상: 메모리 파이프라인 (jev-mem) — SQLite + 로컬 임베딩(bekko-a8m) + FTS/vec/importance/graph 4-lane RRF + JEV(SystemOne API) choice rerank
- **목적**: 아래 3개 사안의 채택/기각/수정 방향 결정을 위한 독립 검토
- **전제**: 각 사안은 실측(raw JSON·러너 포함)으로 판정 대기 중. 추가 정보 요청 없이 답변 가능하도록 모든 수치·조건·한계·함정을 기재.
- **구성**: §0 시스템 요약 → §0.5 실험 이력·함정(수치 해석의 전제) → 사안 1~3(각각: 제안/실측/절충/신뢰성/판단 요청) → 부록 A~C

---

## 0. 시스템 요약 (판단 공통 배경)

| 항목 | 값 |
|---|---|
| 저장소 | SQLite `mnemosyne.db` (working_memory 1,721행 + episodic 113행, 스냅샷 2026-10-06) |
| 임베딩 | `bench/bekko-a8m` (384차원, 로컬 fastembed) — 전체 전용 |
| 검색 | 4-lane RRF: FTS5 + vec + importance + graph → 게이트(어휘 overlap≥1, coverage) → **POOL_BUDGET=60** 컷 |
| rerank | JEV SystemOne `choice` 1콜/쿼리 — "최고 증거 1개 선택" + abstain 라벨(cN, 마지막) |
| excerpt | 전 후보 **쿼리 인지 300자 윈도우 → 150자** (win-300, 2026-10-06 채택) |
| soft gate | choice 응답의 **abstain 라벨 확률(abstain_p) > 0.3** → 빈 컨텍스트 (τ=0.3, 운영) |
| abstain 라벨 | 문구: "No candidate is usable evidence for answering the question" |
| 평가지표 | op 90 (gold 회수): hit@1 74~75, hit@3 77~78, abstain 3 / noans 50 (hard, 답 없음): FP 25~27 (스냅샷 기준선) |
| 운영 무답 비율 | u=22.5% — 라이브 데몬 `query_log` 실측 (2026-10-05, stage25~27, 총 87건 중 abstain/빈 컨텍스트 비율) |
| 평가 프로토콜 | **3-Run Majority Vote 권장** — JEV 비결정성 ±3~5건 실측 (파일럿 79가 재현 75로 붕괴한 사례) |
| 실험 환경 주의 | JEV 호출은 `EXPLABS_API_KEY` SET 터미널에서만 (무료 레인, 240콜/분, 503은 1회 재시도, 429는 키 전환) |

**핵심 구조**: 코퍼스 → lane 검색 → pool 60 → JEV choice(1콜) → pick 1개 노출 (abstain 시 빈 컨텍스트).

---

## 0.5 실험 이력·함정 (수치 해석의 전제 — 반드시 읽기)

### A. venv 오염 사건 (2026-10-05) — 수치 해석의 최우선 전제

- 프로젝트 `.venv`의 fastembed가 `bench/bekko-a8m` 모델을 **지원하지 않음** → 임베딩 예외 → **vec lane 0건** → abstain이 27건으로 급증 (오염 실측)
- **데몬 venv**(`%LOCALAPPDATA%/jev-mem/venv`)로 전환 후: abstain 27→**8**, hit@3 61.1%→**77.8%** (동일 쿼리셋)
- **이후 모든 실험은 데몬 venv 고정** — 프로젝트 .venv로 돌리면 무효
- 이 사건 때문에 "abstain 27건" 등 오염 수치가 일부 문서에 남아 있음. **본 요청서의 모든 수치는 데몬 venv 기준이며, 오염 수치가 아님.**

### B. JEV 비결정성 (온도/배치 순서) → 3-Run Majority Vote 권장

- 동일 쿼리셋을 재실행하면 **±3~5건 차이** 실측 (파일럿 higher-order 79 → 재현 75 붕괴)
- 1-run 결과는 노이즈일 수 있음 → **두 문구/두 구조 비교는 3-Run Majority(2/3 일치)로 판정해야 안전**
- 본 요청서 사안 1의 실측은 1-run (콜 예산) — **§1.5 한계 명시**, 3-run 재검증 필요할 수 있음

### C. 평가 셋 구축 변천

1. 합성 180 (kodialog/kosgd/koalpaca/기계독해) → 운영 현실과 괴리로 졸업
2. **운영 골든셋** op 90 (gold 회수) + noans 50 (hard, 답 없음) — Hermes 실제 기억에서 샘플링
3. **스냅샷 고정** (10-06): `mnemosyne_snapshot_20261006.db` — 이후 모든 실측은 이 DB 기준 (이유: §사안 3)

### D. stage 흐름표 (stage16~46 + A Q5/read-path — 주요 판정만)

| stage | 실험 | 결과/판정 |
|---|---|---|
| 16~17 | pool-out 23건 lane 진단 | 진짜 retrieval miss 분류 시작 |
| 18 | doc2query 파일럿 (9router) | **기각** — 대화 단답은 질문 생성 불가 |
| 19 | gold vec rank 분석 | vec 예외 레버 소진 확인 |
| 20~21 | **excerpt 300 윈도우 파일럿 → op90** | hit@3 70→76, abstain 3→0 |
| 22~23 | excerpt300 noans → FP 13→20 + 분해 | 역사/타임라인 유혹 — soft gate 필요성 확인 |
| 24 | conditional win300 + gate | net -3 → **기각** |
| 25~28 | **win300 + soft abstain gate(τ=0.3) 채택** + 라이브 반영 | hit@3 77~78, abstain 3 — 운영 적용 |
| 29~35 | Noul+Choice hybrid / 1-call / 2-call | 3-run majority hit@3 75 vs 77 → **기각** (불안정) |
| 38 | noans 셋 시점 변질 발견 | **13건** FP로 뒤집힘 (§사안 3) |
| 39 | abstain 라벨 문구 pool 고정 | FP 22건 기준 실측 |
| 40 | evidence-span 지수 | 회수 개선 상한 1건 → **기각** |
| 41 | **IDF 필터 v1/v2/v3** | §사안 2 |
| 42 | soft abstain 노출 관찰 | abstain_p 정상 분포 확인 |
| 43 | **noans 재구성** (snapshot + nans3) | §사안 3 |
| 44 | abstain 위치 2×2 (c0 vs cN) | hit@3 77-78 동일 → **위치 무효과** |
| 45 | **abstain 라벨 문구 current vs improved** | §사안 1 |
| 46 | support set 재감사 (11건) | 진짜 miss 10/11, 문맥 의존 1 (부록 A) |
| A Q5 | write-path 태그 0콜 검증 | 복구 0/10 → **기각** (부록 A) |
| — | read-path 쿼리 확장 0콜 검증 | 복구 2/11 → **기각** (부록 A) |

---

## 사안 1: abstain 라벨 문구 개선 — **판정 보류**

### 1.1 제안 (이전 3종 AI 공통 지적)
현행 abstain 라벨: `"No candidate is usable evidence for answering the question"`
이 문구가 "주제는 같지만 답이 아닌 메모리"를 abstain하지 못해 noans 오주입.

제안 개선 문구:
> `"No candidate contains the specific fact, value, version, or decision the question asks for — same-topic mention alone is not evidence"`

### 1.2 실측 1 (stage45, 스냅샷 기준, 동일 세션 280콜, err 0)

| 문구 | hit@1 | hit@3 | abstain | noans FP (50) |
|---|---|---|---|---|
| current (현행) | 75 | **78** | 3 | 27 |
| **improved** | 73 | **76** | 5 | **22** |

- paired: op **-2** (→76), noans **-5** (27→22) → 건수 순 +3
- op 손실 2건: **"코덱스 앱이 PC 느려지게 한 원인?", "마우스 버벅임 원인 조사 결과?"**
  — **원인(WHY) 질문**을 abstain으로 오판 (current에선 둘 다 hit@1~3)
- noans 개선 5건: "skip_shadow 테이블 누락?", "Mnemosyne consolidation 중복 버그?",
  "주석 영어 규칙?", "테스트 생략 커밋 규칙?", "로그 한국어 규칙?"
  — **시점/규칙 확인형**을 정확히 차단

### 1.3 절충 시도 (v3/v4, 같은 세션)

| 문구 | hit@3 | noans FP | 비고 |
|---|---|---|---|
| v3 (explanation 포괄 수용) | 76 | 24 | 코덱스 rank 4 (hit 아님), noans -2 |
| v4 (WHY 조건부 수용) | 76 | 23 | abstain 6건(+1), 코덱스 여전히 abstain |

- **v3/v4 모두 코덱스(원인 질문)를 hit@3로 구제 실패** + noans 방어 약화 → 기각
- "explanation/cause" 문구 추가는 JEV의 원인 질문 abstain을 바꾸지 못함 (구조적 한계)

### 1.4 "원인 질문 감지 예외" 임베딩 분류 시도 (0콜)

- 설계: 원인 질문 시드 10개 vs 사실/시점 질문 시드 10개 프로토타입과 쿼리 유사도 차이(margin)로 원인 질문 감지 → current 문구 재사용
- **결과: 변별력 없음** — margin 양수 124/140(89%), op 손실 margin(+0.036/+0.055)과 noans 개선 margin(+0.007~+0.051) 분포 겹침 → 임계값 분리 불가 → 기각
- ⚠️ 이 수치는 0콜 임시 계산으로 **별도 raw 파일은 남아 있지 않음** (세션 내 계산) — 재현 시 stage45 raw의 op/noans 레코드 + 시드 프로토타입 재구성 필요

### 1.5 실측 신뢰성

- raw: `data/stage45_abstain_label_snapshot.json` (cond: current/improved, 140쿼리×2=280콜, err 0, 스냅샷 DB 고정)
- 재현 러너: `experiments/operational-golden/stage45_abstain_label_snapshot.py`
- **한계 1: 1-run 실측** — §0.5-B 비결정성 때문에 ±3~5건 노이즈 가능. **채택 여부는 3-run 재검증 필요**
- **한계 2: 동일 세션 내 순서 효과** — current→improved 순서로 실행, 순서 효과 미통제
- v3/v4 raw: `data/stage45_v4_snapshot.json` (같은 세션 연속 실행)

### 1.6 판단 요청 사항

1. **improved 채택 vs 현행 유지**: noans -5 FP vs op -2 정답. 실 운영 무답 비율 u=22.5%(\*)에서 harm-가중 판정은 어느 쪽?

> (\*) u=22.5% 출처: 라이브 데몬 `query_log` 실측 (2026-10-05, stage25~27 시점, 총 87건 중 abstain/빈 컨텍스트 비율). 스냅샷 DB에는 query_log 테이블이 미포함 — 2026-10-05~06 실측 문서(`RECALL_ABSTAIN_INVESTIGATION_20261005.md` §재판정) 기준.

2. **3-run 재검증 없이 채택 가능한가**, 아니면 재검증 설계(콜 예산 ~420콜)를 먼저 할 것인가?
3. WHY(원인) 질문 abstain 오판의 **라벨 문구 외 해법**이 있는가? (지시문 구조 변경? abstain_p soft gate τ 조정? 후처리?)
4. improved 채택 시 op -2를 감수할 근거가 있는가, 아니면 다른 절충이 있는가?

---

## 사안 2: 로컬 식별자/IDF 필터 (noans 값 불일치 방어) — **판정 보류**

### 2.1 제안 (B AI Q1c)
쿼리의 숫자·버전·영문 식별자가 JEV가 고른 pick 원문에 없으면 abstain — "값 불일치 오주입"을 로컬 0콜로 차단 (JEV 콜 추가 없음, 수 ms).

### 2.2 실측 (stage41, 0콜 — stage32 raw의 noans FP 대상)

> 기준 명확화: v1/v2/v3 규칙 비교는 **stage32 raw(hybrid pool30, 2026-10-06 00:27)의 noans FP 16건**을 대상으로 계산. (stage39 pool 고정 22건은 라벨 문구 실험용 — IDF 필터 실측과는 다른 셋)
>
> ⚠️ **수치 정정 (2026-10-06 재검증)**: 아래 표는 스냅샷 코퍼스 DF 통계 + stage32 raw에서 0콜 재계산한 값이다. (기존 초안의 9/2/7은 계산 기준 오류로 기각)

| 규칙 | noans FP 차단 | op-90 오차단 | 순효과 |
|---|---|---|---|
| v1 영문 식별자 전부 | 7 | 2 ("API", "repo") | +5 |
| v2 underscore/숫자 혼합만 | 5 | 0 | +5 |
| **v3 IDF 드문 단어 (DF≤10)** | **4** | **0** | **+4** |

- **v3 차단 4건**: `browser.backend`, `JEV_API_URL`, `diag6`, `diag63` — 쿼리에만 있고 pick 원문(JEV가 고른 gold 후보)에 없는 드문 식별자
- v3 오차단 0건 — "repo" 등 일반명사는 DF가 높아 제외

### 2.3 시간 의존성 (사용자 지적 → 확인됨)

- v3가 잡은 4건 중 **숫자/버전/날짜 패턴으로도 잡히는 건 0/4** — 전부 순수 영문 식별자
- "드물다" 판정이 **코퍼스 DF 통계에만 의존**:
  - 메모리가 쌓이면 DF 상승 → 필터 무력화 (기존 식별자 보편화)
  - 신규 주제 식별자는 DF 낮아 **과민 반응 → 정상 gold 오차단 위험**
- 패턴 기반(버전/날짜/포트) 필터는 드리프트가 없으나 실측 커버리지 0건 (효과 없음)
- 재평가(DF 임계 조정)는 메모리가 불어날수록 곤란

### 2.4 실측 신뢰성

- raw: `data/stage32_hybrid_pool30.json` (noans 50, FP 16건 — 규칙 계산의 베이스), `data/stage39_abstain_label_poolfixed.json` (pool 고정 22건 — 참고용)
- DF 통계: 스냅샷 DB 코퍼스 1,721+113행 기준 전체 문서 빈도
- **한계**: 규칙 계산은 0콜 시뮬레이션이며, **실제 JEV rerank와 결합 시 abstain_p에 미치는 영향은 미측정** — 필터가 abstain을 강제하면 op gold를 잘못 abstain할 가능성은 오차단 0건으로 확인했으나, "pick 없음 → abstain 강제"의 파급은 미검증

### 2.5 판단 요청 사항

1. **시간 의존성(드리프트)에도 채택할 가치가 있는가**, 아니면 기각?
2. 코퍼스 비의존 방식으로 같은 효과(값 불일치 차단)를 낼 방법이 있는가? (abstain 라벨 문구 개선 = 사안 1과 결합 가능성?)
3. 운영 도입 시 **DF 임계 동적 조정**(예: 주기 재계산)으로 드리프트를 막을 수 있는가? 그 비용/리스크는?
4. "pick 원문에 식별자 없음 → abstain 강제"가 soft gate(abstain_p>0.3)와 어떤 상호작용을 할지 예측/설계는?

---

## 사안 3: noans 셋 시점 변질 + 평가 인프라 — **프로토콜 확정 대기**

### 3.1 발견 (stage38)
- noans hard 50건은 "코퍼스에 답 없음" 전제로 구성됐으나, **질문 셋 생성(2026-10-04) 이후 실험 대화가 메모리에 누적**되면서 특정 쿼리에 "실제 답"이 생김 (자기참조 오염)
- 실측: 같은 noans 쿼리가 stage35(10-06 01시)에 abstain → stage38(10-06 09시)에 FP로 뒤집힘 **13건** (stage35/38 raw 대조, 50건 중) — working_memory가 1,701행(stage38 시점 실측) → 1,721행(스냅샷)으로 증가하면서

### 3.2 재구성 (stage43, 0콜)

1. **평가용 DB 스냅샷 고정**: `mnemosyne_snapshot_20261006.db` (sqlite backup, 1,721+113행, 무결성 OK) — 이후 모든 noans 평가는 이 스냅샷 기준
2. **변질 판정**: FTS 스캔 + bekko 임베딩 sim + 인간 판정(리뷰 시트 23건) → **spoiled 5건 제외** (`nans2_008` JEV_API_URL, `_009` Free tier, `_015` pip uv, `_028` pool_rank, `_047` keyring — 셋 이후 생성 메모리에 실제 답 존재)
3. **신규 5건 보충** (`nans3_001~005`): deepseek→muse?, RRF 가중치 변경?, cron 실패?, SKIP 먼저 반환?, ZeroTier? — **전체 1,729벡터 top-1 sim 0.11~0.16**으로 "답 없음" 검증 + 하드-네이버 다수 (deepseek 39, RRF 55, cron 24, gate 77~186건)
4. 최종 50건 = hard 45 + fresh 5

### 3.3 파생 프로토콜

- **이후 모든 noans 평가는 스냅샷 기준** (실측 시점과 무관하게 비교 셋 동일)
- JEV 실험은 `EXPLABS_API_KEY` SET 터미널에서만 (execute_code 셸은 401 폴백), 503은 1회 재시도, 429는 키 전환(KEY1→KEY2)

### 3.4 실측 신뢰성

- raw: `data/golden_noanswer_hard_queries.json.bak_20261006_103054` (변질 전 50건), `data/golden_noanswer_hard_queries.json` (재구성 50건 = hard 45 + fresh 5)
- 판정 근거 시트: `data/stage16_poolout_23_review.html` (리뷰용), `data/gold44_human_review.md` (gold 44 인간 판정)
- 스냅샷 무결성: sqlite `PRAGMA integrity_check` OK
- **한계**: "spoiled 5건" 판정의 인간 판정 기준은 "셋 이후 생성 메모리(작성 시각)에 실제 답이 존재" — 시각 기준이므로 **과거 시점으로 되돌려 평가하면 무효일 수 있음** (시점 고정이 필수)

### 3.5 판단 요청 사항

1. **스냅샷 고정 평가 프로토콜**이 타당한가? (대안: 시간 경과를 허용하는 "유동 noans 셋" 유지보수?)
2. **신규 noans 5건의 선정 방법론**(임베딩 top-1 sim ≤0.16 + FTS 하드-네이버 존재)이 "답 없음" 보장으로 충분한가?
3. 변질된 noans 셋이 의미하는 것: **noans FP 지표 자체를 시간 함수로 봐야 하는가**? (운영 지표로 noans FP 대신 무엇을 써야 하는가)
4. 스냅샷 고정 시 **op 90 gold 셋도 같은 변질 위험**이 있는가? (gold는 회수 쿼리라 self-answer 위험이 낮다고 봤지만 확인 요청)

---

## 부록 A: stage46 pool 밖 miss 11건 판정 (수용 결정 배경)

- support_set 재감사: 11건 전부 q1=direct, q3=exists (진짜 retrieval miss 11/11 — [11]만 q4=dependent)
- [11] "전환 전 어떤 문제?"만 q4=dependent (supermemory→mnemosyne 전환 지식 필요)
- 해법 시도 3종 전부 기각 (0콜 실측):
  - evidence-span 인덱스 (stage40): 회수 개선 상한 1건
  - write-path 태그 (A Q5): 저장 직전 대화 태그 시뮬레이션 복구 0/10 — 저장 시점 대화 주제와 미래 질문의 어휘·개념 단절
  - read-path 쿼리 확장: top-20 유사 메모리 단어 주입 복구 2/11 — 경로/메타/범용어 오염
- → **pool_recall 90.0% (81/90; 문맥 의존 제외 시 81/89=91.0%)를 구조적 상한으로 수용**
  (pool_ids가 있는 최근 raw 5종 — stage25/26/32/33/exp8a — 전부 81/90 일치)

## 부록 B: 참조 문서 (필요 시)

- 실측 raw: `data/stage45_abstain_label_snapshot.json` (current+improved), `data/stage45_v4_snapshot.json` (v4), `data/stage44_abstain_pos_2x2.json`
- noans 재구성: `NOANS_SET_REBUILD_20261006.md`, `data/golden_noanswer_hard_queries.json` (50건)
- 스냅샷: `snapshots/mnemosyne_snapshot_20261006.db`
- miss 판정: `STAGE46_SUPPORTSET_20261006.md`, `data/stage46_verdicts.json`
- 설계안·기각 기록: `docs/design/write-path-tags-design-20261006.md` (§8~9)
- 전체 투자 기록: `RECALL_ABSTAIN_INVESTIGATION_20261005.md`, `STAGE29_35_HYBRID_2CALL_20261006.md`, `STAGE44_45_ABSTAIN_LABEL_20261006.md`

## 부록 C: 실험 raw 전체 목록 (재현 경로)

실험 디렉터리: `experiments/operational-golden/`

- runR: `data/runR_recall_strength_raw.json` — 알파 스윕 (hippo decay/strength 기각)
- stage16~17: `data/stage16_poolout_23_*.json`, `data/stage17_poolout_23_lane_diag.json`
- stage18: `data/stage18_doc2query_pilot.json` (기각)
- stage19: `data/stage19_gold_vec_rank.json`
- stage20~21: `data/stage20_excerpt300_pilot.json`, `data/stage21_excerpt300_op90.json`
- stage22~24: `data/stage22_noans_excerpt300.json`, `data/stage23_noans_fp_inspect.json`, `data/stage24_conditional_win300_gate.json`
- stage28 스모크: `data/stage28_smoke_live.json`
- stage29~37 hybrid/2-call: `data/stage29_*.json` ~ `data/stage37_*.json`
- stage38~39: `data/stage38_*.json`, `data/stage39_abstain_label_poolfixed.json`
- stage40: `data/stage40_evidence_span.json`
- stage41: (0콜 계산 — stage32 raw 기반, 산출 스크립트 `stage41_idf_filter.py`)
- stage42: `data/stage42_soft_abstain_observation.json`
- stage43: `data/stage43_noans_rebuild.json` (스냅샷 생성)
- stage44: `data/stage44_abstain_pos_2x2.json` (2×2, 560콜)
- stage45: `data/stage45_abstain_label_snapshot.json`, `data/stage45_v4_snapshot.json`
- stage46: `data/stage46_verdicts.json`, `STAGE46_SUPPORTSET_20261006.md`
- A Q5: `docs/design/write-path-tags-design-20261006.md`
- read-path 확장: `docs/design/write-path-tags-design-20261006.md` §9

---

## 요청 형식

사안별로: **① 판정 (채택/기각/수정/보류 유지) ② 근거 (실측 인용) ③ 권장 다음 단계 (콜·비용·실험 설계 포함)** 를 답변해 주시면 됩니다. 반대 의견도 환영합니다. 실측 신뢰성(§1.5/2.4/3.4)의 한계 지적도 별도로 부탁드립니다.