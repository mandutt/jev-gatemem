# sift (pablooliva/sift) 검토 — 2026-10-10

**대상**: https://github.com/pablooliva/sift — "personal knowledge management system combining semantic search, hybrid retrieval, and RAG chat over your documents using txtai, Qdrant, Graphiti, and AI models" (ProPal Ethical License v1.0)

**방법**: GitHub tree API(`git/trees/main?recursive=1`, 505 files)로 파일 목록 확보 → `raw.githubusercontent.com`로 핵심 소스 fetch(`mcp_server/txtai_rag_mcp.py` 113KB · `config.yml` · `scripts/graphiti-ingest.py` 49KB · `mcp_server/graphiti_integration/graphiti_client_async.py` 59KB · `docs/QUERY-ROUTING.md` · `8-agent-memory-systems-vs-sift.md` · `custom_actions/ollama_*.py`) → 우리 jev-mem SoT(gateway/j1_pipeline.py · core/j1_engine.py)와 라인 단위 대조. **0콜(실험 콜 0건)**, DB 프로브 1건.

---

## 1. 대상 요약

sift는 문서 말뭉치 기반 **검색 + RAG + 지식그래프** 스택이다:
- **하이브리드 검색**: txtai `similar()` — dense(semantic) + BM25(sparse)를 단일 가중치 `WEIGHTS=0.5`(50/50)로 융합, Qdrant 벡터 스토어 + PostgreSQL 콘텐츠 저장. score 정규화(normalize:true) 후 `score >= 0.5`(RAG_SIMILARITY_THRESHOLD) 필터, `LIMIT 5`(context_limit).
- **RAG**: Top-5 → Together AI Qwen2.5-72B(T=0.3) 생성, "Use ONLY provided context" 프롬프트 + "I don't have enough information" 지시 + 스코어 임계 필터(0.5)로 무답 처리. 검색 시간 초과 시 남은 시간으로 LLM 호출(최소 5s).
- **지식 그래프**: Graphiti + Neo4j — 엔티티/관계 추출(scripts/graphiti-ingest.py), bi-temporal 메타데이터(created_at/valid_at/invalid_at/expired_at)를 " (added: YYYY-MM-DD[, valid: ...])" 문자열로 컨텍스트에 주입(SPEC-041 REQ-013/014). `include_graph_context=True` 시 검색 결과에 그래프 컨텍스트 병합.
- **쿼리 라우팅(/ask)**: 단순 사실 질문 → RAG(~7s), 복잡/분석 질문 → Claude Code 수동 분석(30-60s) + 자동 폴백(타임아웃/API 오류/저품질).
- 인프라: Docker(docker-compose), Ollama nomic-embed-text(768d), ProPal Ethical License(사용 제한 라이선스).

우리 jev-mem과 비교 대상이 되는 것은 **"검색 → 융합 → LLM 컨텍스트 구성" 리드 패스**와 **시간 메타데이터 처리** 두 축이다. (저장 게이트/무답 판정은 sift에 해당 구조가 없음.)

---

## 2. 우리 대비 축 표

| # | 축 | sift | jev-mem (현행, 10-10 실코드 대조) | 판정 |
|---|---|---|---|---|
| 1 | 하이브리드 검색 융합 | txtai `similar(q, 0.5)` — **단일 스칼라 가중치 w로 dense/BM25 선형 융합** (txtai 내부 구현) | **RRF k=30** — FTS 60 + vec 60 + imp 8 + graph 10 lane을 rank 기반 융합 (`_rrf_merge`, j1_pipeline.py:242) | sift 단순형. 우리가 실측으로 확정한 구조 (stage14/15 POOL 60, RRF k=30). **참고 — 단일 가중치 융합은 우리 stage 후보(pool20 등)와 같은 '순위 단일 축' 한계** |
| 2 | 무답 처리 | 유사도 **score 임계 필터(≥0.5)** + 프롬프트 "don't have enough information" — top-5에서 점수 밑으로 잘리면 빈 답 | **abstain 라벨 + soft gate τ=0.3** — JEV choice가 abstain을 고르거나 abstain_p>τ면 빈 컨텍스트 | sift 방식은 우리 stage50 Noul pointwise·stage83 60 vs 5 실측과 같은 레버(점수 절대 임계) — **라이브 무답(이웃 존재형)에서 이미 기각된 레버**. abstain_p는 정답/무답 분리 불가 실측(stage49b/50). **기각(do not re-run 계열)** |
| 3 | 검색 상한 | top-5 컨텍스트 · LIMIT 20 | pool 60 → JEV choice 1콜 → 노출 rows[:5] | sift는 후보 단계 LLM 판정 없음 — JEV lift가 없어 rank 6+ 정답은 원천 유실(우리 stage85 rank 41·36 gold 실측의 반례). 우리가 우위 |
| 4 | 시간 메타데이터 | Graphiti bi-temporal: `(added: YYYY-MM-DD, valid: …)` 문자열 주입 — **읽기 시점 컨텍스트 주석**, 저장 필터 없음·만료 행 제거 없음 | **SQL 수준 시간 필터**: `valid_until IS NULL OR valid_until > now` (imp/graph lane, j1_pipeline.py:267/345, hydration), supersede 113행 + valid_until 159행 + read-time 필터 (0콜 DB: total 2,085 · valid_until 비어있지 않음 159) | **sift는 주석만, 우리는 읽기 차단까지 — 기능적 우위 실측** (Valid_until/supersede 커버 갭 없음: Honcho outdated DELETE 기각과 동일 논리) |
| 5 | 소비 측 환각 방어 | 프롬프트 "Use ONLY context" + T=0.3 + score 게이트 — **생성 전 검문, 응답 후 검증 없음** | 프레이밍 실험(헤더 '참고용') — 환각 23.7→13.2% 실측(stage93/94), 사용자 승인 대기 | 동일 방향이지만 우리가 실측 완료한 레버. sift는 "조건 없는 강한 지시"만 — **grounding 검문소(3지선다 supported/contradicted/not_mentioned)는 HANDOFF 外部 7편 참고로 이미 등록** |
| 6 | 쿼리 라우팅 | `/ask`: 규칙 기반 단순/복합 분기 + 자동 폴백 | — (우리 데몬은 J1 무답 판정만, 라우팅 없음) | 우리 아키텍처(에이전트 메모리 게이트)와 대상이 다름 — **도입 대상 아님** |
| 7 | 그래프 lane | Graphiti의 Neo4j 그래프를 **컨텍스트 주입** | `_graph_lane_search` (facts/consolidated_facts/graph_edges/memoria_facts → memory id 회수, budget 10) | sift는 "검색 결과에 그래프 병합" — 우리는 "그래프를 lane으로 pool에 포함". **구성 방향 정합 — 다만 sift 병합은 우리 graph lane 실측에 없는 신규 메커니즘 없음** |
| 8 | 임베딩 | nomic-embed-text 768d (Ollama 로컬) | bench/bekko-a8m (S4 확정, 100% cutover) | 우리가 S4에서 벤치로 확정 — 참고만 |
| 9 | 벤치/수치 | 자체 보고: RAG 정확도 90%+ · ~$0.0006/쿼리 — **평가 셋·모델 고정 조건 미명시** | op-90/noans-50/live60 + production-exact 3-run 회귀 | sift 수치는 실측과 분리 표기 (회귀 기준 없음) |

---

## 3. 판정

### 채택 (직접 반영): 없음

### 설계 정합 확인 (변경 없음): 2건

1. **하이브리드 검색의 dense+BM25 결합 방향** — sift(txtai 스칼라 가중치 0.5)와 우리(RRF k=30, lane 다중화)는 구현이 다르지만 "단일 랭커로는 놓치는 표면 어휘/의미 격차를 두 신호 결합으로 보완"이라는 원칙은 동일. 우리가 stage14/15·stage50c에서 lane 병합 우위를 실측으로 확정한 방향과 정합 (RRF k=60 동일 계열 — agentmemory k=60·Honcho k=60과 함께 후보 풀 구성 표준성 지지).
2. **시간 메타데이터의 읽기 시점 활용** — sift는 `(added: …)` 주석, 우리는 SQL 필터(`valid_until > now`) — 외부 독립 구현에서 시간 필터링이 필요하다는 점이 일치. 우리가 valid_until 159행·supersede 113행(0콜 프로브)으로 이미 차단 — **Honcho outdated DELETE 기각과 동일 근거 (fail-open 원칙 유지, 기능 우위)**.

### 보류 (신규 축 미실측): 0건

### 기각 (우리 실측과 충돌, do not re-run): 2건

1. **무답 처리 = 유사도 절대 임계 + "모르면 거부" 프롬프트** — sift `score >= 0.5` 필터는 우리 **stage50 Noul pointwise**(라이브 IRREL 0.91 vs 골든 0.26 분리 간격 미달)·**stage50b 프롬프트 변형**(간격 +0.03~0.07)·**stage83 60 vs 5 control**(후보 수 축소 abstain 유발)과 동일 레버 — 라이브 무답(주제 이웃 존재형) 차단은 JEV 단일 판정으로 불가 확정. 재실험 금지.
2. **Top-5 컨텍스트(검색 상한 5~20)** — JEV lift(choice 1콜) 없이 순위만으로 컨텍스트를 자르는 구조는 **production-exact rank>20 gold 존재(stage85 rank 41·36) 실측과 충돌** — pool20 채택 금지 확정(pool60 유지)의 직접적 반례. 채택 판정 시 "top-N 컷" 제안은 do not re-run.

### 참고만: 2건

1. **grounding 검문소(supported/contradicted/not_mentioned 3지선다)** — sift에는 응답 후 검증이 없고 프롬프트 지시만 있으나, 우리는 HANDOFF 외부 문헌 7편에서 '환각 검문소·계산 분리'를 📋 참고로 이미 등록(소비 측 개입 — 사용자 승인 영역).
2. **쿼리 라우팅/폴백(/ask)** — 에이전트 메모리 데몬과 대상이 달라 이식 대상 아님. 단, canary drift 알림(L1/L2)과 같은 "실패 시 다른 경로" 관념은 우리 shadow/실패 폴백과 개념 정합.

---

## 4. 재현 경로

- 소스 대조: GitHub tree API — `https://api.github.com/repos/pablooliva/sift/git/trees/main?recursive=1` (505 files, truncated: False) → raw fetch: `https://raw.githubusercontent.com/pablooliva/sift/main/mcp_server/txtai_rag_mcp.py` 등 (본문 § 대상 요약에 기재한 9개 파일)
- 우리 실코드: `gateway/j1_pipeline.py` (RRF k=30 · lane budget 60/60/8/10 · POOL_BUDGET 60 · `_filter_and_rank` 기본값 (1, 0.0) · abstain τ=0.3 · valid_until 필터 267·345행)
- DB 프로브(0콜): `working_memory` total 2,085 · valid_until 비어있지 않음 159 — `C:/Users/mandu/AppData/Local/hermes/cache/scratch/sift_review/probe_valid.py` (결과는 본문 §2 #4)
- fetch 캐시: `$LOCALAPPDATA/hermes/cache/scratch/sift_review/` (tree.json · mcp_server_txtai_rag_mcp.py · config.yml · docs_QUERY-ROUTING.md · 8-agent-memory-systems-vs-sift.md · scripts_graphiti-ingest.py · graphiti_client_async.py · custom_actions_ollama_*.py · probe_valid.py)

---

## 5. 결론

**직접 반영 없음.** sift는 문서 RAG + 지식그래프 인프라(검색 ↔ 문서)이지 에이전트 메모리 게이트(저장 ↔ 리콜)가 아니며, 우리가 실측으로 소진/기각한 레버(점수 절대 임계, top-5 컷)를 쓰고 있다. 반면 시간 메타데이터(valid_until 159행)와 하이브리드 융합(RRF k=30)은 우리가 이미 기능 우위 + 정합을 0콜로 확인했다. 신규 채택·보류 항목 없음 — 따라서 후속 실험 필요 없음.