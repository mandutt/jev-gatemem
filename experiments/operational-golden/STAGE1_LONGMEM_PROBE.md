# Stage-1/2 Probe: 장문 메모리 문제 실측 (jev chunking 파일럿) — 최종

- 날짜: 2026-10-05
- 방법: 0콜 결정적 probe — JEV 호출 0회, DB read-only, 로컬 bekko-a8m 임베딩
- 스크립트:
  - `stage1_longmem_probe.py` — DB 분포 + 골드 길이
  - `stage1b_plain_long_census.py` — plain 장문 전수 규격 + mid-query 벡터 회수
  - `stage1c_chunk_recall.py` — 800자 규칙 청킹의 벡터 순위 효과 (numpy)
  - `stage1d_scratch_pipeline.py` — **실제 파이프라인 스크래치 검증** (청크 행 저장 시 pool/gate)
  - `stage2_*` — 실사용 gold 구축 (query_log + 세션 transcripts, 사용자 판정 38건)
- 판정: **① JEV chunking·저장 청킹·chunkmax 전부 기각 ② 그러나 "gate 1/19"의 진짜 원인은 `[ASSISTANT] prefetch 제외 정책` — 제외 해제 시 8/19. 청킹은 잘못된 문제에 대한 해법이었음.**
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
2. **JEV chunking / 저장 청킹 / chunkmax: 전부 기각 유지** — 실측 4/6/7의 결론은 유효하나,
   문제 정의 자체가 달라졌으므로 이들은 "잘못된 문제에 대한 해법"이었다.
3. **새로운 쟁점**: "[ASSISTANT] 메모리를 prefetch에서 제외하는 정책이 맞는가?"
   - 스킬 기록: "[ASSISTANT] 프리픽스는 _PREFETCH_EXCLUDED_PREFIXES로 전부 제외(설계 의도)" — 어시스턴트 발화는
     노이즈로 보고 제외하는 정책
   - 그러나 assistant 장문 보고서(103건)에는 **사용자가 나중에 찾는 답이 실려 있음** (gold 8/19가 증거)
   - 즉 "assistant 노이즈" vs "assistant 보고서 회수 가치"의 정책 트레이드오프가 남은 핵심 질문
4. **다음 단계 (미실행)**: [ASSISTANT] 제외 해제가 기존 recall 품질(op 90, shadow)에 미치는 회귀 측정
   → 회귀 0이면 **정책 변경 1줄**로 gold 1/19→8/19 달성 가능 (청킹 불필요)