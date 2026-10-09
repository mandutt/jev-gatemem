# Honcho(plastic-labs/honcho) 검토 — 직접 반영 사항 없음 (0콜 실측)

- 날짜: 2026-10-09
- 대상: https://github.com/plastic-labs/honcho (Server 3.2.2 기준, main 브랜치 소스 직접 확인)
- 판정: **직접 반영 없음** — 설계 정합 3건 확인 + 보류 등록 3건 (모두 0콜 실측 전 채택 금지)
- 재현 경로: 본 문서의 모든 수치는 GitHub raw 소스(src/dreamer, src/deriver, src/dialectic, src/utils/search.py)와 라이브 DB 프로브로 확인. 소스: `https://raw.githubusercontent.com/plastic-labs/honcho/main/<path>`

> 본 검토의 'jev-mem'은 Hermes Mnemosyne 위에 구축한 우리 프로젝트(SoT `C:/Users/mandu/hermes-made/jev-memory-middleware`)이며, 학술 'Jev-Mem'(arXiv 2609.23986) 또는 npm 'jevmem'(Avinash-jetwani)과는 이름만 유사한 별개 프로젝트다.

## 1. 대상 요약

Honcho는 Plastic Labs의 '에이전트 메모리 인프라' 서버(FastAPI + Postgres/pgvector, AGPL-3.0, ~7.5k stars, 768 commits). managed(api.honcho.dev)·로컬 CLI·셀프호스트 3가지 배포.

구조: Storage(동기, workspaces→peers→sessions→messages) + Insights(비동기 deriver worker가 queue 소비). 메시지 저장 → 배경 추론(deriver가 explicit atomic facts 추출) → 'dream' 주기(surprisal 샘플링 → deduction specialist가 논리적 함의·지식 업데이트·모순 처리·outdated 삭제 → induction specialist가 패턴 일반화) → 검색(RRF hybrid) / conclusion API / peer card / chat endpoint(dialectic agent)로 조회.

- 벤치(자체 보고, honcho.dev/evals, 2025-12 갱신): LongMem S 90.4%(Haiku 4.5 단독 62.6%), LoCoMo 89.9%(재판정은 LLM-as-judge), BEAM 100K 0.630. deriver=gemini-2.5-flash-lite, dreamer/dialectic=claude-haiku-4.5 고정.
- 반례 주의: LongMem '더 이상 메모리 시스템 벤치로 부적합'(전체 컨텍스트 주입 모델이 경쟁 가능)을 Honcho 자체가 명시. 수치는 자체 보고 + 특정 모델/스플릿 조건이므로 우리 실측과 분리 표기.

## 2. 우리 대비 축 표

| 축 | Honcho | 우리 jev-mem | 판정 |
|---|---|---|---|
| 저장 | Postgres/pgvector, message 원본 + observation(추출 결론) 2계층 | SQLite Mnemosyne, write-time 게이트(G-qual/G-AS)로 저장 여부·13종 유형 결정 | 축 자체가 다름 (우리는 저장 전, Honcho는 저장 후 추출) |
| 추출 | deriver(LLM)가 명시적 사실 추출 — write-time 무게이트·raw 보존 후 비동기 파생 | JEV choice가 저장/유형 판정 (write gate) + read-time rerank 1콜 | Honcho는 '들어오는 문'이 열려 있고 파생이 비동기. 우리는 들어오는 문을 게이트 |
| 검색 | **RRF(k=60)** hybrid(벡터+BM25류) — `reciprocal_rank_fusion(k=60)` | RRF(k=60) + FTS/vec/imp/그래프 lane + JEV rerank(60 후보) → 노출 최대 5 | **우리와 동일한 RRF k=60** — 검색 융합 상수 정합 확인 |
| 지식 업데이트 | deduction specialist가 같은 사실 다른 값 발견 시 새 observation 생성 + **기존 행 DELETE** | write-time supersede(코퍼스 113행) + valid_until(159행) + read-time 필터(`superseded_by IS NULL AND valid_until > now`) — 삭제 없음 | Honcho의 'outdated DELETE'는 우리 fail-open 원칙(데이터 유실 금지)과 정면 충돌 → 기각 |
| 모순 처리 | contradiction observation 생성(플래그) | corrected_by 컬럼 존재, **사용 0건** (0콜 프로브) | 자동 모순 감지 = 미탐 영역 → 보류 등록 (유병률 미실측) |
| 정체성 | peer card: IDENTITY/ATTRIBUTE/RELATIONSHIP/INSTRUCTION 4종, **명시적 선언만·행동 추론 금지·6개월 안정성·max 40 entries** | '사용자 프로필 규칙' 행이 JEV rerank 도배 주범(stage57/58: 84% 몰림, stage64~66: abstain 유도)으로 실측된 상태 | 분류 규칙은 이미 stage59 meta 라벨로 무력 실측된 영역 → 참고만, 재실험 금지 경계 |
| 놀라움 기반 재처리 | surprisal(기하학적 점수, tree 기반)로 이상치 표본 추려 deduction 표적화 | 없음 | 신규 축이나 OptMem '세대 압축'과 같은 보류 논리 — 코퍼스 2,085행은 시기상조 |
| 소비 측 | dialectic chat = **agentic tool-use** (필요한 만큼만 추가 수집, reasoning level로 비용 조절) | Hermes prefetch 정적 top-k 노출 + 프레이밍(참고용 헤더, stage93/94) | 능동 소비 아키텍처 변경은 Hermes 플러그인 구조 변경 → 보류(승인 영역) |
| 평가 | 공개 벤치(LongMem S/LoCoMo/BEAM, LLM-as-judge) | 자체 라벨 op-90/noans-50/live60 + canary L1/L2(2계층 drift 감시) | canary L1(사용자 독립)이 공개 벤치의 취지를 이미 부분 커버 |
| 비용 구조 | 파생/추론이 비동기 배치(LLM 다중 콜) — 대화당 토큰 불확정 | JEV 턴당 1콜(G-qual) + read rerank 1콜, 토큰 예산 실측 관리 | Honcho는 '추론 비용을 항상 지불' — 우리는 게이트로 선별 |

## 3. 0콜 실측 (라이브 DB 프로브, 10-09)

- 코퍼스: working_memory 2,085행 (context 1458 / fact 284 / error 138 / instruction 63 / preference 51 / goal 16).
- **지식 업데이트 처리 사용률**: superseded 113 (5.4%), valid_until 159 (7.6%, 미래 만료 0건), corrected_by 0건. → '지식 업데이트/모순'은 실제 문제로 존재하나 우리 메커니즘(supersede+valid_until)이 이미 write-time에서 처리. Honcho식 자동 모순 감지가 추가로 구제할 유병률은 미측정.
- **규칙/선호/목표 행 유병률**: instruction 63행 중 rule-like(규칙/원칙/금지/항상/우선 등) 22행, preference 51행 중 1행, goal 16행 중 9행. 단 최신 200행 사람 육안 스캔에서 rule-like 행 다수가 '[IMPORTANT: Background process]'·'완료.'·'stageNN' 작업 지시/이벤트 반복(statem-bench 프롬프트·세션 재개) — mem0 검토(2026-10-09)에서 이미 '정확 중복 15그룹·명사 50%+ 겹침 99그룹 전부 작업 지시/이벤트 반복'으로 실측된 것과 동일 패턴.
- 코드 대조(0콜): Honcho RRF k=60 = 우리 RRF k=60 (`reciprocal_rank_fusion(*ranked_lists, k=60)` 코드 직접 확인 — 우리와 무관한 독립 구현인데 상수 일치). deriver 프롬프트의 '대상 피어의 메시지만 사실로, 타인 발언은 맥락으로만' 규칙은 우리 G-qual의 사용자 발언 게이트와 정합.

## 4. 판정

### 기각 (원칙 충돌 / 이미 보유)
- **outdated observation DELETE (deduction specialist)**: 우리 fail-open 원칙(어떤 경우에도 데이터 유실 금지)과 정면 충돌. 우리는 supersede+valid_until로 '구버전 보존+비노출'을 이미 실현 — 기능적 목표(최신 버전만 노출)는 동일.
- **peer card 분류 규칙의 write-gate 이식**: '명시적 선언만·행동 추론 금지·6개월 안정성'은 타당하나, read-path 메타 라벨/규칙 행 조작은 stage59(meta 라벨 무력)·stage57/58(규칙 행 다운웨이트 무효·유해)·stage64~66(빈도 캡은 abstain 전제 파괴)로 이미 실측 종결된 레버. 라벨 설계 재실험은 do not re-run 경계.
- **비동기 deriver/specialist 구조**: 데몬 구조 전환 + 코퍼스 2,085행 규모에서 LLM 추출 파이프라인 전체는 OptMem '세대 압축' 보류(2026-10-09)와 동일 논리 — 수만 행·수백 세션 규모에서 재검토. 우리는 write gate로 '들어오는 문'을 거르는 대척 설계를 이미 확정 운영 중.

### 보류 등록 (0콜 유병률 실측 전 채택 금지)
1. **자동 모순/지식 업데이트 감지 배치**: corrected_by 사용 0건, 라이브 모순 빈도 미측정. 한계 인식: supersede 발동은 **write-time 게이트가 '같은 사실의 새 버전'을 인지한 경우**에만 일어나는데, G-qual/G-AS는 '이 내용을 저장할까'만 판정하고 기존 행과의 모순/대체 관계는 보지 않는다 — **새 버전이 별개 행으로 저장되는 경로가 기본**이며 supersede 113행은 그 우회가 이미 발생한 사례일 수 있다. 채택 전제 = 라이브 트래픽에서 'supersede로 못 잡은(별개 행으로 저장된) 모순' 유병률 실측(사람 라벨링, 0콜) + 검출된 경우가 실제 회수/노출에 해를 주는지(과거 gold 유실) 확인.
2. **능동 소비(dialectic-style tool-use reading)**: 우리 소비는 정적 prefetch top-k + 프레이밍. '필요할 때만 추가 수집'은 stage93/94 정답 활용 −16pp 문제의 다른 해법 축일 수 있으나 Hermes 플러그인 구조 변경 + 턴당 비용 증가 → 사용자 승인 영역. 미실측.
3. **surprisal 기반 표적 재추론 (신규 축 — 상세 메커니즘, 소스 실측 기준)**: Honcho의 dream 주기가 '메모리 전체 재처리' 대신 **'이례적인 기억만 추려 추론 예산을 집중'**하는 표적화. 점수 = 정보 이론의 surprisal(−log P): 각 observation 임베딩을 트리 구조(설정 `TREE_TYPE`, kNN `TREE_K=5`)에 batch_insert 후 `tree.surprisal(embedding)`으로 이웃 밀도 추정 — **주변에 비슷한 기억이 거의 없는 기억 = 높은 surprisal**. min-max 정규화 후 상위 `TOP_PERCENT_SURPRISAL=0.10`(최소 1건)만 선별(`_filter_by_percent`), `SAMPLING_STRATEGY="recent"`(기본)으로 후보를 최근 observation으로 한정. 선별된 기억은 hint로 deduction specialist에 전달(specialist는 hint에 얽매이지 않고 자유 탐색 가능) — '평범한 기억은 건드리지 않고 특이한 기억에만 추론 예산을 쓰는' 전략. 매 dream 주기마다 새 observation이 들어오면 trigger(`DREAM.DOCUMENT_THRESHOLD` 등). **왜 우리는 보류인가 (chat 답변 요약)**: ① **코퍼스 규모** — 트리 분포가 있어야 점수 의미가 있고 Honcho 자체도 `TREE_K*2` 미만이면 skip; 우리 2,085행은 '회의가 화요일→목요일' 같은 명백한 버전 충돌이 이미 write-time supersede(113행)로 처리되는 밀집 규모라 이례성 표본이 대부분 작업 지시/이벤트 반복 노이즈(stage64~66 규칙 행 도배·mem0 프로브 정확 중복 15그룹의 재현) ② **문제가 이미 다른 경로로 처리됨** — 모순/버전 충돌은 write-time supersede+valid_until 담당, corrected_by 0건 = 자동 감지가 구제할 미처리 모순 유병률 미실측 ③ **fail-open 원칙 리스크** — '이례적인 기억' 표적 집중은 드물지만 중요한 기억의 강등/삭제 위험을 수반, 채택 전제 = production-exact rank>20 gold(stage85) 유지 3-run 전체 재현 회귀. → **'신규 축'으로만 등록, 0콜 유병률 실측(1차: supersede로 못 잡는 모순 존재 여부) 전 채택 금지.**

### 정합 확인 (변경 없음, 정보로만)
- RRF k=60 동일 — 검색 융합 상수가 외부 SOTA 시스템과 일치 (우리 후보 풀 구성의 표준성을 지지하는 간접 신호).
- BEAM 능력별 분해(contradiction·temporal·knowledge-update·abstain)는 우리 canary L1/L2가 '능력별 조합'이 아닌 것에 대한 벤치 설계 참고 — canary 쿼리는 이미 실측 기준값 있는 쿼리 재사용 원칙 유지(신규 생성 금지).

## 5. 재현 경로

- Honcho 소스: `raw.githubusercontent.com/plastic-labs/honcho/main/src/{dreamer/surprisal.py, dreamer/orchestrator.py, dreamer/specialists.py, deriver/prompts.py, dialectic/core.py, utils/search.py}`
- evals: honcho.dev/evals (2025-12 갱신), 벤치 raw: github.com/plastic-labs/honcho-benchmarks
- DB 프로브: `jev_db_probe*.py` (scratch) — working_memory 2,085행 기준 supersede/valid_until/corrected_by/규칙 행 유병률

## 6. 결론

Honcho는 '저장 후 비동기 LLM 추론(deriver+dream+peer card)'으로 메모리 가치를 만드는 대척 설계 — 우리의 'write-time 게이트 + read-time JEV rerank'와 방향이 반대다. 직접 이식 사항은 없다: 지식 업데이트는 우리 supersede+valid_until이 기능적으로 우위(삭제 없음)이나 **결합 한계**(G-qual이 모순을 보지 않아 '새 버전 별개 저장' 우회 가능, corrected_by 0건)를 보류 1로 등록. peer card 규칙은 실측 기각 레버와 겹침, 비동기 추론은 코퍼스 규모상 시기상조. 유일한 가치 = 설계 정합 확인(RRF k=60 일치)과 보류 3건(모순 감지·능동 소비·surprisal 표적 재추론)의 레버 지도 확장. 특별한 라이브 문제와 교차하지 않으므로 우선순위 낮음.