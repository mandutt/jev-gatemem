# Jev-Mnemosyne Middleware — 세션 핸드오프 문서 (2026-09-27, 런타임 통합 디버깅 완료)

> 새 세션에서 이어서 진행할 때 이 문서를 참고하세요.
> 갱신: 2026-09-27 저녁 세션 (런타임 J1 섀도잉 버그 수정 + 실사용 재검증 세션, 세션 ID 20260927_183939_2d9e83)

## 1. 프로젝트 목적

Mnemosyne (Hermes 로컬 메모리)에 TypeSafe Jev (System One) rerank를 접목한
경량 메모리 미들웨어. 저장소와 지능을 분리하고, 필요한 경우에만 Jev를 호출한다.

최종 아키텍처: `Downloads/mnemosyne_jev_memory_architecture_final_spec_v6.md` (v6 스펙)

## 2. 현재 상태: Phase 0~1 완료 + 런타임 통합 동작 확인 (2026-09-27)

| 단계 | 상태 | 결과 |
|---|---|---|
| Step 0 (환경 복구) | ✅ | Hermes v0.21.5 업데이트 후 venv 미스매치로 플러그인 깨짐 → `uv pip install mnemosyne-memory[embeddings] mnemosyne-hermes`로 복구, smoke test 통과 |
| Phase 0 (baseline) | ✅ | Mnemosyne 선형 recall: recall@10=0.019 (대화 덤프가 factual memory를 압도) |
| Pool 확장 | ✅ | FTS+vector lane 분리 (RRF): gold 포함 8% → 79% |
| Phase 1 (Jev rerank) | ✅ | **J1 = Jev choice 1회 + winner lift: recall@1 0.500→0.712, mrr 0.599→0.747** |
| 문서 기반 개선 | ✅ | Choice probabilities ❌ / Confidence-gating ⚠️유형선택 / Noul rerank ❌ / Budget100 ❌ → **J1 유지** |
| Phase 2 (Hermes 통합) | ✅ 구현 | **JevRerankProvider plugin** — lane pool + J1 lift prefetch, 회귀 8/8 PASS, fallback 401 OK, MemoryManager 계약 통과 |
| **게이트웨이 API 완성 (2026-09-27 밤)** | ✅ | **MemoryGateway.retrieve_candidates J1 기반 완성** — lane pool→gate→Jev lift, use_j1=False로 Phase 0 유지, fallback §19, j1_access 경유 섀도잉 안전. verify_gateway_api.py PASS + 런타임 venv smoke PASS |
| **런타임 통합 (2026-09-27 저녁)** | ✅ | **섀도잉 버그 수정 + `.env` 키 등록 + `Jev choice: idx=6 latency=265ms pool=10` 실측 성공** |
| **데스크톱 실사용 검증 (2026-09-27 밤)** | ✅ | 새 데스크톱 세션 1턴에서 `Jev choice: idx=0 latency=226ms pool=1` 실측 — shadowing 재발 없음 |
| **Experiment F (fallback, §26-F)** | ✅ | **4장애 모드(timeout/5xx/network disconnect/auth) 모두 pool 순서 보존, 예외 미전파. auth 401 라이브 검증, Jev OFF와 shape 동일. cross-mode PASS** |
| **실사용 A/B 1차 (2026-09-27 밤)** | ⏸️ 보류 | 12쿼리: 5/9 완전 동일, 4/9 순서 변경. **체감 구분 불가 → 데이터 2,000+ rows 후 재평가** (ab_jev_rerank/AB_REPORT.md) |
| **★ Hydration 버그 수정 (2026-09-27 밤)** | ✅ | **검색은 cross-session인데 hydration이 session-scoped → pool 밖 gold 62건의 실체 (408/524 search-hit 탈락). `get_hydrated()` cross-session 조회로 수정. pool 78.85%→92.31%, filtered 67.31%→78.85%. fallback §19 재검증 PASS** |
| **★ Importance 보조 lane (2026-09-27 밤)** | ✅ | **CJK LIKE 검색 한계(영어 content + row-limit)로 남은 gold 3건 → `_imp_search()` lane 추가 (importance≥0.85 최신 8개, RRF 통합). pool 92.31%→100%, filtered 82.69%, top-5 71.15%. fallback+runtime smoke PASS** |
| **★ Graph/Fact lane (2026-09-27 밤)** | ✅ | **`_graph_lane_search()` 3경로 (facts subject/object→source_msg_id, graph_edges gist→관련성 게이트, memoria_facts key/value→source_memory_id). 합성 데이터 검증 6/6 PASS (회수 경로 정확), 실데이터 4-lane 지표 3-lane과 동일 (100%/82.69%/71.15%, 성능 무하락). 현재 실데이터로는 gold 추가 회수 0 (facts 5개뿐) — 데이터 축적 후 재평가** |
| **★ 한국어 어미 분류 패치 (2026-09-27 밤)** | ✅ | **Mnemosyne `typed_memory.py`에 한국어 어미 패치** (28종성 클래스 + 의문/지시/단정/격식 24패턴). "좋아 진행해줘" fact 오분류 해결. 한국어 39/39, 영어 13/13, 라이브 36건 재분류 정상. **②번 `\b`→ASCII 경계 수정** ("error가" 한-영 혼용 매치, 관계 패턴 동사 정밀화로 relationship 오분류 36→0) + **④번 F1/F2 구조 수정** (종결형 FACT 어미 10개 `(?![가-힣])` 후방차단 + version 패턴 `(?![A-Za-z0-9_-])` — 라이브 823건 A/B 7건 fact→context 전부 개선, 회귀 0) + **⑤번 한글 ERROR 구문 패턴** (2026-09-28, "오류가 발생했어"류 6개 패턴 — 라이브 828건 3건 context/relationship→error 실제 오류 보고, 회귀 0, 스모크 15/15). ①(어휘)·③(score=conf)은 실험 결과 부정적(179건 회귀)로 **보류**. **재적용**: `scripts/reapply_korean_classifier.py` (②+④+⑤ 통합, f4/f5_patch import, 멱등). 문서: `docs/korean-classifier-patch.md` (①③④⑤ 실험 결과 포함). 스킬: `mnemosyne-korean-classifier` |

## 3. 오늘(2026-09-27 저녁) 변경 사항 — 반드시 읽을 것

### 원인: `gateway.j1_pipeline` 모듈 섀도잉 (이번 세션의 핵심 발견)

- **문제**: Hermes 프로세스가 부팅 시 자기 `hermes-agent/gateway/` 패키지를 import
  → 플러그인 wrapper가 middleware repo를 `sys.path`에 넣어도
  `from gateway.j1_pipeline import ...`가 **항상 Hermes의 gateway로 resolve되어**
  `ModuleNotFoundError: No module named 'gateway.j1_pipeline'` 발생
  → prefetch가 조용히 **Mnemosyne-only fallback**으로 떨어짐 (러닝에는 영향 없음)
- **증상**: agent.log에 `Memory provider 'mnemosyne' prefetch failed (non-fatal): No module named 'gateway.j1_pipeline'` (DEBUG)
- **수정**: `harnesses/j1_access.py` (신규) — shadowing-safe accessor
  - `sys.modules['gateway']`가 이미 있으면 백업→pop→middleware repo에서 import→`sys.modules['_j1_gateway']`로 alias→원본 복원
  - `j1_pipeline()` 함수가 alias 경로로 모듈 반환
  - `hermes_j1.py`가 bare `from gateway.j1_pipeline import ...` 대신 이 accessor 사용
  - **되돌리면 안 됨**: bare import로 되돌리는 순간 다시 실패
- **검증**: 19:19:04 `INFO j1_pipeline: Jev choice: idx=6 latency=265ms pool=10` (CLI 세션에서 실측 성공)

### `.env` 키 등록

- `TYPESAFE_API_KEY`를 `C:\Users\mandu\AppData\Local\hermes\.env`에 등록 (기존에 없었음)
  - 그 전까지 desktop/CLI Hermes 프로세스는 키가 없어서 Jev 전부 스킵
  - bash 셸에는 있었지만 Hermes 프로세스(os.environ)에는 없었던 것이 원인
- **주의**: 새 세션에서 키 값이 필요한 경우 `.env`에서 읽거나 사용자에게 확인 (값은 여기에 적지 않음)

### 플러그인 설치 위치 (실측)

- **설치본**: `C:\Users\mandu\AppData\Local\hermes\plugins\jev-mem\` (wrapper + plugin.yaml)
  - `~/.hermes/plugins/jev-mem/`가 아니라 `$LOCALAPPDATA/hermes/plugins/` (Windows desktop 경로)
  - wrapper `__init__.py`는 `C:\Users\mandu\hermes-made\jev-memory-middleware`를 sys.path에 넣고 `harnesses.hermes_j1` import
- 소스: `hermes-made/jev-memory-middleware/harnesses/hermes_j1.py` (단일 소스)

### 런타임 동작 확인 요약

- prefetch는 **시스템 프롬프트가 아니라 턴의 user 메시지(api_content sidecar)에 주입**
  - `## Mnemosyne Context` 블록이 시스템 프롬프트에서 보이지 않아도 정상일 수 있음
- Hermes 로그에서 확인: `grep "Jev choice" $LOCALAPPDATA/hermes/logs/agent.log`
- 실패 시 fallback: `prefetch failed (non-fatal)` 로그 → Mnemosyne-only (스펙 §19 준수)

## 4. 검증 방법 (재현)

```bash
# 로그에서 J1 동작 확인
grep "Jev choice" "$LOCALAPPDATA/hermes/logs/agent.log"

# Jev 개입 trace (lane별 기여/gate/Jev 선택/lift) 확인
tail -20 "$LOCALAPPDATA/hermes/logs/jev_trace.log"

# CLI로 턴 1회 → Jev choice 라인 확인
"$LOCALAPPDATA/hermes/bin/hermes.exe" chat -q "검증 쿼리"
```

**데스크톱은 재시작해야 새 코드가 로드됨** — 기존 데스크톱 세션(18:39 부팅)은 구버전 코드.

## 5. 파이프라인 (prefetch당)

```
lane pool (FTS 60 + vec 60 + importance 8 + graph 10, RRF k=30) top-40
  → 보수적 게이트 (lexical 겹침 ≥2토큰 & coverage ≥0.30, 소스 품질 가중)
  → Jev choice 1회 (5s timeout) → top1 lift
  → top-5 → "## Mnemosyne Context" 블록 (Mnemosyne 포맷 그대로)
  → Jev 실패/타임아웃/비활성 → pool-only 결과 (fallback, 스펙 §19)
```

**4-lane 구조 (2026-09-27 밤 확정)**:
- **FTS 60** — `_fts_search_working` (cross-session, CJK LIKE 포함)
- **vec 60** — `_wm_vec_search` (임베딩)
- **importance 8** — `_imp_search()`: importance≥0.85 최신 8건 (언어 무관, CJK row-limit 한계 보완)
- **graph 10** — `_graph_lane_search()`: facts/graph_edges/memoria_facts 관계 회수 (노이즈 게이트: confidence≥0.5 + gist 관련성 확인 + budget 10)
- 전부 `recall_raw()` supplier로 `build_lane_pool()`에 연결, 오류 시 개별 lane만 skip (fallback §19)

## 6. 프로젝트 구조 (현재)

```
C:\Users\mandu\hermes-made\jev-memory-middleware\
├── gateway/               # types.py, excerpts.py, gateway.py (J1 API 완성), j1_pipeline.py, trace.py
├── backends/mnemosyne.py  # Mnemosyne 백엔드 어댑터
├── jev_controller/        # scorer.py (JevScorer), fusion.py (RRF)
├── harnesses/
│   ├── hermes_j1.py       # JevRerankProvider(MnemosyneMemoryProvider) — prefetch 오버라이드
│   ├── j1_access.py       # ★ NEW: shadowing-safe accessor (gateway.j1_pipeline import 문제 해결)
│   ├── install_plugin.py  # 플러그인 설치 스크립트
│   └── jev_mem_plugin/    # wrapper __init__.py
├── experiments/           # lane_pool.py, run_phase1_v2.py, smoke_*.py, run_experiment_f.py (신규)
│   ├── trace_live_prefetch.py         # ★ 라이브 J1 파이프라인 단계별 trace 스크립트
│   ├── verify_trace.py                # ★ trace.py ring buffer 단위 검증
│   ├── verify_graph_lane_synthetic.py  # ★ graph lane 합성 데이터 검증 (6/6 PASS)
│   ├── verify_imp_lane.py              # ★ importance lane 검증
│   └── results/           # PHASE1_REPORT.md, EXPERIMENT_F_REPORT.md, DOC_IMPROVEMENTS_REPORT.md, ledger.jsonl 등
├── scripts/
│   └── reapply_korean_classifier.py    # ★ 한국어 어미 분류 패치 재적용 + 검증 (업데이트 대비)
├── docs/
│   └── korean-classifier-patch.md      # ★ 한국어 분류 패치 문서 (패턴 표, 종성 인덱스, 검증 기록)
├── data/
│   ├── dataset_curated.json    # 52쿼리 평가셋 (gold 16자리 ID)
│   └── snapshots/snap-20260927.db  # 766 rows 스냅샷
├── HANDOFF_NEXT_SESSION.md  # 이 문서
└── .venv/                 # Python 3.12 전용 venv
```

## 7. 핵심 발견 (반드시 기억)

1. **Jev choice 질문만 rerank에 유효** — score는 요청당 답변 수 제한+점수 몰림, Noul은 한국어에서 변별력 없음(recall@1 0.183)
2. **TypeSafe API**: `POST https://api.typesafe.ai/v1/systemone`, model `jev-latest` (= jev-1.13.0), `TYPESAFE_API_KEY` (이제 `.env`에 있음)
3. **CJK 언어 제약**: Jev는 영어 우선, 한국어는 정확도 낮음 (Noul 실패 원인)
4. **Jev choice는 비결정적** — 동일 입력 재실행 시 선택 다를 수 있음 (miss 2/4는 이 때문)
5. ~~lane pool 자체가 gold 포함 79%가 한계~~ → **수정됨: hydration 버그였음. 이제 92.31%** (아래 11번 참조)
6. **gateway 패키지 섀도잉**: Hermes 자체 `gateway/` 패키지가 있어 `from gateway.j1_pipeline import ...`은 항상 실패 → **j1_access.py 경유 필수**
7. **`sys.modules` 영속성**: 한 번 import된 `gateway`는 sys.path 변경으로는 못 바꿈 (섀도잉이 생존하는 이유)
8. **MnemosyneMemoryProvider.name은 @property** — override할 때도 @property 유지
9. **user plugin dir 로딩**: `register_memory_provider(ctx)` 함수만으로는 dir loader가 인스턴스 못 잡음 → **모듈에 MemoryProvider 서브클래스 노출 필수**
10. **환경변수 vs os.environ**: Hermes 프로세스는 `.env` 파일에서 키를 읽지만, **기존 bash 세션의 export는 Hermes 프로세스에 전달 안 됨** — `.env` 등록이 유일한 방법
11. **★ 검색과 hydration의 격리 수준 불일치 (2026-09-27 밤 발견)**: `_fts_search_working`/`_wm_vec_search`는 cross-session인데 `BeamMemory.get()`은 `(session_id=? OR scope='global')` 필터 → **다른 세션 메모리는 검색엔 잡혀도 pool에서 조용히 탈락** (실측: 408/524 search-hit 탈락, gold 쿼리 기준 14건). Mnemosyne의 의도된 설계(세션 격리)이며 4.0.0b3에서도 유지됨. **해결: `get_hydrated()` (id-only SQL, working→episodic)로 교체** — middleware 레이어에서 해결, Mnemosyne core 무수정
12. **Mnemosyne 버전 정책**: 3.15.1 고정 (Hermes 런타임과 일치). 4.0.0b3는 베타 메이저라 하위호환 미보장 — **4.0.0 stable + mnemosyne-hermes 호환 확인 후 업데이트** (신규 메모리는 scope='global' 기본이라 get()에 노출되는 이점)
13. **★ CJK 검색 한계 (2026-09-27 밤 발견)**: `_cjk_like_search`는 (a) content에 쿼리 한글 문자가 **하나라도** 있어야 하고 (b) LIMIT k*5=300 row로 잘라 score 순위를 매김 → **영어 content 메모리는 순수 한글 쿼리에서 무조건 탈락**, 한글 content도 row-limit으로 고득점자가 밀려날 수 있음. vec도 한국어-영어 크로스랭귀지가 약해서 못 살림. **해결: importance 보조 lane** — 언어 무관하게 importance≥0.85 고신뢰 메모리 8개를 항상 pool에 포함 (실측: 남은 gold 3건 전부 회수 → pool 100%)
14. **★ graph 데이터는 존재한다 (2026-09-27 밤 재발견)**: `triples`(0행)는 **E6 마이그레이션으로 deprecated된 레거시** — post-E6 엔티티 저장은 **`annotations` 테이블 (LIVE 2,715행)**. Hermes 어댑터가 매 턴 `extract_entities=True`로 remember → `occurred_on`/`has_source`/`mentions` 등이 쌓임. graph/fact lane을 만들려면 `annotations`/`graph_edges`(gist→fact ctx)를 봐야 함
15. **★ graph lane 검증 방법 (2026-09-27 밤 확립)**: 현재 실데이터 (facts 5 / graph_edges 7 / memoria_facts 95)로는 **graph lane 회수 경로 검증 불가** → **합성 데이터 주입으로 검증**: 스냅샷 복사본에 facts/graph_edges/memoria_facts를 심고 `_graph_lane_search`가 gold를 회수하는지 확인 (verify_graph_lane_synthetic.py, 6/6 PASS). 메모리가 늘면 같은 스크립트로 실데이터 재평가. 참고: `_query_tokens`는 스네이크 결합 토큰 분리 처리 (python_version→python, version)
16. **★ 한국어 어미 분류 패치 (2026-09-27 밤, Mnemosyne core 수정)**: `typed_memory.py` 원본은 영어 정규식뿐 → 폴백 `default_short`(단어<5)가 한국어를 전부 FACT로 오분류 ("좋아 진행해줘"→fact). **28종성 클래스 + 어미 패턴 24종 주입으로 해결** (한국어 39/39, 영어 13/13, 라이브 36건 재분류 정상). **Mnemosyne 업데이트가 이 파일을 덮어쓰면 패치가 사라짐 → `scripts/reapply_korean_classifier.py`로 재적용** (라이브 vs 재적용 40/40 일치 검증). 상세: `docs/korean-classifier-patch.md` + 스킬 `mnemosyne-korean-classifier`. ⚠️ 라이브는 Hermes 설치 venv만 패치됨 (middleware `.venv`는 원본)
17. **★ trace 로그도 bare import 금지 (2026-09-27 밤 실증)**: `gateway/j1_pipeline.py`에 `from gateway.trace import trace`를 모듈 레벨로 추가하면 Hermes 프로세스에서 **조용히 prefetch가 fallback**됨 (warning/에러 로그도 안 남음 — j1_access가 alias로 로드하고 원본 gateway를 복원한 뒤라 bare import가 Hermes core gateway를 봄). **해결: `_jtrace()` 지연 헬퍼** — alias(`__j1mw_gateway`).trace 우선 → standalone `from gateway.trace` → repo 직접 파일 로드 fallback. **주의: `alias.trace`는 첫 호출 시 서브모듈이 로드되며 모듈→함수 변환이 필요** (`getattr(t, "trace", None) or t`) — 이걸 빼면 첫 호출만 기록되고 이후 조용히 누락 (실측: smoke 8쿼리 중 1줄만 기록됨)

## 8. 다음 단계 (남은 작업 우선순위)

- [x] **데스크톱 재시작 후 실사용 검증** — 2026-09-27 밤 세션: `Jev choice: idx=0 latency=226ms pool=1` 실측 (agent.log)
- [~] **JEV_RERANK=0 vs 1 실사용 A/B — 1차 완료(보류)** — 12쿼리 페어와이즈: 5/9 완전 동일, 4/9 순서 변경(대부분 1↔2 스왑). 사용자 체감 차이 없음 → **메모리 2,000+ rows 후 재평가**. 산출물: ab_jev_rerank/AB_REPORT.md + run 스냅샷 + pairs.html
- [x] **gateway.py의 retrieve_candidates/retrieve 완성** — J1 파이프라인(lane pool→gate→Jev lift) 기반 MemoryGateway 완성. use_j1=False로 Phase 0 surface 유지, fallback §19, j1_access 경유 섀도잉 안전. 검증: verify_gateway_api.py pass + 런타임 venv smoke PASS (+ JEV_RERANK=0 킬스위치 존중 버그 수정)
- [x] **Experiment F (fallback 실험, 스펙 §26-F)** — 2026-09-27: 4장애 모드 전부 pool 순서 보존+예외 미전파, auth 401 라이브 검증, Jev OFF와 shape 동일 (results/EXPERIMENT_F_REPORT.md)
- [ ] 데이터가 쌓인 뒤 (2,000+ rows) 유형별 하이브리드 재검토 (project→J1, causal/factual/failure→J1c)
- [x] **★ Hydration 버그 수정 (2026-09-27 밤)** — `get_hydrated()` cross-session 조회 추가 (backends/mnemosyne.py, gateway.py 2곳, harnesses/hermes_j1.py). pool 78.85%→92.31%, filtered 67.31%→78.85%. fallback §19 재검증 + runtime smoke PASS. **플러그인 재설치 필요 없음** (harnesses/hermes_j1.py가 단일 소스, sys.path에 middleware repo 있음) — 단, **데스크톱 재시작해야 새 코드 로드**
- [x] **★ Importance 보조 lane (2026-09-27 밤)** — `_imp_search()` lane 추가 (`gateway/j1_pipeline.py`, `gateway.py` 2곳, `harnesses/hermes_j1.py`). importance≥0.85 최신 8개를 RRF 통합. 검증: verify_imp_lane.py → pool 92.31%→**100%**, filtered 82.69%, top-5 71.15%. fallback F 재실행 PASS + runtime smoke PASS
- [x] **★ Graph/Fact lane (2026-09-27 밤)** — `_graph_lane_search()` 3경로 구현 (`gateway/j1_pipeline.py`, `gateway.py` 2곳, `harnesses/hermes_j1.py`): ①facts/consolidated_facts subject/object 매치→source_msg_id ②graph_edges gist 스트립+관련성 게이트 ③memoria_facts key/value→source_memory_id. **검증: 합성 데이터 6/6 PASS** (verify_graph_lane_synthetic.py), 실데이터 4-lane 지표 무하락 (100%/82.69%/71.15%), fallback F PASS, runtime smoke PASS. 현재 실데이터로 gold 추가 회수 0 → **data 축적 후 재평가 (facts 수십+ 이후)**
- [x] **★ Jev 개입 trace 로그 (2026-09-27 밤)** — `gateway/trace.py` — ring buffer 로거: `$LOCALAPPDATA/hermes/logs/jev_trace.log` (기본, `JEV_TRACE_PATH`로 오버라이드), cap 512KB 초과 시 선두 절반 폐기 (파일 상시 ~256~512KB 수렴, 무한 증가 없음). prefetch당 4이벤트 기록: `pool`(lane별 기여: fts/vec/imp/graph/pool) → `gate`(pool/passed) → `jev`(idx/lat_ms/pick) → `lift`(lifted/from_idx/picked_id/prev_top). Jev OFF/fallback 시 trace 미기록. **검증: verify_trace.py (ring 단위), 섀도잉 시뮬레이션 PASS, smoke --on 8쿼리×4이벤트=32줄, --off 회귀 8/8, verify_gateway_api pass**
- [ ] **Mnemosyne 업데이트 시** — `typed_memory.py` 한국어 패치 재적용: `.venv\Scripts\python.exe scripts\reapply_korean_classifier.py` (라이브 vs 재적용 40/40 검증됨). 업데이트 자체는 §7-12 정책(3.15.1 고정, 4.0.0 stable 확인 후) 따름
- [ ] graph/fact lane — **실데이터 재평가**: facts/graph_edges/memoria_facts가 쌓이면 (수십 개 이상) verify_graph_lane_synthetic.py 방식으로 실데이터 gold 회수 확인 후 lane 상세 튜닝 (budget/confidence 임계값)

## 9. 환경 요약

| 항목 | 값 |
|---|---|
| Hermes | v0.21.5+3141.ga1d2a5b (2026-09-24) |
| Mnemosyne | v0.15.1, DB 766 working / 113 episodic / 95 memoria facts |
| DB 경로 | `C:\Users\mandu\AppData\Local\hermes\mnemosyne\data\mnemosyne.db` |
| 플러그인 | `C:\Users\mandu\AppData\Local\hermes\plugins\jev-mem\` (설치본) |
| 키 | `TYPESAFE_API_KEY` → `C:\Users\mandu\AppData\Local\hermes\.env` (등록 완료) |
| 런타임 venv | `C:\Users\mandu\AppData\Local\hermes\installs\315db7b763fb0d0a\environments\746564964b1042b79add42260378503b\venv\` |
| Jev API | `https://api.typesafe.ai/v1/systemone`, model `jev-latest`, TYPESAFE_API_KEY |
| 스냅샷 | `data/snapshots/snap-20260927.db` (실험용, 프로덕션 DB와 분리) |
| 평가셋 | `data/dataset_curated.json` (52쿼리, 6유형, gold 16자리 ID) |
| 로그 | `C:\Users\mandu\AppData\Local\hermes\logs\agent.log` (`grep "Jev choice"`) |
| **Jev trace 로그** | `C:\Users\mandu\AppData\Local\hermes\logs\jev_trace.log` (ring buffer 512KB, `JEV_TRACE_PATH`로 경로 변경 가능) |

## 10. 세션 전환 방법

- **새 세션**: Hermes desktop에서 `/new` → 이 핸드오프 문서를 참조해 "다음 단계" 중 하나 요청
- session_search로 과거 진행 복구 가능: 세션 ID `20260927_170219_d102fe` (Phase 1), `20260927_183939_2d9e83` (런타임 디버깅)