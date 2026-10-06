# 외부 AI 검토 요청서 — jev-mem 메모리 파이프라인 보류/결정 대기 사안 3건

- 작성일: 2026-10-06
- 대상: 메모리 파이프라인 (jev-mem) — SQLite + 로컬 임베딩(bekko-a8m) + FTS/vec/importance/graph 4-lane RRF + JEV(SystemOne API) choice rerank
- **목적**: 아래 3개 사안의 채택/기각/수정 방향 결정을 위한 독립 검토
- **전제**: 각 사안은 실측(raw JSON·러너 포함)으로 판정 대기 중. 추가 정보 요청 없이 답변 가능하도록 모든 수치·조건·한계를 기재.

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
| 평가 프로토콜 | **3-Run Majority Vote 필수** — JEV 비결정성 ±3~5건 실측 (파일럿 79가 재현 75로 붕괴한 사례) |
| 실험 환경 주의 | JEV 호출은 `EXPLABS_API_KEY` SET 터미널에서만 (무료 레인, 240콜/분) |

**핵심 구조**: 코퍼스 → lane 검색 → pool 60 → JEV choice(1콜) → pick 1개 노출 (abstain 시 빈 컨텍스트).

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

- 설계: 원인 질문 시드 10개 vs 사실/시점 질문 시드 10개 프로토타입과 쿼리 유사도
  차이(margin)로 원인 질문 감지 → current 문구 재사용
- **결과: 변별력 없음** — margin 양수 124/140(89%), op 손실 margin(+0.036/+0.055)과
  noans 개선 margin(+0.007~+0.051) 분포 겹침 → 임계값 분리 불가 → 기각

### 1.5 판단 요청 사항

1. **improved 채택 vs 현행 유지**: noans -5 FP vs op -2 정답. 실 운영 무답 비율
   u=22.5%(\*)에서 harm-가중 판정은 어느 쪽?

> (\*) u=22.5% 출처: 라이브 데몬 `query_log` 실측 (2026-10-05, stage25~27 시점,
> 총 87건 중 abstain/빈 컨텍스트 비율). 스냅샷 DB에는 query_log 테이블이 미포함 —
> 2026-10-05~06 실측 문서(`RECALL_ABSTAIN_INVESTIGATION_20261005.md` §재판정) 기준.
2. WHY(원인) 질문 abstain 오판의 **라벨 문구 외 해법**이 있는가?
   (지시문 구조 변경? abstain_p soft gate τ 조정? 후처리?)
3. improved 채택 시 op -2를 감수할 근거가 있는가, 아니면 다른 절충이 있는가?

---

## 사안 2: 로컬 식별자/IDF 필터 (noans 값 불일치 방어) — **판정 보류**

### 2.1 제안 (B AI Q1c)
쿼리의 숫자·버전·영문 식별자가 JEV가 고른 pick 원문에 없으면 abstain —
"값 불일치 오주입"을 로컬 0콜로 차단 (JEV 콜 추가 없음, 수 ms).

### 2.2 실측 (stage41, 0콜 — stage32 raw의 noans FP 대상)

> 기준 명확화: v1/v2/v3 규칙 비교는 **stage32 raw(hybrid pool30, 2026-10-06 00:27)의
> noans FP 16건**을 대상으로 계산. (stage39 pool 고정 22건은 라벨 문구 실험용 —
> IDF 필터 실측과는 다른 셋)

| 규칙 | noans FP 차단 | op-90 오차단 | 순효과 |
|---|---|---|---|
| v1 영문 식별자 전부 | 9 | 1 ("repo" 일반명사) | +8 |
| v2 underscore/숫자 혼합만 | 2 | 0 | +2 |
| **v3 IDF 드문 단어 (DF≤10)** | **7** | **0** | **+7** |

- v3 차단 7건: `browser.backend`, `config.yaml`, `JEV_API_URL`, `v0.19.x`,
  `skip_shadow`, `pool_rank`, `golden_eval_v2`, `diag63` — 쿼리에만 있고 pick에 없는
  드문 식별자
- v3 오차단 0건 — "repo" 등 일반명사는 DF가 높아 제외

### 2.3 시간 의존성 (사용자 지적 → 확인됨)

- v3가 잡은 7건 중 **숫자/버전/날짜 패턴으로도 잡히는 건 0/7** — 전부 순수 영문 식별자
- "드물다" 판정이 **코퍼스 DF 통계에만 의존**:
  - 메모리가 쌓이면 DF 상승 → 필터 무력화 (기존 식별자 보편화)
  - 신규 주제 식별자는 DF 낮아 **과민 반응 → 정상 gold 오차단 위험**
- 패턴 기반(버전/날짜/포트) 필터는 드리프트가 없으나 실측 커버리지 0건 (효과 없음)
- 재평가(DF 임계 조정)는 메모리가 불어날수록 곤란

### 2.4 판단 요청 사항

1. **시간 의존성(드리프트)에도 채택할 가치가 있는가**, 아니면 기각?
2. 코퍼스 비의존 방식으로 같은 효과(값 불일치 차단)를 낼 방법이 있는가?
   (abstain 라벨 문구 개선 = 사안 1과 결합 가능성?)
3. 운영 도입 시 **DF 임계 동적 조정**(예: 주기 재계산)으로 드리프트를 막을 수 있는가?
   그 비용/리스크는?

---

## 사안 3: noans 셋 시점 변질 + 평가 인프라 — **프로토콜 확정 대기**

### 3.1 발견 (stage38)
- noans hard 50건은 "코퍼스에 답 없음" 전제로 구성됐으나, **질문 셋 생성(2026-10-04)
  이후 실험 대화가 메모리에 누적**되면서 특정 쿼리에 "실제 답"이 생김 (자기참조 오염)
- 실측: 같은 noans 쿼리가 stage35(10-06 01시)에 abstain → stage38(10-06 09시)에 FP로
  뒤집힘 8건 — working_memory가 1,701행(stage38 시점 실측) → 1,721행(스냅샷)으로 증가하면서

### 3.2 재구성 (stage43, 0콜)

1. **평가용 DB 스냅샷 고정**: `mnemosyne_snapshot_20261006.db` (sqlite backup,
   1,721+113행, 무결성 OK) — 이후 모든 noans 평가는 이 스냅샷 기준
2. **변질 판정**: FTS 스캔 + bekko 임베딩 sim + 인간 판정(리뷰 시트 23건)
   → **spoiled 5건 제외** (`nans2_008` JEV_API_URL, `_009` Free tier,
   `_015` pip uv, `_028` pool_rank, `_047` keyring — 셋 이후 생성 메모리에 실제 답 존재)
3. **신규 5건 보충** (`nans3_001~005`): deepseek→muse?, RRF 가중치 변경?,
   cron 실패?, SKIP 먼저 반환?, ZeroTier? — **전체 1,729벡터 top-1 sim 0.11~0.16**
   으로 "답 없음" 검증 + 하드-네이버 다수 (deepseek 39, RRF 55, cron 24, gate 77~186건)
4. 최종 50건 = hard 45 + fresh 5

### 3.3 파생 프로토콜

- **이후 모든 noans 평가는 스냅샷 기준** (실측 시점과 무관하게 비교 셋 동일)
- JEV 실험은 `EXPLABS_API_KEY` SET 터미널에서만 (execute_code 셸은 401 폴백),
  503은 1회 재시도, 429는 키 전환(KEY1→KEY2)

### 3.4 판단 요청 사항

1. **스냅샷 고정 평가 프로토콜**이 타당한가? (대안: 시간 경과를 허용하는
   "유동 noans 셋" 유지보수?)
2. **신규 noans 5건의 선정 방법론**(임베딩 top-1 sim ≤0.16 + FTS 하드-네이버 존재)이
   "답 없음" 보장으로 충분한가?
3. 변질된 noans 셋이 의미하는 것: **noans FP 지표 자체를 시간 함수로 봐야 하는가**?
   (운영 지표로 noans FP 대신 무엇을 써야 하는가)

---

## 부록 A: stage46 pool 밖 miss 11건 판정 (수용 결정 배경)

- support_set 재감사: 11건 전부 q1=direct, q3=exists (진짜 retrieval miss)
- [11] "전환 전 어떤 문제?"만 q4=dependent (supermemory→mnemosyne 전환 지식 필요)
- 해법 시도 3종 전부 기각 (0콜 실측):
  - evidence-span 인덱스 (stage40): 회수 개선 상한 1건
  - write-path 태그 (A Q5): 저장 직전 대화 태그 시뮬레이션 복구 0/10 — 저장 시점
    대화 주제와 미래 질문의 어휘·개념 단절
  - read-path 쿼리 확장: top-20 유사 메모리 단어 주입 복구 2/11 — 경로/메타/범용어 오염
- → **pool_recall 87.8% (79/90; 문맥 의존 제외 시 80/89=89.9%)를 구조적 상한으로 수용**

## 부록 B: 참조 문서 (필요 시)

- 실측 raw: `experiments/operational-golden/data/stage45_abstain_label_snapshot.json`
  (current+improved), `stage45_v4_snapshot.json` (v4), `stage44_abstain_pos_2x2.json`
- noans 재구성: `NOANS_SET_REBUILD_20261006.md`, `golden_noanswer_hard_queries.json` (50건)
- 스냅샷: `snapshots/mnemosyne_snapshot_20261006.db`
- miss 판정: `STAGE46_SUPPORTSET_20261006.md`, `stage46_verdicts.json`
- 설계안·기각 기록: `docs/design/write-path-tags-design-20261006.md` (§8~9)

---

## 요청 형식

사안별로: **① 판정 (채택/기각/수정/보류 유지) ② 근거 (실측 인용) ③ 권장 다음 단계
(콜·비용·실험 설계 포함)** 를 답변해 주시면 됩니다. 반대 의견도 환영합니다.