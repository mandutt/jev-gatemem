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
| **★ G-AS 적용 확인 (2026-09-29)** | ✅ | **§8.5 체크리스트 실측 통과** — `sync_roles=[user, assistant]` 로드, trace `write-gate-as` 이벤트 실세션 발화로 기록(KEEP/SKIP 모두), session `hermes_20260929_104012_df1103`에 `[ASSISTANT]` 레코드 8건 저장, final 발화 KEEP/중간 진행 SKIP 판정 정상 |

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

> **2026-09-28 갱신 — JEV 생성 분류(Ingestion Classification) 평가 + 쓰기 게이트 구현 완료**. 최종: **P8 + G-qual**
> 명명 규칙: **P{번호}** = JEV 프롬프트 버전 (P8 = 84.9%, 채택) / **G{규칙}** = 저장 게이트 (G-qual = store==NO_STORE && type==NO_STORE && conf≥0.6 → SKIP, type rescue 포함). 조합 표기가 곧 최종.
> 상세: `memory-classification-evaluation/JEV_INGESTION_REPORT.md`, `AB_WRITE_GATE_REPORT.md`.

**★ 쓰기 게이트 실장 (2026-09-28) — 구현 완료, 적용 승인 대기**
- `gateway/write_gate.py` — G-qual 평가 (P8 스토어/분류 지시문, 킬스위치 `JEV_WRITE_GATE=0`, 실패→KEEP, **KEEP/SKIP 모두 trace** (2026-09-29 B 반영))
- `harnesses/wg_access.py` — 섀도잉 안전 accessor (alias → repo fallback)
- `harnesses/hermes_j1.py` — `JevRerankProvider.sync_turn` 오버라이드: user 발화만 게이트 (SKIP 시 `_sync_turn_without_user`로 저장), assistant는 무게이트, 실패→base. **주의: `_sync_roles` 기본값은 `{"user"}`** — 기본 환경에선 user 발화만 저장되므로 게이트 실효 범위는 "user 발화 SKIP" 하나로 한정 (assistant 저장은 sync_roles에 assistant 추가 시에만)
- **검증**: `harnesses/smoke_write_gate.py` 4/4 PASS (SKIP/KEEP/킬스위치/JEV실패), 실 JEV API로 SKIP(좋아 진행해줘) vs KEEP(내일까지 보고서) 판정 확인, trace 로그 기록 확인
- ✅ **남은 일 완료 (2026-09-29)**: 데스크톱 재시작 후 실사용 확인 — **§8.5 체크리스트 실측 통과**: `sync_roles=[user, assistant]` 로드, `write-gate-as` trace 이벤트 실세션 발화로 기록(KEEP/SKIP 모두), session `hermes_20260929_104012_df1103`에 `[ASSISTANT]` 레코드 8건 저장 (final 발화 KEEP / 중간 진행 SKIP), content 앞 100자 확인됨. **장기 관측 지속**

**★ assistant 발화 저장 게이트 (G-AS) — 2026-09-28 구현 (커밋 7615e1a), 2026-09-29 적용 완료**
- **문제**: Mnemosyne 기본 `_sync_roles={"user"}` → assistant 결과물(작업 핵심)이 메모리에 안 남음. 사용자 지적: "지시만 저장하면 작업 내용을 기억 못 함"
- **실측**: 최근 21일 assistant 3,715건 중 200건 분류 → **79% 저장 가치** (유저와 정반대). gold50 인간 판정 → **G-AS 채택** (`store==STORE && type!=context → KEEP`, precision 0.744 / recall 0.935 / F1 0.829). **context 필터 전수 검증: 17건 gold → 오분류 0건** (결과물 손실 0, G-AS 확정)
- **폐기된 대안**: conf 임계값(결과물 conf 0.59~0.97 분산 → recall 폭락), commitment 필터(TP 6건 손실), P8-AS 전용 프롬프트(recall 0.355), 정규식 next-step 필터(FP 2/9만 매치)
- **주의**: JEV 호출은 반드시 TypeSafe 직접 API (`api.typesafe.ai/v1/systemone`, jev-latest) — 9router(localhost:20128)는 간헐적 400 반환
- **구현 내역**: `write_gate.evaluate_assistant()` (G-AS 규칙 + 1500자 truncation + 5xx/시간초과 1회 재시도), `hermes_j1.sync_turn()` 4-way 분기 (user G-qual / asst G-AS), `_sync_turn_without_assistant()`, 타임아웃 5s→15s (실측 latency 0.24~23s), config `memory.mnemosyne.sync_roles: [user, assistant]` (실제 홈 AppData\Local\hermes에 hermes config set으로 반영 — **주의: .hermes/가 아님**, get_hermes_home 기준)
- **검증**: smoke_write_gate 7케이스 ALL PASS + 실 DB 라이브 검증 (A: user만 저장, B: 둘 다 저장 — trace로 skip 확인, 테스트 메모리 삭제 완료)
- 산출물: `memory-classification-evaluation/ASSISTANT_GATE_REPORT.md`, `data/ab_assistant_gold50*`

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

## 8.5 G-AS 적용 확인 체크리스트 (재시작 후)

> 2026-09-28 구현 완료 — **Hermes 재시작(새 세션) 시 G-AS가 활성화됨**. 아래 순서로 확인:

1. **config 로드 확인**:
   ```
   hermes config get memory.mnemosyne.sync_roles   # → [user, assistant]
   ```
2. **`[ASSISTANT]` 자동저장 확인** (새 세션에서 대화 몇 턴 후):
   ```sql
   SELECT COUNT(*) FROM working_memory WHERE content LIKE '[ASSISTANT]%';
   -- 0 → sync_roles 미적용 (config 확인), N>0 → 정상
   ```
3. **G-AS 게이트 동작 확인** — `jev_trace.log`에서 `write-gate-as` 이벤트:
   ```
   $LOCALAPPDATA/hermes/logs/jev_trace.log  (tail)
   # keep=skip ... reason=no-store / reason=context  → 게이트 정상 SKIP
   # reason=commitment-fp-v4  → commitment FP 필터 v4 동작 (2026-09-28 추가)
   # 이벤트 없음 → JEV_WRITE_GATE=0 확인 / TYPESAFE_API_KEY 확인
   ```
3b. **commitment FP 필터 v4** (2026-09-28 실험→라이브 반영):
   - 규칙: `gateway/write_gate.py` `_as_commitment_fp_filter` (KNOWLEDGE 보호 + TRANSITION×OPERATION/INTENT SKIP)
   - 실측: gold50 precision 0.744→0.806, recall 유지 0.935, 회귀 0, FP 43% 감소, 비용 0
   - 상세: `ASSISTANT_GATE_REPORT.md` §7, 실험: `experiments/exp2_*_rule_v*.py`
3c. **G-AS 실측 (2026-09-29, 세션 20260929_104012_df1103) — KEEP trace(B) + final-only 전달 확정**:
   - **B 구현 (unconditional KEEP trace)**: `write_gate.py` `evaluate()`/`evaluate_assistant()` — before: `if not keep: _jtrace` (SKIP만) → after: KEEP/SKIP 모두 trace (`keep=keep`/`keep=skip`, 같은 이벤트명). 검증: 라이브 4케이스 trace 4줄 정확 기록 + smoke 7케이스 ALL PASS + trace `keep` 0→8건. **플러그인 자체 완결성** (스킬/문서 없이 사후 감사 가능 — 다른 에이전트 연결 대비)
   - **Hermes는 final 발화만 provider에 전달** (C 관측): `turn_finalizer.py` → `_sync_external_memory_for_turn` 턴당 1회, `final_response`=마지막 assistant text. 도구 중간 assistant 발화는 sync_turn에 **도달 안 함** (#15218 "partial output is not durable truth"). 실측: 세션 assistant 53건 중 final(fr=stop) 5건만 게이트+[ASSISTANT] 저장 → 중간 발화 유실은 Hermes 설계, 플러그인 결함 아님 (수정은 Hermes 코어/별도 훅 몫)
   - **저장 session_id = `hermes_<session_id>`** (`_session_id = f"hermes_{stable_scope}"`), importance=0.15, scope=session, memory_type은 beam classify (게이트와 독립)
   - **[ASSISTANT] 첫 KEEP 실측**: 2026-09-29 세션서 final 발화 8건 저장 (결과물/판단형), trace `write-gate-as keep=keep` 동반. 과거(07-31~09-28)는 전부 SKIP(no-store/context) → 0건이 "게이트 미적용"이 아니라 "게이트가 정상 SKIP"이었음
   - **G-qual/G-AS 독립**: user SKIP + asst KEEP → `_sync_turn_without_user`로 [ASSISTANT]만 저장 (10:46:52 실측: write-gate skip + [ASSISTANT] row 동시, write-gate-as 무기록=KEEP)
4. **롤백 방법** (문제 시):
   - 게이트만 끄기: `JEV_WRITE_GATE=0` (환경변수) → 전부 KEEP
   - assistant 저장 끄기: `hermes config unset memory.mnemosyne.sync_roles` → user만
5. **장기 관측 후 리포트 갱신**: 1~2주 후 `[ASSISTANT]` 저장량·recall 영향 → `ASSISTANT_GATE_REPORT.md`에 실측 반영
5b. **v4 필터 실측 기준선/관측** (2026-09-28 협의 — gold50 50건은 추정치, 운용 데이터로 검증):
   - 기준선: `grep -c 'commitment-fp-v4' $LOCALAPPDATA/hermes/logs/jev_trace.log` (적용 직후 0건)
   - 관측: 1~2주 후 `grep 'commitment-fp-v4' ... | wc -l` + SKIP된 utterance(로그에 100자까지)를 gold 판정
   - 판정 기준: SKIP 중 실제 NO_STORE(FP) 비율 = live precision; **TP를 버린 회귀 1건이라도 발견 시 즉시 필터 비활성화 보고**
   - 결과를 `ASSISTANT_GATE_REPORT.md` §7 실측 표에 반영 (추정치 → 운용치 갱신)

**알려진 주의**:
- 실제 Hermes 홈 = `C:\Users\mandu\AppData\Local\hermes` (**`.hermes/` 아님**) — config 수정은 `hermes config set` 사용 (agent 직접 편집은 차단됨)
- JEV API 간헐 503/520 — 게이트는 KEEP으로 fallback (데이터 손실 없음), trace에 `http-5xx` 기록
- 라이브 JEV 호출은 발화당 ~0.2~2초 (가끔 15초+) — sync_turn이 그만큼 지연될 수 있음

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
| **쓰기 게이트** | `JEV_WRITE_GATE=0` → 비활성(KEEP). **KEEP/SKIP 모두** `jev_trace.log`에 `write-gate`(user) / `write-gate-as`(assistant) 기록 (2026-09-29 B: unconditional, `keep=keep`/`keep=skip`) |

## 10. 세션 전환 방법

- **새 세션**: Hermes desktop에서 `/new` → 이 핸드오프 문서를 참조해 "다음 단계" 중 하나 요청
- session_search로 과거 진행 복구 가능: 세션 ID `20260927_170219_d102fe` (Phase 1), `20260927_183939_2d9e83` (런타임 디버깅)