# MemPalace (MemPalace/mempalace) 검토 — 설계 정합 2 · 기각 4 · 보류 1, 직접 반영 없음 (0콜 실측)

> 본 검토는 우리 'jev-mem' 프로젝트(과학적 내부 메모리 게이트 데몬)의 관점에서
> 외부 저장소 MemPalace를 대조한 것이다. 학술 'Jev-Mem'(arXiv 2609.23986)·npm
> 'jevmem'(Avinash-jetwani)·혼동 금지 — 이름만 유사한 별개 프로젝트들이다.
> 판정은 소스 대조(tree API + raw 파일 12종 fetch)와 라이브 trace 실측(0콜)으로만
> 내렸다. JEV API 호출 없음. 코드 변경 없음.

- 검토일: 2026-10-10 (토)
- 대상: https://github.com/MemPalace/mempalace (branch `develop`, v3.11.0, MIT)
- 방식: GitHub tree API(`git/trees/develop?recursive=1`, 854파일) → 핵심 소스 12종 raw fetch → 소스 대조 + 라이브 trace(10-07~10-09) 상대시간 표현 유병률 0콜 실측
- 재현 경로: `hermes-made/reviews/mempalace-review/` (tree JSON + fetch된 소스 사본)

## 0. 대상 요약 (소스 기반)

MemPalace는 **로컬 우선·verbatim 저장·플러그형 백엔드(ChromaDB 기본)의 대화/문서 마이닝 메모리 시스템**이다. 요약·추출 없이 원문 그대로 저장하고, 사람·프로젝트를 wing, 주제를 room, 원문을 drawer로 구조화한다. 검색은 하이브리드(벡터 + BM25)이며, 자체 벤치(LongMemEval 500문항): raw R@5 96.6% / hybrid v4(450q 홀드아웃) 98.4% / hybrid+LLM rerank ≥99%.

핵심 소스 상수·메커니즘 (fetch 확인):
- `searcher/ranking.py` — union 모드 하이브리드 랭킹: `_hybrid_rank` = **0.6·벡터 + 0.4·BM25(min-max 정규화)** convex 결합; BM25는 후보 집합 내 코퍼스 상대 IDF(Lucene smoothed, `log((N−df+0.5)/(df+0.5)+1)` — 항상 non-negative); 동점 시 `authored_at` 최신 우선 tie-break
- `searcher/candidates.py` — 후보 풀 크기: 무창 `n_results*3`, 날짜창 활성 시 `n_results*15`(캡 500); union 모드는 벡터 후보를 `n_results`로 자른 뒤 BM25 후보 병합; closet 확장(±1 sibling chunk), `_fold_copies_across_sources`(≥100자 동일 텍스트를 소스 간 접어 `also_in`으로 표기), `_dedupe_rendered_hits`(closet 경유 중복 제거)
- `searcher/sqlite_bm25.py` — HNSW 손상(#1222) 시 **Chroma 자체 FTS5 trigram 인덱스 → BM25 재랭크 폴백** (옵트인 stop-word 필터, 날짜창 SQL prefilter: ISO day-granularity narrowing + Python 재검증)
- `date_window.py` — `[since, before)` 반개구간; `filed_at` 누락/미파싱 행은 창 활성 시 **제외**(미지 연령 행의 조용한 포함 금지)
- `knowledge_graph.py` — SQLite 로컬 temporal KG: `valid_from`/`valid_to` 반개구간 `[from, to)` + `as_of` 시점 쿼리 (idx_triples_valid 인덱스)
- `dedup.py` — source_file 그룹 내 코사인 **거리 <0.15**(≈유사도 0.85)면 longest-first greedy keep; delete 허용
- `dynamics.py` — hall/tunnel 연결에 Hebbian potentiation(+0.05, max 5.0) + Ebbinghaus decay `strength·exp(−days/stability)` floor 0.05; **그러나 정작 hall/tunnel에는 wiring 안 됨** (docstring: "nothing potentiates them on access, nothing decays them"; `_render` 노출 순위에는 무영향 — 현재는 dead math)
- `hlc.py` — RFC 004 복제 op 정렬용 Hybrid Logical Clock (unix_ms 13자리-카운터 6자리-replica_id)
- `entity_detector.py`(921줄), `layers.py`(L0 identity/L1 essential-story), closet LLM — 추가 소스 확인
- README 강조: "verbatim, no summarization/extraction/paraphrase", "Nothing leaves your machine unless you opt in", 임베딩 openai-compat 서버 옵션, 멀티링궐 embeddinggemma-300m

## 1. 축 대비 표 (우리 jev-mem vs MemPalace)

| 축 | jev-mem(우리) | MemPalace | 관계 |
|---|---|---|---|
| 저장 단위 | 턴 단위 발화(게이트 통과 행) | verbatim drawer(chunk) | 대척(마이닝) |
| write-time 게이트 | JEV G-qual/G-AS (LLM 판정) | **없음** — 전량 저장 | 우리 우위 |
| read-time 판정 | JEV choice rerank 1콜 (pool 60) | LLM rerank 옵션(단계 3, top-20) | 우리 우위(비용) |
| 랭킹 퓨전 | RRF k=30/60(+lane 단독) | hybrid 0.6·vec+0.4·BM25(min-max) | 기각(아래 C1) |
| 어휘 검색 | FTS5 + `_cjk_like_search` | BM25(Lucene smoothed IDF, 후보 내) | 참고(우리 CJK 스코어링 갭) |
| 무답 처리 | abstain 라벨 + soft gate τ=0.3 | 없음(유사도 floor 없음) | 우리 우위 |
| 점수 절대 임계 | 금지(stage100—JEV score-floor 금지) | 유사도 절대 임계 없음(창·max_distance만) | **정합** |
| 구버전/신버전 | supersede 113행 + valid_until 159행(read-time 필터) | temporal KG valid_from/to + `date_window` | 기능 동등(우리 SQL read-path가 우위) |
| 시점 쿼리 | read-time SQL 필터 | `date_window.py` 반개구간 `[since,before)` | **정합** |
| 중복 처리 | write-path dedup 없음(재전송 dedup 후보) | `dedup.py` delete 허용 | 기각(아래 C2) |
| 시간 표현 부스트 | 없음 | hybrid v2 'N일 전' 파싱 + 40% 거리 감소 | 보류(아래 C4) |
| 강도/decay | 없음 (Run R: recall-strength 기각) | `dynamics.py` Hebbian+Ebbinghaus | 기각(아래 C3) |
| 벤치 주장 | pool_recall 90.0%·op hit@1 78/79 (자체 실측) | R@5 96.6% raw / 98.4% hybrid (자체 보고) | 분리 표기 |

## 2. 판정 상세

전체 판정: **직접 반영 없음(0콜·코드 미변경)** — 정합 2 · 기각 4 · 보류 1.

### 정합(설계 표준성 근거)

- **P1. 유사도 절대 임계 없음 / 시점 반개구간** — MemPalace는 검색에서 유사도 스코어 절대 임계로 무답을 자르지 않는다(절대 임계는 `max_distance` 옵션·날짜창뿐). 우리 stage100 'JEV score-floor 절대 임계값 금지'·`[since,before)` valid_until 반개구간과 독립적으로 일치. 외부 구현이 같은 설계를 쓰는 것은 우리 설계의 표준성 신호.
- **P2. '하이브리드 = 단일 랭커 갭을 두 신호 결합으로 보완' 방향** — sift(txtai dense+BM25)와 함께 dense+BM25 결합 표준성 지지(우리 RRF k=30/60 계열).

### 기각 (do not re-run)

- **C1. hybrid 0.6·vec+0.4·BM25 convex 퓨전 — 기각(0콜)**: 우리 fusion α=0.7은 2026-10-08 실측 종결 '보류'(op +2/+3·abstain 2→0·noans FP +1, 조건부 신호 없음), convex 퓨전 자체가 우리 실측에서 '구조 변경 채택 없음'으로 끝났다. 또한 BM25를 후보 집합 내 상대 스코어(min-max)로 쓰는 것은 우리 RRF가 이미 lane 단독 순위를 병합하는 방식과 기능 중복 — 재실험 금지. (MemPalace 자체 벤치 논리는 별개 — 그들 raw 96.6%는 LongMemEval 조건의 자체 보고.)
- **C2. near-dup drawer 삭제(`dedup.py`)} — 기각**: 우리 fail-open 원칙(데이터 유실 금지)·실측 기각(2026-10-09 자동 supersede 기각: 84그룹 판정 W49/I27/V8, V 8건 전부 재전송 중복 5+동일 지시 3 — '진짜 새 버전 충돌 0')과 정면 충돌. 삭제가 아니라 read-time 컨텍스트 관리 방향만 우리와 호환.
- **C3. `dynamics.py` Hebbian/Ebbinghaus 강도 — 기각**: 우리 run_r_retrieval_strength 실측 확정 — '회수 강화·decay 강도'는 JEV choice rerank 구조에서 winner 무변화(79/90 순서가 바뀌어도 improved 0/regressed 0), 그리고 MemPalace에서조차 **정작 wiring이 없다**(docstring: "nothing potentiates them on access and nothing decays them") — 실행 코드가 아닌 수학 라이브러리. Hippo decay 기각과 동일 축(do not re-run).
- **C4. 시간 표현 파싱 + 날짜 거리 부스트(hybrid v2) — 라이브 유병률 실측 기각 추천 (0콜)**: MemPalace hybrid v2는 'N일 전/지난주' 패턴을 정규식 파싱해 세션 날짜 거리 40% 감소를 준다. **우리 라이브 트레이스 10-07~10-09 (|jev| 374건 · |pool| 3,278건) 상대시간 참조 실측: JEV 쿼리 374건 중 5건(1.3%), pool 쿼리 중에도 실질 참조는 '어제 날씨/지난주 금요일/내일 복권' 등 극소수** — 대부분 '전에/이후에/후에' 문법 용법이었다(정밀 큐레이션 패턴 사용). 즉 발동률이 낮아(≈1%) 추가 부스트는 실질 이득이 없고, 부스트가 골드 순위를 비틀어(temporal-reasoning 쿼리의 과도한 최근성 페널티) stage90 IDF v2 기각(라이브 발동 1.7%)과 같은 결론. **단, 이 항목은 '기각'이 아니라 '추천' — 실측 계열이지만 우리 골든셋에 temporal-reasoning 쿼리가 없어 JEV 결합 전 폐기 여부를 0콜로 확정하지는 못한다.**

### 보류

- **D1. 수집 라이선스 break-glass 'mine → verbatim drawer' 파이프라인**: 우리는 `[USER]`/`[ASSISTANT]` 행 verbatim 저장을 게이트만으로 행하고 있다(read-path 재구성 불가 문제 없음 — 원문 보존). MemPalace의 대화 마이닝은 그 자체로 '원문 유지 + 문맥 재구성'의 참고 구현이며, **우리 write-path에 drawer/같은 문맥 단위 재구성 레버를 추가하면 저장된 발화의 문맥(=이웃 턴) 소비가 가능**하다. 단, 이는 소비 측 구조 변경(사용자 승인 영역·stage93/94 프레이밍과 교차)이라 별도 실험 전까지 보류한다.

### 분리 표기 (자체 보고)

- 벤치 수치(LongMemEval R@5 96.6%/98.4%/≥99%)는 자체 보고이며, 데이터셋(500문항)/조건(세션 단위 verbatim chunk) 전제가 우리 op-90 골든셋과 다르다. **외부 벤치 수치는 우리 실측과 분리 표기** — 직접 비교 금지.

## 3. 실측 근거 (이 문서의 근거)

| 근거 | 내용 |
|---|---|
| MemPalace 소스 | tree API(854파일)·raw fetch 12종(ranking/candidates/sqlite_bm25/dedup/knowledge_graph/date_window/dynamics/hlc/layers/entity_detector/filters/HYBRID_MODE/BENCHMARKS/pyproject/searcher __init__) |
| 우리 라이브 trace (0콜) | `logs/jev_trace_20261007~09.log`: \|jev\| 374건·\|pool\| 3,278건 — 상대시간 참조 JEV 5/374(1.3%) · pool 실질 참조 극소수(어제/지난주/내일 등, 나머지는 '전에/이후에' 문법 용법) |
| 우리 실측 재사용 | stage100(절대 임계 금지)·fusion α(A/B 보류)·Run R(retrieval 강도 기각)·stage90(IDF 발동률)·자동 supersede 기각(84그룹)·stage103b(timestamp 불필요)·stage93/94(프레이밍 보류) |

## 4. 결론

MemPalace는 '저장 무게이트 + 광범위 마이닝 + 값싼 하이브리드 검색' 철학의 **우리와 대척 구조**(write-time 게이트 없음, read-time LLM optional)이며, 우리가 이미 실측·기각한 레버(convex 퓨전·강도 decay·중복 삭제·시간 부스트)를 대부분 갖고 있다. **직접 반영할 사항 없음.** 참고 가치: ① 우리 `_cjk_like_search`의 CJK 스코어링 갭을 BM25(Lucene smoothed IDF)로 보완하는 방안(개발 참고) ② drawer 문맥 재구성(보류 D1) ③ temporal 부스트(발동률 낮음, 추천 기각).

- 소스 미러: `hermes-made/reviews/mempalace-review/` (tree JSON, fetch 소스)
- 다음 단계: 없음(직접 반영 0). D1은 소비 측 승인 영역에서 다시 열 수 있음.