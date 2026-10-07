# 외부 저장소 검토: AnchorMind (구 Memento-mcp) (2026-10-08)

> 검토 대상: https://github.com/JinHo-von-Choi/anchormind
> 파편(fragment) 기반 메모리 MCP 서버 — AI 에이전트 장기 기억. PostgreSQL+pgvector, Node.js.

## 개요

- **도메인**: 우리(jev-mem)와 동일 — 에이전트 장기 기억. 단 구조는 MCP 서버(PostgreSQL) vs
  우리(Hermes 플러그인, SQLite Mnemosyne 데몬)
- **핵심 메커니즘**: 파편 단위 저장(7유형: fact/decision/error/preference/procedure/relation/episode),
  context(세션 시작 복원)·recall(검색)·remember(저장)·reflect(세션 요약)
- **정제**: 중복 병합·모순 탐지(NLI mDeBERTa)·중요도 감쇠·TTL 만료 — **Jev 같은 판정 모델 없음**
- **벤치마크 (자체 보고)**: LongMemEval-S 검색 recall_any@5 88.3%, QA 44.9% —
  검색은 우리 pool_recall 90%와 동급, QA 갭은 소비 LLM 합성 한계(우리 stage93/94와 동일 패턴)
- **라이선스**: Apache 2.0

## 우리 프로젝트에 반영할 만한 것

### ① 한국어 형태소 보조 벡터 (MorphemeTokenizer) — 실측 기각 (stage103)
- garu-ko 형태소 분석 + KO_STOPWORDS(조사/어미) 필터 + 고유명사(NNP/SL/SH) 추출을
  L3 시맨틱 검색 보조 채널로 사용
- **우리 실측 (stage103, 0콜)**: 현재 pool miss 4/90에서 형태소 보조 gold 구제 **0/4** —
  miss 원인이 한영 미스매치(2건)·쿼리 과단축(1건)·의역(1건)이고, 형태소는 표면 어휘
  정규화일 뿐 이들을 연결하지 못함. **do not re-run**
- 조건부 재검토: 영문 메모리가 크게 늘면 그때는 합성 역질의가 맞는 레버 (단 stage18 기각과 균형)

### ② 합성 역질의(Doc2Query) 증강 — stage18 기각 확인
- AnchorMind: Recall@1 70→76.7%, Recall@5 80→86.7% (isolated, 75건 역질의)
- 개선 3건 전부 '영문 저장문 × 한국어 질의' — 본문 벡터로는 한영 미스매치로 후보 진입 실패
- **우리는 stage18에서 doc2query 기각** (오염 단어 주입) — do not re-run, 단 '한영 미스매치 전용' 조건이면 재검토 여지 있음

### ③ 임베딩 유사도 임계값 실측 — 교차 검증
- text-embedding-3-small: 한국어 질의×영문용어 저장문 코사인 0.2621, 무관 5000건 p50 0.228/p95 0.335
- 기본 임계값 0.40이 실제 분포보다 높아 정답 탈락 → 질의 의도별 임계값 보정(개념·원인·절차 0.20 하향, 식별자 유지)
- = 우리 stage100 'JEV score-floor 절대 임계값 금지'의 임베딩 버전 — **모델별/분포별 임계값 검증 필요성 교차 확인**

### ④ 랭킹 가중치 정규화 — 교차 검증
- `importance 0.4 + recency 0.3 + similarity 0.3` 선형 가중이 모델 값 대역 차이로 깨짐
  (text-embedding-3-small 0.078 vs bge-m3 0.060 기여 폭) → **점수 정규화 후 가중** 필요
- = 우리 fusion min-max 정규화 + α 스윕과 동일 교훈

### ⑤ 검색 계층 — 참고만
- L1(Redis 키워드)/L2(GIN) 0%, L3(pgvector) 99% — 그들의 키워드 계층은 약함 (저장 방식 탓)
- 우리는 FTS+vec 하이브리드(RRF)라 구조 다름
- HNSW 강제 최적화(308ms→7ms, `SET LOCAL enable_seqscan=off`) — sqlite-vec에도 유사 개념 있으나
  우리 스케일(1,700행)에선 불필요

## 범위 밖 (채택 불가)

- PostgreSQL+pgvector 인프라 (우리는 sqlite-vec) — Docker 포함
- MCP 서버 구조 (우리는 Hermes 플러그인)
- Redis 캐시 (우리 규모에 불필요)
- NLI 모순 탐지(mDeBERTa, ~250MB) — write-path 게이트(JEV)가 이미 저장 판정 수행

## 채택 판정 요약

| 항목 | 판정 | 근거 |
|---|---|---|
| 형태소 보조 벡터 | ❌ 기각 (do not re-run) | stage103: miss 4건 중 0건 구제 |
| 합성 역질의 | ❌ stage18 기각 유지 | 영문 코퍼스 증가 시에만 재검토 |
| 임계값 보정 | ✅ 교차 검증 | stage100과 동일 교훈 |
| 랭킹 가중치 정규화 | ✅ 교차 검증 | 우리 fusion과 동일 |

## 산출물

- `experiments/operational-golden/STAGE103_MORPH_20261008.md` — 형태소 실측
- `experiments/operational-golden/stage103_morph_fix.py` + `data/stage103_morph_raw.json`
- 스킬 `references/external-fork-ab-comparison.md` — AnchorMind 절 추가