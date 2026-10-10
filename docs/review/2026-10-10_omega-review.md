# OMEGA (omega-memory/omega-memory) 검토 — 2026-10-10

> 본 검토는 외부 시스템 단건 검토 절차(스킬 규약)에 따라 작성한다: 대상·주장 요약 → 우리 대비 축 표 → 0콜 실측(소스 대조 + 라이브 DB/trace 프로브) → 판정(기각·보류·채택·정합·참고·트래킹) → 재현 경로 → 결론.
> ⚠️ 본 프로젝트('jev-mem')와 학술 'Jev-Mem'(arXiv 2609.23986)은 이름만 유사한 별개 프로젝트다. 본 문서는 우리 로컬 Hermes 메모리 미들웨어(jev-gatemem)와 OMEGA를 비교한다.

## 0. 요약

| 항목 | 값 |
|---|---|
| 대상 | OMEGA — 로컬 퍼스트 에이전트 메모리 (Apache-2.0, Python 3.11+, ONNX 로컬 임베딩) |
| source | github.com/omega-memory/omega-memory (218★, 331 commits) |
| 검토 근거 | 벤치 페이지(omegamax.co/benchmarks)의 LongMemEval 95.4% + 소스 대조 |
| 검토 비용 | 0콜 (소스 fetch 26파일 + 라이브 DB/trace 프로브, JEV 호출 없음) |
| 판정 | ❌ **직접 반영 없음 — 정합 1건·참고 2건·기각 4건·보류 1건·트래킹 1건** |

**한 줄 결론**: 벤치 페이지가 광고하는 95.4%와 "RRF k=60 + semantic dedup" 구조는 실제 소스와 다르다(RRF는 dead code, 임베딩 dedup은 제거됨, 문항 타입별 가중치가 벤치 점수에 맞춰 하드코딩됨). 우리가 과거에 실측·기각한 레버(시간 decay·priority/access boost·LLM 쿼리 확장·타입 가중치)를 대부분 재사용하나, **near-tie bounded metadata**(±0.0025 이내로 제한된 메타데이터 기여)만은 우리 "기각"과 다른 설계로 남아 유일한 신규 레버 후보다.

## 1. 대상·주장 요약

### 1.1 벤치 페이지 (omegamax.co/benchmarks) 주장
- **LongMemEval 95.4% (466/500)**, 측정 2026-02, reader=GPT-4.1, bge-small 임베딩
- 카테고리: single-session 99%·preference 100%·multi-session 83%·knowledge-update 96%·temporal 94%
- "12 tools local / 95.4%" — Mastra 94.87%·Emergence 86%·Zep/Graphiti 71.2%와 비교
- 검색 파이프라인: **RRF (Reciprocal Rank Fusion, k=60)** + FTS5 + type-weighting(2x) + contextual boost + cross-encoder(top-20) + dedup + time-decay
- 저장: SHA256 + **임베딩 유사도 0.85 semantic dedup** + Jaccard per-type
- 수명주기: TTL(세션 요약 1일) + compaction + **decay(미접근 시 랭킹 가중치 감소, floor 0.35)**
- 성능: cold 31MB RSS, warm 337MB, retrieval <50ms, embedding 8ms(bge-small ONNX)

### 1.2 소스에서 확인된 실제 구조
- **임베딩 dedup 제거됨**: `_store.py` 주석 — "NOTE: embedding-similarity dedup used to run here. It was removed ... Do not reintroduce similarity-based dedup" (벤치 페이지 주장과 정면 불일치)
- **RRF는 dead code**: `_rrf_fuse(k=60)` 정의 존재하나 실사용은 `_fuse_semantic_channels`(raw score clamp 후 가중합) — 벤치 페이지의 "RRF fusion" 설명과 다름
- **문항 타입별 가중치 하드코딩**: `_RETRIEVAL_PROFILES`에 `"single-session-assistant": (1.0,1.0,1.0,1.0,1.0)  # 98.2% — at ceiling` 등 **LongMemEval 카테고리별 가중치가 벤치 정확도 주석과 함께 존재** → 벤치 오버피팅 정황
- **벤치 스크립트도 타입별 필터 파라미터로 조정**: `longmemeval_official.py`의 `_CATEGORY_CONFIG`가 문항 타입별 min_rel/min_res/max_res/max_tokens을 달리함
- decay floor는 벤치 페이지 0.35 vs 소스 `_DECAY_FLOOR_NEVER_ACCESSED = 0.15`(legacy 0.35는 "not access-selected in ranking")

## 2. 우리 대비 축 표

| 축 | OMEGA | 우리 (jev-mem) | 비교 |
|---|---|---|---|
| 임베딩 | bge-small-en-v1.5 ONNX 로컬 (384d) | bekko-a8m fastembed (S4 cutover) | 구조 동일(로컬 ONNX/fastembed) — 정합 아님(모델 다름), 채택 불필요 |
| 벡터+FTS 퓨전 | `_fuse_semantic_channels` (raw score 가중합) | FTS + vec + importance lane → RRF 병합 | 우리 RRF(lane 병합) vs OMEGA 가중합 — RRF는 OMEGA에서 dead code |
| RRF k | 정의만 `_RRF_K=60` (미사용) | k=60 `_rrf_fuse` 사용 | 정합: k=60 상수 일치 (Honcho·agentmemory와 함께 후보 풀 표준성 지지) |
| LLM rerank | cross-encoder ONNX (ms-marco, **벤치에서 ENABLE_RERANK=False**) | JEV listwise choice (60 후보) | 구조 차이 — JEV가 우리 고유 레버, OMEGA reranker는 소스에서도 벤치 시 끔 |
| 랭킹 메타데이터 | **near-tie 한정** bounded (+priority/access ±0.0025, decay ±0.05) | importance를 lane 가중치로, priority/access boost는 **우리 실측 기각** | ★**신규 후보**: "near-tie일 때만" 제한이 우리 "boost 금지"와 다른 설계 |
| 시간 decay | `_compute_decay_factor` — 타입별 λ, floor 0.15, 미접근 시 | 시간 축 레버 **실측 기각** (완곡어 1.3%, MemPalace 시간 부스트, OptMem 노출 밀도 보류) | 우리 기각 레버 — do not re-run |
| feedback | feedback_score (양/음 피드백 boost) | 없음 — 우리 "사용 빈도 boost" 기각 4단계와 동일 축 | 기각 (자기 강화 루프 위험) |
| 쿼리 확장 | LLM lex/vec/HyDE variant (OMEGA_QUERY_EXPANSION, 기본 ON) | **우리 stage18 기각** (오염 단어 주입) · AnchorMind 0/4 | 기각 (동일 한계) |
| 저장 dedup | canonical hash + exact hash, **임베딩 dedup 제거됨** | 왜곡 dedup은 없음, 우리 dedup 정책은 JEV 게이트 기반 | 정합: "임베딩 dedup 부정" = 우리 소스 주석과 독립 일치 |
| supersede | contradictions 모듈 (모순 감지 → 최신 승) | superseded_by 113행 + valid_until 159행 + read-time 필터 | 우리가 기능 우위 (Honcho·synix 정합과 동일 축) |
| forgetting | forgetting_log 감사 + decay + TTL(세션 요약 1일) | 없는 편 (보존 우선) | 우리 Harm-가중 판정: 삭제는 fail-open 원칙 충돌 — 기각 |
| 벤치 방법론 | **문항 타입별 가중치 하드코딩 + 타입별 필터 파라미터** | 벤치 조건 고정(운영 동등) + 홀드아웃 동결 | ★참고: OMEGA 벤치는 독립 재현·일반화 불가 정황 |

## 3. 0콜 실측

### 3.1 소스 대조 (fetch 26파일, `reviews_omega/survey-sources/`)
- `src/omega/sqlite_store/_store.py` L123-136: **임베딩 유사도 dedup 제거** 주석 + "Do not reintroduce"
- `src/omega/sqlite_store/_query.py`: `_rrf_fuse` 정의(k=60) vs `_fuse_semantic_channels`(raw score clamp·가중합) 실사용 — RRF 호출 0건
- `src/omega/sqlite_store/_base.py` `_RETRIEVAL_PROFILES`: LongMemEval 문항 타입 키 + 벤치 점수 주석 (`# 98.2% — at ceiling`, `# 94.3%`, `# 85.9%`, `# 74.1%`, `# ~70%`)
- `scripts/longmemeval_official.py`: `_CATEGORY_CONFIG` 문항 타입별 min_rel/min_res/max_res/max_tokens 상이 + `ENABLE_RERANK = False`(cross-encoder 벤치에서 끔)
- `scripts/longmemeval_bench.py`: 자체 합성 100개 메모리 + "Did the correct memory appear in top-3?" — **합성 셋, LLM 호출 없음, 공식 LongMemEval 아님** (95.4%와 무관한 로컬 스모크)

### 3.2 우리 라이브 DB/trace 프로브
- 우리 superseded_by: 113/2121 (5.3%), valid_until: 159/2121 (7.5%), **corrected_by: 0건, pinned: 0건**
- OMEGA의 supersede/decay/feedback을 우리 스키마에 대입하면: corrected_by(모순 수동 플래그)는 사용률 0 → 기능이 있으나 라이브 무사용
- 우리 recall_count 상위 40건 중 50%가 '다른 ai 답변 복사' 토론/작업 지시 (기존 tigerless 검토 실측) → OMEGA feedback/access boost의 자기 강화 루프 위험과 동일 결론

### 3.3 우리 LongMemEval 실측 (stage112/113, 500문항, haiku 판정)
| 카테고리 | 우리 (stage113) | OMEGA 주장 |
|---|---|---|
| single-session-user | 51.4% (36/70) | 99% (125/126) |
| single-session-assistant | 53.6% (30/56) | — |
| single-session-preference | 30.0% (9/30) | 100% (30/30) |
| multi-session | 9.0% (12/133) | 83% (111/133) |
| temporal-reasoning | 9.0% (12/133) | 94% (125/133) |
| knowledge-update | 25.6% (20/78) | 96% (75/78) |
| **전체** | **28.6% (119/416 판정, abstention 제외)** | **95.4% (466/500)** |

※ 우리 수치는 abstention 30건 제외 후 416건 기준이며 JEV+deepcombo reader 조합. 직접 비교는 부적절(모델·파이프라인 상이)하나, OMEGA의 "타입별 가중치 하드코딩" 없이 같은 벤치에서 우리가 28.6%임을 고려하면 OMEGA 95.4%는 벤치 튜닝 결과로 추정됨(추론).

## 4. 판정

| # | 레버 | 판정 | 근거 |
|---|---|---|---|
| 1 | RRF k=60 | ✅ **정합 (변경 없음)** | 우리 `_rrf_fuse` k=60과 상수 일치. Honcho·agentmemory k=60과 함께 후보 풀 표준성 지지 |
| 2 | 임베딩 유사도 dedup 금지 | ✅ **정합 (변경 없음)** | OMEGA가 소스 주석으로 "재도입 금지" — 우리도 시도 안 함(실측: dedup은 JEV 게이트·supersede로 처리) |
| 3 | near-tie bounded metadata (priority/access ±0.0025 한정) | ⏸️ **보류 — 신규 후보** | 우리는 priority/access boost를 "도배 행 자기 강화"로 실측 기각했으나, OMEGA는 **semantic near-tie(≤SEMANTIC_NEAR_TIE_DELTA)일 때만 ±0.0025 이내로 제한**해 "boost가 관련성을 만든다"는 우리 기각 근거(도배 행이 캡1 실측에서 abstain을 유도한 것, stage66)와 다른 설계. 채택 전제: production-exact 3-run 전체 재현 회귀(stage85 gold rank 41·36 유실 방지) + 도배 행 실측 재확인 |
| 4 | 시간 decay (타입별 λ, floor 0.15) | ❌ **기각 (do not re-run)** | 완곡어 실측 1.3%(MemPalace)·시간 부스트 검토에서 우리가 같은 축을 실측 기각. 코퍼스 시간 분포에 의존하고 drift 위험. 단 OMEGA는 "near-tie + bounded 0.05" 제한을 두어 우리 "완전 무시간" 대비 완화된 설계 — fail-open 원칙과 충돌 없음 |
| 5 | feedback_score boost | ❌ **기각 (do not re-run)** | tigerless "읽기 횟수 boost" 4단계 기각과 동일: recall_count 상위 40건 중 50% 도배 + 자기 강화 루프 + boost가 도배를 강화 |
| 6 | LLM 쿼리 확장 (lex/vec/HyDE) | ❌ **기각 (do not re-run)** | 우리 stage18(read-path 쿼리 확장) 기각 + AnchorMind 합성 역질문 0/4 — "표면 어휘 정규화일 뿐 의역/한영 단절 연결 못 함"과 동일 한계. HyDE도 LLM 호출이 read-path에 추가됨(우리 0콜 원칙 위반) |
| 7 | 타입 가중치 (decision/lesson 2x) | ❌ **기각** | 우리 stage59 meta 라벨 무력 실측(choice_idx 1건만 변경·abstain 0/38) + stage57~66 도배 실측. OMEGA의 가중치는 벤치 문항 타입에 맞춰 조정된 것(하드코딩) — 라이브 일반화 불가 |
| 8 | forgetting/decay 삭제 | ❌ **기각 (fail-open 원칙)** | 삭제는 fail-open 원칙 충돌. 우리는 supersede/valid_until로 처리(Honcho DELETE 기각과 동일) |
| 9 | LongMemEval 벤치 수치 95.4% | 🔭 **참고·트래킹 (벤치 신뢰성 경고)** | 소스의 타입별 가중치 하드코딩 + 타입별 필터 파라미터 + RRF/dedup 설명 불일치 → **독립 재현·일반화 불가** 수치. 우리 벤치 방법론(운영 동등·홀드아웃 동결·3-run)이 더 엄격함. 벤치 수치 인용 시 "OMEGA 자체 보고, 문항 타입별 튜닝 조건"으로 분리 표기하라 |

## 5. 논의

### 5.1 벤치 신뢰성 — 소스와 광고의 불일치 3건
1. **semantic dedup**: 벤치 페이지는 "0.85 유사도 dedup"이라 하나 소스 주석은 "제거됨 · 재도입 금지" — **소스가 최신**이며 벤치 페이지는 구버전 스펙 또는 광고용
2. **RRF k=60**: 소스 `_rrf_fuse`는 정의만 있고 실사용 0건 — "RRF fusion" 설명은 구현과 다름
3. **타입별 가중치 하드코딩**: `_RETRIEVAL_PROFILES`의 주석 `# 98.2% — at ceiling` 등은 **벤치 점수를 목표로 가중치를 튜닝한 직접 증거** — 일반화 불가

### 5.2 near-tie bounded metadata — 유일한 신규 레버 후보
- OMEGA 설계: semantic score가 best 대비 `SEMANTIC_NEAR_TIE_DELTA` 이내(near-tie)일 때만 priority/access/decay가 ±0.0025~0.05 가산. 관련성 밖의 메타데이터는 개입 불가.
- 우리 기각 근거와의 차이: 우리는 "boost가 관련성을 만든다"(stage66 노출 구성 변경이 abstain을 뒤집음)는 비선형 효과를 실측 — OMEGA는 "bounded near-tie"로 그 비선형 영역을 좁힘. priority/access가 2.5%p 이내 제한이면 도배 행 승격을 막을 수 있는지는 **실측 필요**.
- 채택 전제: ① production-exact 게이트에서 3-run 전체 재현 회귀 ② 도배 행(규칙 5행 top5 81~99%)에 대한 캡 대비 효과 확인 ③ 우리 "boost 금지" 원칙과 충돌 여부는 사용자 판단.

### 5.3 우리 대비 방법론 우위
- 우리: JEV(LLM) rerank 60 후보 + abstain soft gate + 운영 동등·홀드아웃 동결·3-run 회귀
- OMEGA: cross-encoder ONNX + 임계 필터, 벤치 타입별 튜닝 — **LLM 없이 0콜** 구조는 우리 원칙과 정합하나 rerank 품질은 JEV 대비 열위(벤치에서조차 reranker를 끔)

## 6. 재현 경로

- 소스 미러: `reviews_omega/survey-sources/` (26개 핵심 파일 + omega_tree.json, git 커밋됨)
- 벤치 페이지 캐시: `AppData/Local/hermes/cache/web/omegamax.co-*.md` + `github.com-6352dbf874.md`
- 우리 실측 raw:
  - LongMemEval: `experiments/operational-golden/data/stage112_lmev_results.jsonl` (500문항) · `stage113_lmev_judged.jsonl` (색인) · `stage115_lmev_oracle_results.jsonl` · `stage116_lmev_haiku_judged.jsonl`
  - DB 카운트: `superseded_by 113 · valid_until 159 · corrected_by 0 · pinned 0` (mnemosyne.db working_memory, 2026-10-10 조회)
  - tigerless recall_count 기각: `reviews_tigerless/` + HANDOFF 2026-10-10 행
- OMEGA 키 소스 참조:
  - `src/omega/sqlite_store/_store.py` (dedup 제거 주석)
  - `src/omega/sqlite_store/_query.py` (`_rrf_fuse` vs `_fuse_semantic_channels`, `_score_bounded_metadata`, `_compute_decay_factor`)
  - `src/omega/sqlite_store/_base.py` (`_TYPE_WEIGHTS`, `_DECAY_LAMBDAS`, `_DECAY_FLOOR_NEVER_ACCESSED=0.15`, `_RETRIEVAL_PROFILES`)
  - `src/omega/query_expansion.py` (lex/vec/HyDE)
  - `src/omega/feedback_signals.py` (피드백 카운트 캡 20)
  - `scripts/longmemeval_official.py` (`_CATEGORY_CONFIG`, `ENABLE_RERANK=False`)
  - `scripts/longmemeval_bench.py` (합성 셋, top-3 recall)

## 7. 결론

- **직접 반영 없음** — 우리가 실측·기각한 레버(시간 decay·feedback·쿼리 확장·타입 가중치)의 재사용이며, 벤치 페이지 광고(95.4%·RRF·semantic dedup)는 소스와 불일치해 신뢰 불가.
- **보류 1건**: near-tie bounded metadata — 우리 기각(priority/access boost)과 다른 설계 제약(±0.0025·near-tie 한정)으로 **유일한 신규 후보**. 채택 여부는 production-exact 3-run 재현과 사용자 판단 필요.
- **정합 2건**: RRF k=60, 임베딩 dedup 금지 — 우리 설계의 표준성 재확인.
- **트래킹 1건**: OMEGA의 벤치 수치는 "자체 보고 + 문항 타입별 튜닝"으로 분리 표기하고, 재현 가능한 공식 벤치가 나올 때까지 외부 인용 금지.