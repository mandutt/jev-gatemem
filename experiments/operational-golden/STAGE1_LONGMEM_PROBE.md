# Stage-1 Probe: 장문 메모리 문제 실측 (jev chunking 파일럿 0단계) — 최종

- 날짜: 2026-10-05
- 방법: 0콜 결정적 probe — JEV 호출 0회, DB read-only, 로컬 bekko-a8m 임베딩
- 스크립트:
  - `stage1_longmem_probe.py` — DB 분포 + 골드 길이
  - `stage1b_plain_long_census.py` — plain 장문 전수 규격 + mid-query 벡터 회수
  - `stage1c_chunk_recall.py` — 800자 규칙 청킹의 벡터 순위 효과 (numpy)
  - `stage1d_scratch_pipeline.py` — **실제 파이프라인 스크래치 검증** (청크 행 저장 시 pool/gate)
- 판정: **"저장 시 규칙 청킹 (800자) = 게이트 통과율 개선 레버"로 확정. JEV chunking은 불필요.**
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

## 종합 판정

1. **JEV chunking (continuation/boundary choice): 기각** — 실측 4에서 규칙 청킹도 벡터 회수를 못 살림.
   JEV가 추가로 줄 이득 없음. (2단계 JEV 비교 불필요)
2. **규칙 800자 청킹 저장: 게이트 통과율 실질 개선 확인 (20.8% → 83.3%)** — 채택 후보.
   단, 이득은 자기발췌 mid-query 기준. **실사용 쿼리로 재확인 필요**.
3. **잔여 한계**: 벡터 lane의 절대 유사도 문제(pool 0인 7건)는 청킹으로 해결 불가.

## 다음 단계 (미실행)

- 실사용 검증: 장문 행에 실제로 답을 찾는 자연 쿼리 10~20건을 큐레이션해 stage1d 프레임워크로 재검증
- 채택 시 설계: 쓰기 경로 KEEP 장문 → 800자 청크 행 저장(부모 참조 meta `chunk_of`/`chunk_idx`),
  읽기 경로: prefetch가 청크 반환 시 부모 묶음 노출. 코드 변경 3곳 + 회귀.
  (게이트 입력·prefetch 주입·pool hydration 조정)