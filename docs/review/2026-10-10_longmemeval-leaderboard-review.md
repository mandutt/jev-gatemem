# AMB LongMemEval leaderboard 등재 솔루션 검토 (2026-10-10)

> 대상: https://agentmemorybenchmark.ai/dataset/longmemeval 에 등재된 메모리 솔루션
> 범위: 우리 jev-mem에 참고할 신규 사항 탐색 (기존 검토 완료 항목 제외)
> 방법: 0콜 (web_extract + arXiv 원문 + 기존 실측 raw 대조, JEV 호출 없음)
> 판정: 참고 2 · 설계 정합 확인 2 · 기각 3 · 보류 0 — **직접 반영 없음**

## 1. 후보 목록 및 기존 검토 이력 대조

| 등재 솔루션 | Accuracy | 출처 | 우리 이력 |
|---|---|---|---|
| Chronos | 95.6% | arXiv:2603.16862 | **신규** |
| Mastra | 92.8% | Chronos 페이퍼 경유 리포트 | **신규** (백본 미지정·수치만) |
| Honcho | 90.4% | Plastic Labs | 이미 검토 (2026-10-09, 보류 3·정합 3) |
| SmartSearch | 88.4% | arXiv:2603.15599 | **신규** |
| Memora | 87.4% | arXiv:2602.03315 | **신규** |
| Supermemory (Gemini-3) | 85.2% | Hindsight 페이퍼 | 직접 사용 중 (Hindsight 검토 2026-10-10) |
| EMem-G | 84.9% | arXiv:2511.17208 | **신규** |
| EverMemOS | 83.0% | SmartSearch 페이퍼 | 이미 검토 (synix 8종, 2026-10-10) |
| Supermemory | 81.6% | Hindsight 페이퍼 | 직접 사용 중 |
| TiMem | (표 잘림) | arXiv:2601.02845 | **신규** |
| hindsight·local 94.6% / hybrid-search 74.0% | — | AMB 재현 | 이미 검토 (synix, Hindsight 계열) |

**경고**: AMB "Unverified" 표의 점수는 자체 보고+백본 모델이 제각각(Chronos 95.6%는 Claude Opus 4.6 — 다른 후보들의 GPT-4o/4.1-mini 대비 월등히 강한 백본)이라 **비교 불가** — benchd.ai/maximem.ai 검증 회의론과 동일하게 분리 표기.

## 2. 주목할 만한 신규 메커니즘 (원문 기준)

### 2.1 SmartSearch — "compilation bottleneck" (검색이 아니라 랭킹이 병목)
- 전 검색 파이프라인이 **LLM 없음**: NER/POS 가중 substring 매칭 → 규칙 기반 엔티티 확장(multi-hop) → CrossEncoder(mxbai-rerank-large-v1)+ColBERT RRF 퓨전 (CPU ~650ms, 학습 컴포넌트는 reranker뿐)
- Oracle 분석: retrieval recall 98.6%인데 **토큰 예산 내 gold 생존 22.5%** — truncation 전 랭킹 품질이 실제 병목 ("compilation bottleneck")
- score-adaptive truncation + no tuning으로 LoCoMo 93.5%·LongMemEval-S 88.4%

### 2.2 Chronos — 이벤트 캘린더 + dynamic prompting (SOTA)
- 대화를 SVO 이벤트 튜플 + **해석된 datetime 범위 + 엔티티 별칭**으로 분해 → 이벤트 캘린더 + 턴 캘린더 이중 인덱스
- 쿼리마다 dynamic prompting: 무엇을/시간 범위/멀티홉 전략을 생성해 iterative tool-calling
- Ablation: **이벤트 캘린더 단독 58.9% 게인** (다른 컴포넌트 15.5~22.3%)
- 주의: 95.6%는 Opus 4.6 백본, Chronos Low(GPT-4o)는 92.6%

### 2.3 TiMem — Temporal Memory Tree (L1~L5 계층 + recall planner/gating)
- TMT: 원문(L1) → 세션말 → 일 → 주 → 월간 프로필 경계에서 instruction-guided consolidation (파인튜닝 없음)
- 복잡도 인지 recall: **planner 1콜 + gating 1콜**, recall 토큰 52% 감소 (LoCoMo 511 tokens/쿼리)
- LongMemEval-S 76.88% (gpt-4o-mini 백본)

### 2.4 EMem / Memora — event-centric 저장
- EMem: neo-Davidsonian 이벤트 의미론 — 대화를 **참여자+시간 단서+로컬 컨텍스트** 묶음 EDU로 분해, **비압축 보존** + 이종 그래프 + 그래프 전파 검색 (LongMemEval-S 84.9%, GPT-4.1-mini)
- Memora: 추상 인덱스 + 구체 값 + **cue anchors** (연결을 통한 확장 검색) — RAG·KG가 특수 케이스로 귀결 (87.4%)

## 3. 우리 실측 대조 (0콜)

| 레버 | SmartSearch/Chronos/TiMem/EMem 제안 | 우리 실측 | 판정 |
|---|---|---|---|
| **reranker 추가** (CrossEncoder+ColBERT RRF) | 검색 병목이 랭킹 | ① **JEV choice는 후보 60개 전체 입력 — 순서 변경에 winner 무영향 (Run R 180콜 실측 확정)** — reranker가 순서만 바꾸면 JEV가 같은 winner를 고름 ② 환경: torch/sentence_transformers 없음 (fastembed·onnxruntime만) — mxbai-rerank-large 435M 설치 불가 ③ RRF 점수 Δ 분포에서 near-tie flip은 노출만 요동 (stage119) ④ pool_recall 90% 상한 수용 — miss는 의역/한영 단절로 랭킹 문제가 아님 | ❌ **기각** |
| **시간/이벤트 캘린더** (Chronos) | temporal reasoning 별도 캘린더 + datetime 파싱 | 라이브 trace 시간 참조 유병률 **1.1~1.3%** (MemPalace·synix 실측) — 같은 '완곡어 문법 용법' 함정. LongMemEval 자체가 temporal을 별도 카테고리로 채점하므로 벤치 성능에는 유효하나, **우리 라이브 트래픽엔 발동 기회 부재** | ❌ **기각** (기존 temporal 부스트 기각과 동일 논리) |
| **계층 통합 경계** (TiMem L1~L5) | 세션/일/주/월 통합 | consolidated_at 595행이 **메타데이터 필드뿐** (consolidation_claimed_at 0건), 코퍼스 2,085행 — 백그라운드 합성 보류(OptMem·Honcho·synix)와 동일 논리. **단 TiMem이 구체 통합 경계(세션말/일/주/월)를 제시** — 보류 항목 재검토 시 파라미터 참고 | 🔭 **참고 등록** |
| **이벤트/EDU 단위 저장** (EMem·Memora) | 비압축 보존 + 그래프 전파 | 우리도 **비압축 턴 저장 + supersede/valid_until**로 동일 철학 (EMem '비압축 보존'과 정합). 그래프 전파는 우리 graph lane(3경로)과 기능 겹침 — 단 우리 graph lane은 실데이터 gold 추가 회수 0건 (2026-09-27, facts 5개뿐) | ✅ **정합 확인** |
| **레버리지 없는 검색** (SmartSearch index-free) | grep 단독 회수 | 우리 lane 폴백(stage50c)과 부분 정합 — 단 recall 98.9%는 LongMemEval 규모(표면 어휘 일치) 한정, 우리 의역 miss와 무관 | ✅ **정합 확인** |

## 4. 판정 요약

- **참고 2**: ① TiMem 계층 통합 경계(세션말/일/주/월) — 백그라운드 합성 보류 항목의 재검토 트리거 파라미터 ② SmartSearch reranker convex/RRF 퓨전·서브스트링 recall — 벤치 수치 참고만
- **정합 2**: ① 비압축 보존 (EMem) ② LLM-free 검색 원칙 (SmartSearch index-free — 우리 0콜 원칙과 동일 방향)
- **기각 3**: ① reranker 도입 — **JEV 순서 무영향 (Run R)** + 실행 환경 부재 ② 시간/이벤트 캘린더 — 라이브 발동률 1.1~1.3% ③ (chronos dynamic prompting) — read-path LLM 콜 = 우리 0콜 원칙 위반
- **보류 0** — 새 보류 등록 없음

## 5. 결론

**실제 반영 후보 없음.** 검색 병목이 랭킹이라는 SmartSearch의 통찰은 JEV choice가 60개 전체를 입력으로 받는 우리 구조에선 **이미 rerank가 내장되어 있어 해당 병목이 존재하지 않음** (Run R 실측: 순서 변경 무영향). 나머지(temporal/계층 합성/그래프)는 전부 기존 보류·기각 레버의 재확인 수준.

## 6. 재현 경로

- AMB 페이지: https://agentmemorybenchmark.ai/dataset/longmemeval (web_extract 캐시)
- arXiv 원문: 2603.15599(SmartSearch) · 2603.16862(Chronos) · 2602.03315(Memora) · 2511.17208(EMem) · 2601.02845(TiMem) — spillover 캐시 `AppData/Local/hermes/cache/spillover/call_22c39078d53c4587a72cb548.txt`
- TiMem: arXiv 2601.02845 (web_search 결과)
- 0콜 실측 요약 러너: `experiments/operational-golden/stage120_amb_leaderboard_env_probe.py` (reranker 환경·RRF 밀림 대조·백본 분리)
- 우리 실측 근거: Run R 180콜 (references/external-fork-ab-comparison.md), stage50c lane 분해 raw `data/stage50c_lane_decomp.json`·stage50d `data/stage50d_lane_ranks.json`, stage119 near-tie, 시간 유병률 (MemPalace·synix 검토), 데몬 venv 패키지 조사