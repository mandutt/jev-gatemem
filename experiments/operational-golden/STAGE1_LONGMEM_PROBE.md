# Stage-1/2 Probe: 장문 메모리 문제 실측 (jev chunking 파일럿) — 최종

- 날짜: 2026-10-05
- 방법: 0콜 결정적 probe — JEV 호출 0회, DB read-only, 로컬 bekko-a8m 임베딩
- 스크립트:
  - `stage1_longmem_probe.py` — DB 분포 + 골드 길이
  - `stage1b_plain_long_census.py` — plain 장문 전수 규격 + mid-query 벡터 회수
  - `stage1c_chunk_recall.py` — 800자 규칙 청킹의 벡터 순위 효과 (numpy)
  - `stage1d_scratch_pipeline.py` — **실제 파이프라인 스크래치 검증** (청크 행 저장 시 pool/gate)
  - `stage2_*` — 실사용 gold 구축 (query_log + 세션 transcripts, 사용자 판정 38건)
- 판정: **① 저장 청킹·chunkmax 기각 (JEV semantic chunking은 미검증 — 규칙 청킹만 실측) ② 그러나 "gate 1/19"의 진짜 원인은 `[ASSISTANT] prefetch 제외 정책` — 제외 해제 시 8/19. 청킹은 잘못된 문제에 대한 해법이었음.**
- (v1 보고서는 `STAGE1_LONGMEM_PROBE.v1.md`로 보존 — 실측 5 전까지의 중간판)

## 배경

supermemory 트윗(DhravyaShah)의 jev chunking(문장별 continuation 판정으로 청크 경계 선택)을
우리 jev-mem에 적용할지 검토. 가설: 장문 메모리가 (a) full-text 게이트 800자 절단으로
답이 잘림, (b) 512토큰 clamp 임베딩으로 벡터가 희석돼 회수 불량.

## 실측 1 — DB 장문 분포 (working 1,625 + episodic 113 = 1,738행)

| 버킷 | 행 수 | 비율 |
|---|---|---|
| ≤800 | 1,275 | 73.4% |
| 801–1,350 | 266 | 15.3% |
| 1,351–3,000 | 122 | 7.0% |
| 3,001–10,000 | 46 | 2.6% |
| >10,000 | 29 | 1.7% |

>1,350자 = 197행(11.3%). meta 분류: session-dump 36 / file-URL-attach 29 / compaction 1 / **plain 131**.
>10,000자 29행은 대부분 attach(25). **"토큰 폭탄"은 회수 문제가 아니라 prefetch 컨텍스트·비용 오염 문제.**

## 실측 2 — op-90 골드 메모리 길이 (게이트 절단 손실 상한)

DB 원문 기준 gold 메모리 45건: min 23 / p50 371 / p90 572 / max 687 — **전부 800자 미만**.
full-text 게이트 절단 손실: 0건. exp7g의 "절단으로 NO→YES 6건"은 43건 표본 한정.
→ **골드셋은 장문 문제를 드러내지 못함 (선택 편향)** — 실제로는 plain 장문 130행이 실재.

## 실측 3 — plain 장문 130행 전수 + mid-query 회수 붕괴

plain(>1,350) 130행: p50 1,758 / p90 3,289 / max 6,578자.
구성: [ASSISTANT] 분석 보고서 103(79%) + [USER] 대화 입력 19 + conversation 7.
FTS 존재 130/130, 벡터 존재 122/130.

**mid-query(본문 55% 지점 200자) 자기 행 rank: ≤30 = 2/41 (4.9%), median 972.**
→ 장문에 답이 중간에 있으면 벡터 lane으로 사실상 회수 불가. excerpt-120은 머리 제목만 노출.

## 실측 4 — 규칙 800자 청킹: 벡터 순위 효과 없음

동일 41행·mid-query를 청크(max cos)로 다시 계산:

| 지표 | whole | 800자 청크 |
|---|---|---|
| top-30 | 4.9% | 4.9% |
| top-100 | 7.3% | 9.8% |
| median | 973 | 918 |

개선 미미. 청킹은 "벡터 회수"를 구제하지 못함. (절대 유사도 부족 + 개별 청크도 풀에서 경쟁력 없음)

## 실측 5 — 실제 파이프라인 스크래치 검증 (stage1d) ★핵심

라이브 DB 사본 2개: baseline(현행) vs chunked(48 long 행 → 223 chunk 행, FTS·vec0 재구축, 청크 임베딩).
실제 lane pool(`build_lane_pool`) + 게이트(`_filter_and_rank`)로 동일 mid-query 48건 실행:

| 지표 | baseline | chunked |
|---|---|---|
| **pool hit** | 41/48 (85.4%) | 41/48 (85.4%) |
| **gate hit** | **10/48 (20.8%)** | **40/48 (83.3%)** |

- pool 형성은 동일 (청킹이 회수를 넓히지 않음 — 실측 4와 일치)
- **게이트 통과가 4배 (+30건)**: 어휘 게이트(min_distinctive=2, min_coverage=0.30)가
  "행 전체 content" 기준이므로, 장문 1행은 중간 답이 쿼리와 어휘 겹침 미달로 탈락하지만,
  답이 있는 청크는 겹침을 만족 → 통과. **청킹 = "회수"가 아니라 "게이트 통과(노출)" 레버.**
- pool 0/48이었던 7건은 청킹으로도 0 — 벡터 절대 유사도 부족, 청킹 무관.

### stage1d 주의사항 (재실행 시)
- **chunk 삽입 전 parent 스냅샷 필수** — parent 먼저 DELETE하면 삽입 루프가 전부 continue → chunk 0개 + 삭제만 된 DB로 잘못 비교 (1차 실행에서 실제 발생, 전멸로 오판)
- sqlite_vec.load는 `enable_load_extension(True)` 후 호출해야 함 ("not authorized" 방지)
- vec0 재구축·int8 양자화 필요 (`vec_quantize_int8(?, 'unit')`)
- 스크래치 DB는 실행 시작 시 삭제 (stale 산출물 무효화)

## 실측 6 — 실사용 gold 검증 (stage2, ★최종 판정 근거)

**gold 구축**: query_log 83건 + 장문 행 출처 세션 transcripts(user 발화)에서 후보 (쿼리, 행) 155건 추출
→ 행별 최적 쿼리 38건을 사용자가 판정(VALID/PLAUS/IRREL + 답이 mid인지) → **VALID+mid=YES 19건 확정**
(idx 21은 에이전트 재검토로 PLAUS→VALID 교정, 사용자 승인). gold: `data/stage2_final_gold.json`.

동일 stage1d 스크래치(baseline vs chunked)를 이 **실사용 쿼리 19건**으로 실행:

| 지표 | baseline (현행) | chunked (800자 저장) |
|---|---|---|
| **pool hit** | **15/19 (78.9%)** | **10/19 (52.6%)** |
| **gate hit** | **1/19 (5.3%)** | **8/19 (42.1%)** |

- **baseline gate 1/19 (5.3%)**: 현행 시스템은 mid-답 장문을 실사용 쿼리로 **사실상 회수 불가**.
  pool 15/19로 답이 이미 풀에 있는데도 게이트가 14건을 탈락시킴 → 병목은 회수가 아니라 **어휘 게이트**.
- **chunked gate 8/19 (42.1%)**: 저장 청킹은 게이트를 8배 통과시키지만,
  **pool 15→10 (5건 손실)** — 청크별 벡터가 전체 행 벡터보다 유사도가 낮아져 vec lane에서 이탈.
  (자기발췌 실측 5의 pool 동일 유지와 달리, 실사용 쿼리는 어휘·벡터 신호가 약해 손실이 드러남)

## 실측 7 — 게이트 입력 변환(chunkmax) 파일럿 (stage3, ★기각 확정)

`_filter_and_rank`의 어휘 겹침을 "행 전체" → "800자 청크별 max"로 바꾼 변형을
스크래치(0콜, 라이브 DB read-only)에서 구현해 실측:

| 지표 | real 게이트 | chunkmax 게이트 |
|---|---|---|
| A) 실사용 gold 19 gate pass | 1/19 | **1/19 (개선 0)** |
| B) op 90 regression (gate pass) | 81/90 | 81/90 (손실 0) |

**원인 분해 (gold 19 벡터 rank 실측)**:
- whole rank ≤2 (vec-2 예외로 살아날 수 있는): **1건** (01dfeb2168, rank 2)
- chunk rank ≤2: **0건** — 청킹해도 어떤 gold도 벡터 상위로 오르지 않음
- 대부분 rank 400~1600 (꼬리)

**즉 stage1d 저장 청킹이 8/19 통과한 것은 "청크 행이 풀에 많이 들어와 어휘로 통과"한 것**이지
"청크 벡터가 상위"라서가 아니었다. 행을 유지한 채 게이트만 청크로 바꾸면(본 파일럿) 개선 0.

## 실측 8 — ★반전: "[ASSISTANT] prefetch 제외" 정책이 진짜 병목 (외부 AI 검토 후 재검증)

세 AI 검토(b-ai "게이트 파라미터 불일치", a-ai "sanity 검사", c-ai "청크 독립 행 구조")를 받은 뒤
**전 실측을 재검증**한 결과, 실측 6/7의 "gate 1/19"는 **게이트·청킹 문제가 아니라
`_PREFETCH_EXCLUDED_PREFIXES = ('[ASSISTANT]',)` 정책 때문**이었다:

- gold 19건 중 **18건이 `[ASSISTANT]` 프리픽스** (plain 장문 131행 중 [ASSISTANT] 103건 = 79%와 동일 구성)
- `_filter_and_rank`는 `content.startswith('[ASSISTANT]')` → **게이트 전에 continue (설계상 prefetch 제외)**
- 나머지 1건([USER])만이 실제 prefetch 대상 → 1/19은 **설계대로의 동작**

**재실측** (동일 gold 19, 제외 해제 = 프리픽스 스트립만 적용):

| 조건 | gate pass |
|---|---|
| 현행 ([ASSISTANT] 제외 유지) | 1/19 |
| **[ASSISTANT] 제외 해제** (프리픽스 스트립) | **8/19** |

**해석 정정**:
- 저장 청킹(8/19)이 통과한 것은 청크 행이 `[ASSISTANT]` 프리픽스를 잃어 **제외를 우회**했기 때문 (게이트 개선 아님)
- chunkmax(1/19) 개선 0도 제외가 그대로라 그랬던 것
- "게이트 파라미터 (2,0.30) vs (1,0.0)"은 라이브 데몬·스크래치 모두 (2,0.30)으로 **영향 없음** (b-ai 지적은 실측상 기각)

## 종합 판정 (반전 반영, 최종 확정)

1. **"장문 mid-답 회수 불가"의 실체 = `[ASSISTANT] prefetch 제외 정책`**.
   실제 병목은 청킹·게이트·벡터가 아니라 **정책 1줄** (`_PREFETCH_EXCLUDED_PREFIXES`)이었다.
2. **저장 청킹 / chunkmax: 전부 기각 유지** — 실측 4/6/7의 결론은 유효하나,
   문제 정의 자체가 달라졌으므로 이들은 "잘못된 문제에 대한 해법"이었다.
   **단, "JEV semantic chunking(문장별 continuation) 자체는 직접 검증하지 않았다** —
   실측한 것은 규칙 기반 800자 paragraph-aware 청킹뿐. JEV chunking 기각은
   "JEV를 쓸 이유가 없음"(규칙 청킹도 벡터를 못 살림, 실측 4)의 의미로 한정해
   해석해야 하며, JEV continuation 품질 자체의 실측은 아직이다 (c-ai 지적 반영).
3. **새로운 쟁점**: "[ASSISTANT] 메모리를 prefetch에서 제외하는 정책이 맞는가?"
   - 스킬 기록: "[ASSISTANT] 프리픽스는 _PREFETCH_EXCLUDED_PREFIXES로 전부 제외(설계 의도)" — 어시스턴트 발화는
     노이즈로 보고 제외하는 정책
   - 그러나 assistant 장문 보고서(103건)에는 **사용자가 나중에 찾는 답이 실려 있음** (gold 8/19가 증거)
   - 즉 "assistant 노이즈" vs "assistant 보고서 회수 가치"의 정책 트레이드오프가 남은 핵심 질문
4. **다음 단계 (미실행)**: [ASSISTANT] 제외 해제가 기존 recall 품질(op 90, shadow)에 미치는 회귀 측정
   → 회귀 0이면 **정책 변경 1줄**로 gold 1/19→8/19 달성 가능 (청킹 불필요)

## 실측 9 — [ASSISTANT] 제외 해제 회귀 측정 (★채택, 코드 반영 완료)

`_PREFETCH_EXCLUDED_PREFIXES`에서 `[ASSISTANT]`를 제거하는 정책 변경의 회귀를
op-90 골드(90) + 무답(10)으로 0콜 실측 (`stage9_assistant_exclusion_regression.py`):

| 지표 | with-excl (현행) | without-excl (해제) |
|---|---|---|
| op-90 gold gate pass | 81/90 | **81/90 (손실 0, 변화 케이스 0)** |
| noans 오주입 (게이트 통과 유무) | 10/10 | 10/10 (변화 없음) |
| noans 통과 셋 중 [ASSISTANT] 행 | 0 | **0** |
| pool 내 [ASSISTANT] 비중 (op90) | 29% | 29% |

**해석**:
- op-90 정답 회수 손실 0 — 기존 recall 품질 불변.
- noans 오주입 증가 0 — 무관 [ASSISTANT]는 `_filter_and_rank`의 어휘 겹침·커버리지로
  이미 차단됨. 제외는 **이중 안전장치**였을 뿐, 실질 필터는 게이트가 담당.
- pool 내 [ASSISTANT] 29%는 그대로지만 게이트 통과까지 가는 건 관련성 있는 것뿐 (noans 0).

**채택 확정 (사용자 승인 2026-10-05)**: `gateway/j1_pipeline.py`의
`_PREFETCH_EXCLUDED_PREFIXES = ("[ASSISTANT]",)` → `()` 변경. 커밋 포함.
효과: 장문 assistant 보고서(사용자가 나중에 찾는 답) 회수 gold 1/19 → 8/19.
청킹·스키마 변경·콜 증가 전부 불필요.

**잔여 관찰**: 데몬 재시작 후 shadow/enforcement로 실사용 변화 관찰 권장.
(코드 변경은 라이브 데몬 재시작 시 반영 — RPC 경로 `pipeline.py`는 동일 모듈 import)

---

## 후속 실측 (2026-10-05 오후, 3종 AI 검토 후속)

### 실측 10 — ★임베딩 하네스 버그 발견 (b-ai "sanity 검사" 지적이 맞았음)

**직접 `TextEmbedding()` 호출이 `BAAI/bge-small-en-v1.5`를 로드** — sitecustomize가
`MNEMOSYNE_EMBEDDING_MODEL=bench/bekko-a8m`을 강제하는 건 **beam 경로에만** 적용되고,
fastembed 직접 생성은 기본 모델로 폴백했다. (실측: 같은 문장 fastembed vs beam cosine ≈ 0.02)

→ **stage1b/1c/3의 벡터 순위 실측 전부가 bge-small로 돈 것** → "chunk rank≤2=0건"(실측 7)은 무효.
단 stage1d(파이프라인 경유)·stage9(운영)은 beam 경유라 유효.

**교훈**: 실험 스크립트에서 임베딩은 항상 `mnemosyne.core.embeddings`(beam 경유)를 쓸 것.

### 실측 10b — 정확한 모델(bekko-a8m)로 재실측 → 결과 역전

| 지표 | bge-small (잘못됨) | bekko-a8m (정확) |
|---|---|---|
| gold 19 whole rank median | 400~1,600 | **107** |
| whole rank ≤2 | 1건 | 2건 |
| **chunk rank ≤2** | **0건** | **10건!** |

맞는 모델에선 청크가 벡터 상위로 확실히 올라간다 — stage1c의 "청킹 무효"는 모델 버그의 인공물.

### 실측 11 — parent multi-vector (chunk-lane) 단독 회수

227청크 sidecar를 쿼리-vs-청크 max로 collapse: **top-5 11/19, top-19 18/19** (whole 5/19 대비 +13).

### 실측 12 — ★chunk lane 통합 → 하네스 오류로 "이득 0" 판정 무효 (2026-10-05 재검토로 번복)

**원래 결론**: 실제 파이프라인(5번째 레인으로 통합, 부모 collapse) → gold pool 15/19 그대로, gate 8/19 그대로,
op-90 회귀 0, noans 0 → "이득 0, parent multi-vector 기각" (로 기록됐으나)
**c-ai 재검토(2026-10-05)에서 무효 확인**: `build_lane_pool()`은 실제로 `fts/vec/imp/graph` 4개 lane만
호출하고 `"chunk"` kind는 union에 **포함시키지 않았다** (recall_raw에만 구현, 호출 경로 없음).
→ "통합 실측"이 실제로는 통합이 아니었음.

**정정**: stage12의 "이득 0"은 **하네스 오류로 미검증**. stage11(청크 단독 top-19 18/19)은 유효.
**진짜 통합은 stage23에서 재실측 → gold pool 13/19 → 16/19 (+3), gate도 +3.**
  - 새로 잡힌 3건: `afd156a9`(rank 42 — 단, POOL_BUDGET 60 컷 밖이라 gate 실해당 2건), `77fff372`, `0a32589e`
  - POOL-MISS 4건 중 1건만 구제(`afd156a9`), 나머지 3건은 chunk lane으로도 불가
→ "parent multi-vector 기각"은 보류, 운영 반영 여부는 추가 판단 필요 (아래 실측 23).

### 실측 13 — 잔여 탈락 11건 분석

pool 15 → gate 8의 7건: 대부분 **게이트 통과는 하지만 top-40 랭크 컷**(gate_rank 44~104) — 게이트 로직 문제가 아니라 POOL_BUDGET 컷오프. POOL-MISS 4건은 구조적 한계.

### 실측 14 — POOL_BUDGET 스윕 (40→100)

| 컷 | gold gate | op-90 | noans |
|---|---|---|---|
| 40 | 8/19 | 81/90 | 10/10 |
| 50 | 11/19 | 81/90 | 10/10 |
| 60 | 12/19 | 81/90 | 10/10 |
| 80 | 13/19 | 81/90 | 10/10 |
| 100 | 14/19 | 81/90 | 10/10 |

### 실측 15 — ★Jev 실제 lift 확인 (무료 레인, 6건 × 컷)

게이트 통과 ≠ Jev가 1위로 lift. 실측:

| gold (gate rank) | cut 60 | cut 80 | cut 100 |
|---|---|---|---|
| 97bca6e2 (44) | **GOLD#1 ×2** | NO-PICK | NO-PICK |
| 0e2418bb (44) | other ❌ | NO-PICK | NO-PICK |
| 8c43c4f6 (46) | other ❌ | NO-PICK | NO-PICK |
| 01dfeb21 (51) | other ❌ | NO-PICK | NO-PICK |
| f76a006d (66) | (컷 밖) | NO-PICK | NO-PICK |
| 77fff372 (87) | (컷 밖) | NO-PICK | NO-PICK |

**핵심**: ①실질 lift는 1/6건(97bca6e2)뿐 ②**cut 80/100은 abstain 폭증으로 전멸** — 풀을 키울수록
Jev가 기권. → **POOL_BUDGET 60이 실질 상한, 80/100은 역효과로 기각.**

### ★적용 (사용자 승인 2026-10-05): POOL_BUDGET 40 → 60

`gateway/j1_pipeline.py` `POOL_BUDGET=60` + `POOL_DEFAULT_TOP=60`. 토큰 +50%(≈+1,360/쿼리,
연간 ~$11~22, 무시 가능), 콜 수 불변(쿼리당 1콜). 데몬 재시작 반영 필요.

### 실측 16 — 장문 노출율 (b-ai #12, ★높음)

(2026-10-05 b-ai 재검토로 "기저율"→"노출율" 표현 정정: 아래 수치는 "장문 행이 풀/gate에
하나라도 있는 쿼리 비율"로, 장문 행이 코퍼스의 ~8%(136/1,738)이고 풀이 60개라
구성에서 나오는 값 — "정답 근거가 장문인 쿼리 비율"(진짜 기저율)은 아님.)

query_log 115건 중 비기계 87건 대상, 장문(plain >1,350자 136행) 노출 실측:

| 지표 | 결과 |
|---|---|
| long 행이 pool에 있는 쿼리 | **87/87 (100%)** |
| long 행이 gate 통과 top-60에 있는 쿼리 | **85/87 (98%)** |
| long 행이 top-1인 쿼리 | 0/87 (0%) |

- **기저율 98% — b-ai의 "5% 이하면 접자" 조건 불충족**. 장문 노출은 실사용에서 보편적.
- **진짜 갭: 장문은 gate까지 오지만 top-1로 선택된 적 0건** — choice 120자 head 절단이 실질 원인 후보.
  → #6 답 구간 발췌 파일럿의 근거.

### 실측 17/18 — ★답 구간 발췌(snippet 윈도우) 파일럿 (b-ai #6, 채택)

`_query_window`: 본문에서 쿼리와 어휘 겹침이 최대인 300자 구간을 50자 스텝으로 탐색 →
150자 excerpt로 라벨 생성. **장문(>800자) 행에만 적용, 단문은 head-100 유지** (부분 반영).

| 지표 | baseline (head-100) | snippet (부분 반영) |
|---|---|---|
| gold 12건 lift (2회) | 6/24 | **10/24 (+2)** |
| 새로 lift된 gold | — | 0e63e2c7, 05ab2f73 (pos 25·28) |
| 손실 | — | 0건 |
| op-90 서브셋(40) gold-pick | — | 개선 1, 회귀 0 |
| noans 6건 | — | 변화 0 (동일 인덱스) |
| 결정성 | 87483f 비결정(9↔24) | 2회 모두 동일 |

- head 절단이 장문 gold lift를 실제로 막고 있었고, 쿼리 인지 윈도우가 해소.
- **부분 반영이 전면 반영과 동일 효과** (단문은 head가 이미 본문 대부분을 커버 — 윈도우 불필요).
- **적용 (사용자 승인 2026-10-05)**: `jev_rerank` 라벨 생성에 `_query_window` 반영
  (gateway/j1_pipeline.py, 커밋 예정). 토큰 증가: 장문 후보 수×50자, 연간 ~$30 무시 가능.
  로컬 윈도우 스캔 비용: 쿼리당 수십 ms (무시 가능).

### 실측 19 — ★episodic 벡터 "누락"은 오해 (b-ai #15 해소)

"벡터 없는 장문 8행" 조사 → **episodic_memory 113행 전부 memory_embeddings에 없음**이 확인됐으나,
실제로는 **`vec_episodes`(vec0 가상테이블)에 113행 전부 존재** (S4 설계: "episodic은 vec_episodes에만
존재, 재임베딩 제외" — `s4-embedding-migration-plan.md` 57행). **정상 상태, 누락 아님.**

- 교훈: **임베딩 유무 진단은 `memory_embeddings` + `vec_working`/`vec_episodes` 모두를 읽어라.**
  JSON만 보면 episodic이 전부 "벡터 없음"으로 오판한다.
- stage12(통합 파일럿)은 `_wm_vec_search`(beam, vec0 경유)를 사용해 영향 없음 — 결론 유효.

### 실측 표기 보정 — gold 19의 독립 쿼리 수 (c-ai #11)

stage2 gold 19건은 **독립 쿼리 14개 + 행 중복 매칭 5건** ("recall 배제..."가 3개 행,
"fit 피드백..."·"3차 외부 검토..." 등이 복수 행). "19건" 수치는 관측/시도 수로,
독립 질문 정확도로 읽지 말 것. (방향성 결론엔 영향 없음 — 전체 14개 쿼리에서도
baseline gate 1건 통과는 동일.)

### 실측 21 — 구체 CI + exact McNemar (a/b-ai #14)

| 수치 | Wilson 95% CI |
|---|---|
| gold 1/19 (제외 전) | [0.9%, 24.6%] |
| gold 8/19 (제외 해제) | [23.1%, 63.7%] |
| gold 12/19 (POOL_BUDGET 60) | [41.0%, 80.9%] |
| lift 6/24 (baseline) | [12.0%, 44.9%] |
| lift 10/24 (snippet) | [24.5%, 61.2%] |

Exact McNemar (lost=0 개선, p = 2·(0.5)^gained):
- 제외 해제 (gained 7): **p=0.0156 — 유일하게 <0.05**
- POOL_BUDGET 60 (gained 4): p=0.125
- snippet (gained 2, **독립 반복 기준**): p=0.5

(2026-10-05 b-ai 재검토 정정: "gold 12건 × 2회 = 24"는 **가짜 반복** — 같은 입력이면
같은 출력이므로 24는 사실상 12. snippet 순이득은 2건(gained 2, lost 0)이고 p=0.5.
stage18의 "6/24→10/24"는 "3/12→5/12"로 읽어야 하며, Wilson CI도 n=24가 아닌 n=12 기준.
또한 snippet은 이후 stage23 all-candidate 검증(5/16, +2)에서 재확인됨.)

**해석**: 제외 해제만 <0.05. POOL_BUDGET/snippet은 소표본이라 "유의미"라고 단정 불가 —
그러나 **lost=0으로 회귀 위험 0, 방향 일관**. 소표본 한계를 정직하게 표기한다.

### 실측 22 — ★사이드카 FTS 레인 → 하네스 오류로 "이득 0" 판정 무효 (2026-10-05 재검토로 번복)

**원래 결론**: "청크 전용 FTS5(227청크) 5번째 레인 → gold 12/19 그대로, op-90 회귀 0, noans 0 → 이득 0, 기각 확정"
**c-ai 재검토(2026-10-05)에서 무효 확인**:
  - `chunk_lane_fts()`는 실제로 `return []`만 함 (FTS5 검색 미구현 — 죽은 코드)
  - 실제 경로는 `chunk_lane_cjk()` = **한글 문자 set 교집합 수작업 스코어** (FTS5 아님)
  - 이것도 `build_lane_pool()`이 `"chunk"` kind를 호출하지 않아 RRF 통합 안 됨 (stage12와 동일 하네스 오류)

**정정**: stage22의 "이득 0"은 **하네스 오류로 미검증** — 실제 FTS5/RRF 통합은 측정된 적 없음.
사이드카 FTS 레인 자체는 stage23의 청크-vec 레인(진짜 통합) 결과와 함께 판단:
stage23에서 chunk-vec는 pool +3 — FTS5가 vec보다 나을 이유는 없으나, "이득 0 확정" 표현은 폐기.
### 실측 23 — ★진짜 통합 (chunk-vec lane, RRF 5레인) + all-candidate snippet (c-ai/b-ai 반영, 2026-10-05)

stage12/22의 하네스 오류를 고쳐 `build_lane_pool`을 모방한 커스텀 pool로
fts+vec+imp+graph+chunk(vec) **5레인 RRF를 진짜 합산**:

| 지표 | base (4레인) | +chunk-vec레인 |
|---|---|---|
| gold 19 pool | 13/19 | **16/19 (+3)** |
| gold 19 gate | 13/19 | **16/19 (+3)** |
| 새로 잡힌 | — | `afd156a9`(rank 42, 60컷 밖 — gate 실해당 2건), `77fff372`, `0a32589e` |
| POOL-MISS 4건 | — | 1건만 구제(`afd156a9`), 3건(`329fb315`/`f66a777d`/`77f9a2b2`) 불가 |

→ **parent multi-vector는 stage11(단독 강함) + stage23(+3)로 재평가 필요.** 기각 보류.

**all-candidate snippet (production 형태, gold gate-pass 16건, Jev 무료 레인):**
- head: 3/16, all-snippet: **5/16 (+2), 손실 0** — stage18(target-only)과 동일 방향, production 재현 확인.
- b-ai 지적대로 stage17/18은 gold target에만 snippet 적용이라 "production 전체 후보" 검증이 아니었음 → 이번에 해소.

**POOL_MISS 4건 잔여 판정**: 3건은 chunk lane으로도 불가(구조적) — 허용 손실로 정리 가능.

### 실측 23-판단 — chunk-vec lane 운영 반영 여부 (2026-10-05, **보류 — 기록만**)

stage23에서 진짜 통합은 +3 pool (+2 gate 실효) 확인했으나:

| 고려 | 내용 |
|---|---|
| 실효 이득 | gold 19 중 **2건** (`77fff372`, `0a32589e`) — `afd156a9`는 rank 42로 60 컷 밖 |
| 비용 | 청크 임베딩 227건 저장(쓰기 시 계산) + chunk lane 1개 + 동기화 로직 = 영구 인프라 |
| c-ai 기준 | "POOL-MISS 4건 중 0건이면 닫아도 됨" → 실제 1건만 구제(그마저 컷) |
| 사용자 판단 | **2026-10-05: 보류 (기록만). shadow enforcement 실측(3~5일 후)에서 "장문 답 누락이 실제로 자주 발생"이 확인되면 그때 재검토** |

→ chunk-vec lane은 **미채택 (shadow 후 재판정 예약)**. 코드는 운영 반영 안 함, 실측 스크립트(stage23)만 보존.

### 실측 24 — 하네스 패리티 (b-ai #5, 2026-10-05)

실험 하네스 vs 운영 RPC(`pool_ids`로 게이트 통과 id 비교): **gold 8건 8/8 완전 일치.**
- stage24b가 처음에 "불일치 8/19"를 보였으나, 이는 RPC context가 **Jev rerank 후
  final 상위만 렌더**하기 때문 (렌더 범위 차이). `pool_ids`(게이트 통과 60건)로 비교하면 완전 일치.
- b-ai가 우려한 "실험 ≠ 운영" (임베딩 폴백·RPC 컷·게이트 파라미터)은 **현재 모두 해소** 확인.
- 재발 방지: 패리티 스크립트(stage24b) 유지.

### 실측 25 — 하네스 오염 전수 점검 (b-ai #5, 2026-10-05)

`experiments/` 전체에서 직접 임베딩 호출 검색:
- **오염(무효)**: `stage1b`, `stage1c`, `stage1_vector_dilution` (fastembed 폴백 bge-small),
  `stage1d_scratch_pipeline` (청크=bge / 쿼리=bekko **모델 불일치**)
  → stage1b/c/d/vector_dilution의 벡터 결론은 전부 무효 (이미 stage10b가 정정한 영역의 동일 원인 확장)
  - 단, **저장 청킹 기각(FTS 기반)** 과 chunkmax(어휘 기반)는 벡터 무관이라 유효.
- **정상**: `stage10`(의도적 bge 진단), `stage10b`(beam), `embed_dataset_eval2`(MODEL 지정 시),
  `harnesses/hermes_j1`/`app.py`(검증 코드).
- 교훈: **모든 실험 스크립트는 `mnemosyne.core.embeddings`(beam) 경유로 통일**하거나
  시작 시 모델명·차원 assertion.
