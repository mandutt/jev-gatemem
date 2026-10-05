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
| **★ 인젝션 스크린 · screening 신호 — 보류 (2026-10-05, 검토 대기)** | ⏸️ | **hermes-jev-skills 대조 후 0콜 실측 6종 완료.** ① 저장소 영어 local_screen 직접 이식은 한국어에서 무력(인젝션 catch 3%, FP 4.06%) → 기각. ② 신규 **한글 스크린**(명령형 어미+위험 신호 결합 규칙)은 **인젝션 30/30 catch · DB FP 0/1796** 검증 완료. ③ **screening 신호 실측**: fail-open(10-03) 23회에서 Jev 미검증 passage가 풀째로 컨텍스트 진입 — 읽기 경로 비대칭 확인. ④ 메모리 1,796행 출처 분류: **외부 제어 텍스트 378행(21%)** — @url/@file 첨부(70)·백그라운드 출력(107)·타 에이전트 자동주입(201). **사용자 지시: 당장 채택 금지 — 추후 외부 AI 검토 후 재판정.** 산출물: `experiments/operational-golden/screen_probe_*` + `SCREEN_PROBE_REPORT.md`, 검토 요청서: `docs/review/2026-10-05_인젝션스크린_screening신호_검토요청.md`. production 코드 미변경. |
| **★ [ASSISTANT] prefetch 제외 해제 (2026-10-05)** | ✅ | **`_PREFETCH_EXCLUDED_PREFIXES = ("[ASSISTANT]",)` → `()` (커밋 `ffb2ca5`) + 데몬 재시작 반영 (커밋 `73cb1f5`).** 근거: 장문 청킹 7단계 실측 끝에 "gate 1/19 = 제외 정책 동작"임을 발견, 회귀 실측(stage9) op-90 81/90 유지·noans 오주입 0 후 채택. 장문 assistant 보고서 회수 gold 1/19→8/19. 라이브 실측: 재시작 후 passed 48→85. 관찰: shadow 배치로 추적 중 (롤백 시 `89282ee` revert). 상세: `STAGE1_LONGMEM_PROBE.md` 실측 8~9, `docs/ops/2026-10-05_assistant-exclusion-lift-restart.md` |
| **★ POOL_BUDGET 40→60 (2026-10-05)** | ✅ | **후속 실측 stage10~15 (3종 AI 검토 반영): ①임베딩 하네스 버그 발견 — 직접 `TextEmbedding()`이 bge-small 로드(beam 경유만 bekko-a8m), stage1b/1c/3 벡터 실측 무효 ②정확 모델 재실측: chunk rank≤2 0→10건 ③parent multi-vector 통합 이득 0 → (2026-10-05 재검토로 번복: build_lane_pool이 chunk lane을 호출 안 하는 하네스 오류였음, stage23에서 진짜 통합 +3 확인) ④잔여 탈락 7건 = top-40 랭크 컷 ⑤POOL_BUDGET 스윕 40→100: gold gate 8→14, op-90 회귀 0 ⑥Jev 실제 lift: cut 60에서 1/6건만 lift, **cut 80/100은 abstain 폭증(b-ai: API criteria 63한도 가능성, 미확인)** → 60 채택(단, "실질 상한"이 아닌 "측정 범위의 무난한 operating point"로 표현 정정).** `POOL_BUDGET=60`+`POOL_DEFAULT_TOP=60` (gateway/j1_pipeline.py), 토큰 +50% 연간 ~$11~22 무시 가능, 콜 불변. 데몬 재시작 반영 필요. 상세: `STAGE1_LONGMEM_PROBE.md` 후속 실측 10~15 |
| **★ 답 구간 발췌(snippet 윈도우) 반영 (2026-10-05)** | ✅ | **기저율(→노출율로 정정) 실측(stage16): query_log 87건 중 장문이 gate 통과 85/87(98% — 구성에서 나오는 노출율, 진짜 기저율 아님)인데 top-1 0건 = head 절단이 lift를 막는 갭 확인 → stage17/18: `_query_window`(쿼리 인지 300자→150 excerpt)를 장문(>800자)에만 적용 → gold lift 3/12→5/12(+2, 손실 0; 24반복은 가짜 반복으로 n=12 환산), op-90 회귀 0, noans 변화 0. (2026-10-05 재검토 정정: "부분 반영=전면과 동일"은 아직 미검증이었음 → stage23 all-candidate로 production 형태 검증 완료, +2 유지.)** `jev_rerank` 라벨 생성 반영(gateway/j1_pipeline.py) + 데몬 재시작. 토큰 연간 ~$30, 로컬 스캔 수십 ms. 상세: `STAGE1_LONGMEM_PROBE.md` 실측 16~18 |
| **★ excerpt 전면 win-300 + abstain_p soft gate (2026-10-06)** | ✅ | **stage20~27 실측 끝에 excerpt를 전 후보 300자 윈도우로 전면 적용 + choice abstain_p>0.3이면 빈 컨텍스트(soft gate).** 근거: ① 800자 임계만으론 abstain 3건(답이 300~670자에 위치) 미해결 ② win-300 단독은 noans 오주입 +7로 1차 기각 ③ **B AI 지적으로 분모 오류(harm-가중, u=22.5%) 재판정** + C AI 지적으로 `_jev_choice`가 probabilities 파기하던 것 발견 → abstain_p soft gate로 noans 비용 상쇄. 실측: op hit@3 72→77(85.6%), hit@5 74→80(88.9%), abstain 9→3, noans hard 22→16 FP, 독립 easy 셋 0 FP. **커밋 `c433195` + 데몬 재시작 반영(2026-10-06), trace에 `abstain_p` 필드 추가, `JEV_SOFT_ABSTAIN_TAU=0.3`(env 오버라이드).** 롤백: 커밋 revert. 상세: `STAGE25_PROBABILITY_20261006.md`, `experiments/operational-golden/RECALL_ABSTAIN_INVESTIGATION_20261005.md`, `docs/ops/2026-10-06_win300-soft-abstain-restart.md` |
| **★ chunk-vec lane 재검증 — 보류 (2026-10-05)** | ⏸️ | **stage12/20의 "기각"은 하네스 오류로 번복** (build_lane_pool이 chunk lane 미호출). stage23 진짜 5레인 RRF: gold pool 13→16(+3, 실효 gate +2 — afd156a9는 60컷 밖). POOL-MISS 4건 중 1건만 구제. **실효 +2 vs 영구 청크 인프라 → 사용자 판단: shadow enforcement 실측 후 재판정 예약. 코드 미반영, 스크립트만 보존.** |
| **★ gold 미선택 9건 판정 (2026-10-05)** | ✅ | **A(VALID) 6건 / B(PLAUS) 2건 / C(IRREL) 1건** — "게이트 통과 ≠ lift" 갭의 대부분은 gold exact-ID 지표의 인공물(다른 후보가 같은 답). 실질 오선택은 abstain 1건뿐. choice 프롬프트 문제 아님. 상세: `STAGE1_LONGMEM_PROBE.md` 실측 26, `data/stage26_verdicts.json` |
| **★ shadow 지표 보강 (2026-10-05)** | ✅ | **assistant 오염 지표 추가**: 최종 선택(winner) 중 [ASSISTANT] 비율 — 누적 308건 기준 16.7% (40/240). 기존 gate NO율·R2 abstain·오류율 + 신규. 토큰 p50/p95는 shadow_log에 렌더 크기 없어 미구현(스키마 확장 시). 상세: `STAGE1_LONGMEM_PROBE.md` 실측 27 |
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

> **2026-09-30 외부 AI 검토 후속 사이클 완료** — 검토 브리프(`docs/design/multi-agent-implementation-review-brief.md`)에 대한 외부 검토서(`jev-mem-core-implementation-review.md`)의 지적을 전부 처리:
>
> | 항목 | 결과 |
> |---|---|
> | A1 골든 동등성 | ✅ 22/22 (max_chars=0 비교, 로직 결함 아님) |
> | A2 게이트 동등성 | ✅ 5케이스 임베디드 vs core 일치 |
> | A4 /v1/tools 세션 | ✅ on_session_switch(reset=False) 리바인딩 + hermes_ 접두 정규화, 라이브 실측 PASS |
> | A5 spawn 스로틀 | ✅ 쿨다운 30s + in-flight 플래그 (좀비 3개 정리 실측) |
> | D-2 전용 venv | ✅ `%LOCALAPPDATA%\jev-mem\venv` 구축, client가 우선 사용, 전 기능 실측 PASS |
> | D-3 저장 redaction | ✅ `redact_text_high_precision` (형식 기반 고정밀), 기본 ON, `JEV_MEM_STORE_REDACT=0` 토글 |
> | D-5 idle shutdown | ✅ 기본 60분, 3조건(비활동+큐+백로그) 모두 충족 시 graceful 종료 |
> | F8 DB 정체성 | ✅ 기동 시 DB 부재 거부(exit 4, `--init-db` 오버라이드) + core_meta 기록 + 경로/행수 변화 거부(`--accept-db-change`) |
> | F11 fail-open 표식 | ✅ `gate: fail_open:<reason>` 메타 + `/v1/status` degraded/degraded_reasons/gate_fail_open_total |
> | F12 생존성 | ✅ 부모 종료 후 데몬 생존 실측 PASS |
> | F14 내구성 | ✅ mnemosyne.db `synchronous=FULL` (ledger와 정합) |
> | F15 doctor | ✅ `experiments/jev_mem_doctor.py` — 6영역 15체크 |
> | F17 동시성 | ✅ Jev live 조건 명시: 4클라이언트×10, p50=276ms/p95=453ms (목표 <800ms) |
>
> **잔여**: F16(검토 브리프 번호 정정 — 다음 외부 검토 시 반영), 장기 관측(§8.5).

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
- [x] **★ Hermes 종속성 독립화 (P1 일부)** — `core/j1_engine.py` 분리 완료 (hermes_j1은 얇은 어댑터로), smoke 7/7 + verify_core_j1_engine.py live DB PASS, 커밋 `140fa46`
- [x] **★ 8차 400자 A + full-text 게이트 결합 (2026-10-04, 커밋 82cd674)** — **400자 excerpt choice + full-text 게이트(≤800자) + R2(θ=0.5)**. 실측: op hit@3 **88.9%** (+8.9pp over 100자 A), noans FP **16.0%** (게이트 없이 28% → 적용 후 16%). **수동 3분류 판정 + 맹검 재판정(kappa 0.778)**: LGO 37건 중 32건(86.5%)이 VALID(대체 증거) — gate YES 100% 정밀도. 상세: `docs/review/2026-10-04_8차-*.md`, `7차-3분류-판정결과.md`. **⏸️ 2026-10-06 기준: 이 400자/게이트 실측은 op/noans 실험 셋의 판정 구조이고, 라이브 rerank excerpt는 win-300(150 excerpt) + abstain_p soft gate로 운영 중 — 두 구조의 관계는 enforcement(shadow) 판정에서 확인.**
- [x] **★ Shadow 모니터링 구축 (2026-10-04, 커밋 fa451b6+bff76fc)** — Hermes cron 10분 배치(`jev_shadow_batch.py` → `shadow_batch.py`: query_log 신규 쿼리 → 400자 choice → full-text 게이트 → R2(θ=0.5) → shadow_log) + 매일 09:00 텔레그램 요약 cron(`jev_shadow_daily_summary.py`). **별도 데몬 없음** (Hermes cron이 실행). **판정(enforcement)**은 3~5일 shadow 축적 후: gate YES/NO/ABSTAIN 분포 + A vs R2 갈림률.
- [x] **★ shadow_batch source 마킹 버그 수정 (2026-10-05, 커밋 839362f)** — `for r in rows: r = dict(r); r["source"]="query_log"` + `rows=[dict(r)...]`가 **둘 다 무효** (로컬 복사본에만 source 주입, rows 미반영) → shadow_log에 source=NULL(`'?'`) 기록 + 마킹 조건 `rows[0].get("source")=="query_log"` **항상 False** → query_log shadow_marked=0 영구 유지 → **배치가 매 실행마다 같은 쿼리 반복 처리, 중복 685건 축적**(고유 20건뿐, enforcement용 shadow_log 오염). **수정**: `rows = [dict(r) | {"source": "query_log"} for r in rows]` 병합. **정리**: `source='?'` 685건 중 고유 20건만 보존(665 DELETE, 백업 `experiments/operational-golden/shadow_log_dedup_backup.json`). **검증**: 수동 실행 후 marked=1 20건 + cron 12:17 후 marked=40건·source='query_log' 60건·신규 쿼리만 기록 — 정상. 현재 shadow_log: query_log 60 + op-snapshot 90 + '?' 20(고유분). **마킹 상태 확인**: `SELECT shadow_marked, COUNT(*) FROM query_log GROUP BY shadow_marked` (marked=1이 늘어나는지).
- [x] **★ 데몬 typesafe→EXPERLABS 전환 (2026-10-04, 커밋 c4c61d9 + 3f3aa6f)** — 데몬이 `api.typesafe.ai 401`을 내던 2중 버그 수정: ① `_spawn_core()`가 HKCU에서 EXPLABS 키 주입 (Hermes env에 없어도) ② `_jev_choice()`가 `client._jev_api` 우선 (env JEV_API_URL 부재 시 typesafe 고정 버그). **SmartRotator 키 로테이션** (EXPLABS→EXPLABS2, 429 시 전환, 무료 소진 키는 **다음 정각(HH:00)까지** 제외 후 자동 복귀). 실측: `api.experientiallabs.ai 200 OK + idx 선택` 성공. **데몬 재시작 후** query_log 0건→활성화 (버그: `w.state.conn`→`w.state`).
- [x] **★ 메모리 중단 14시간 발견·복구 (2026-10-05, 커밋 5d9a0a1)** — "no provider instance found" 원인: **18:41 Hermes PM 재설치로 새 런타임 venv(099e00, Py3.14)에 mnemosyne-hermes 누락** → `uv pip install --python <런타임 venv> mnemosyne-hermes==0.7.0` + 데스크톱 재시작으로 복구 ("jev-mem activated" 재개). **중단 기간**: 10-04 **10:09**(첫 prefetch 8s 타임아웃 → stuck-call 스킵 상태 진입) ~ 00:11(복구). 10:09~18:41은 데몬 연결, 18:41~00:11은 패키지 누락. ★**Hermes PM 재설치 시 런타임 venv(installs/.../environments/*/venv)에 mnemosyne-hermes가 빠질 수 있음 — 재설치/업데이트 후 `hermes memory status`가 "plugin NOT installed"이면 이 경로부터 확인**.
- [x] **★ 세션 메모리 사후 재주입 backfill (2026-10-05, 커밋 58e59fd)** — 중단 구간 대화를 **평소와 동일한 게이트 판정**으로 저장. 원본: 전역 `state.db`(516MB, sessions 953/messages 106,042)의 `session_id='20261004_225351_7c8fa4'` — **메시지 원본은 여기 저장됨 (state/state.db 아님 — 빈 파일)**. 61건 추출(user 30/assistant 31, **turn-final만** — Hermes 평소 동작과 동일) → G-qual/G-AS 실 JEV 판정 KEEP 43/SKIP 18 → 저장 31건(12건 beam.remember content dedupe). **`metadata_json.source_timestamp`**(원발화 시각) + `backfilled_at`(재주입 시각) — content는 원문 유지(recall/게이트/분류 무영향). **`source_timestamp`는 backfilled_at 있을 때만 의미** (평소 저장은 timestamp≈발화 시각이라 생략). 도구: `experiments/operational-golden/backfill_session_memories.py` (state.db timestamp는 epoch float — ISO 변환 필요). recall 검증: prefetch 4쿼리 회수 + Jev lift 정상.
- [~] **★ abstain 조기 기권 아쉬움 — 일부 해소 (2026-10-06, excerpt 전면 + soft gate)** — 원 사례: "아까 할 일이 shadow 비교만 남았었나?" → pool 88/게이트 31 구성 성공 → **Jev abstain** → 빈 컨텍스트. 검색 성공·의미 판정 기권 문제. **2026-10-06 처리**: ① excerpt 전면 300자(작은 메모리에서 답 절단 → abstain 유발 요인 제거) ② `_jev_choice`가 probabilities 파기하던 것 수정 → **abstain_p soft gate**(>0.3이면 빈 컨텍스트)로 "확신 없는 abstain"의 noans 오주입을 막으면서 gold는 살림. **잔여**: "답이 pool에 없는데 abstain"인 경우(gold pool 밖 abstain)는 여전히 빈 컨텍스트 — 이건 JEV의 정직한 판정(정답 없음)이며, 사용자 관점의 "특징적 키워드인데 아무것도 안 줌"은 **enforcement 판정(shadow 3~5일 축적) 때 abstain 분포와 함께 재논의** 예정(2026-10-05 합의 유지). 개선 후보 3종(①②③)은 그때 재검토.
- [x] **★ 멀티 에이전트 전환 (Core-as-Writer) — 2026-09-29 P5 완료 (전체 완료)** — `docs/design/p1-core-server-report.md` (P1) + `docs/design/p2-spool-breaker-report.md` (P2) + `docs/design/p3-pi-extension-report.md` (P3) + `docs/design/p4-codex-opencode-report.md` (P4) + `docs/design/p5-hermes-rpc-report.md` (P5). **P5 완료**: Hermes rpc 전환(JevRpcProvider 기본, embedded 롤백), mnemosyne_* 툴 `/v1/tools` 프록시(단일 writer 직렬화), core DB → Hermes 실 DB 전환, 세션 접두사 `hermes_<sid>` 규칙 유지. 검증: §16.2 동시성 7/7 (1760 요청, 0 BUSY, p95 508ms), RPC 8/8+롤백 3/3, 전 회귀(smoke/P1/P2 chaos/redact) ALL, **재시작 후 라이브 실측** (activated, prefetch 200, turns.stored→실DB, tools 200, 행수 967→969). 커밋 `d2f6a05`. 잔여: ~~core 데몬 부팅 자동화~~ → **해소: on-demand 기동 확정** (client auto-start 수정 `2c1845e`+`46e24cc` — 첫 에이전트 요청 시 pythonw 무창 기동, 부팅 상주 불필요; 2026-09-29 사용자 확정), `/v1/tools` remember류 세션 스코프 확인

**★ 임베딩 모델 교체 벤치마크 S3 완료 + bekko-a8m 채택 확정 (2026-10-01)**
- 배경: baseline(mmBERT? → E5 계열) RAM 948MB 과다 → 경량 후보 `koen`(한·영 프루닝), `bekko-a8m`(100+ 언어, 7.7M), `bekko-a25m`(24.9M), granite(fp16 동적/정적 quint8) 전수 평가.
- 실측 요약 (`docs/design/embed-benchmark-final-report.md`, 스크립트/결과: `%LOCALAPPDATA%/jev-mem/bench/run-20260930/cand/`):
  - **bekko-a8m**: 내부 gold-50 MRR 0.772(1위), RAM commit 617MB(-35%), p95 1.5ms, X2 다국어 vec 5/5 통과. 조건: 배치 4+클램프 512 필수.
  - **koen**: 외부 KoDialogBench(X1) Acc@1 0.622로 1위이나, **CJK(일본어·중국어) vec 붕괴(X2 0/1)** — 한·영 전용 프루닝의 직접 결과. 하이브리드(BM25 vw=0.3)로 이 조건에서 복구되지만 대규모 코퍼스·의미적 유추 질의에선 보장 없음.
  - **bekko-a25m**: gold MRR 0.501 + 배치 2+ OOM(4.29GB) + G5 드리프트 93% → 탈락 확정.
  - **granite**: 정적 quint8 배치 4에서도 50.8GB 버퍼 OOM → 운영 불가 확정.
- **최종 판정: bekko-a8m 채택** (다국어 배포 조건 + RAM + 지연 종합). 하이브리드 vec_weight 0.3 권장.
- **X3 외부 데이터셋 확장 검증 완료 (2026-10-01)**: a8m vs baseline 실측 — koalpaca 0.980 vs 0.788, 기계독해 **1.000 vs 0.370**, kosgd 0.086 vs 0.052, kodialogbench(baseline 근소 우위 0.585 vs 0.560, X1 방향 재현). RAM a8m 615MB(-35%)/WS 285MB(-53%), 처리량 94 vs 40건/s. **운영 도메인(문서·지시문 회수)에선 a8m 압도적 우위 → S4 채택 재확인.** 상세: `embed-benchmark-final-report.md` §8b.
- 남은 일: ~~S4 마이그레이션~~ → **완료 (2026-10-01 라이브 컷오버)**: `docs/design/s4-live-cutover-report-20261001.md` (commit `c19e2ea`). 최종 상태: `bench/bekko-a8m` 100% 단일 모델 (1,153행, orphan 0, integrity ok). 라이브 reindex 37.3s / fixup 54.7s → maintenance window 2분 이내 확정. 사건: 데몬 warmup 실패 시 fallback MiniLM 조용히 서빙 → 1행 오염 발견·복구. 모델 고정: jev-mem venv `sitecustomize.py` (커스텀 등록+clamp512+cache_dir 강제 주입) + 데몬 env `MNEMOSYNE_EMBEDDING_MODEL`/`MNEMOSYNE_FASTEMBED_CACHE_DIR` 필수. `bench/bekko-a8m`은 fastembed 커스텀 별칭 — 원본 `hotchpotch/bekko-embedding-v1-a8m` (별칭↔원본 매핑은 sitecustomize.py, DB 이관 시 함께 가야 함). 백업 `s4-pre-migration-20261001-154527.db` 2026-10-08 검증 후 삭제 권고.
- **~~P1 잔여~~ → 완료 (2026-10-01, commit 예정)**: `/v1/status`에 `embedding: {model, dim, warmup_ok, warmup_error}` 노출 + warmup 실패 시 **기본 fail-fast(exit 9)** (`JEV_MEM_EMBED_WARMUP=warn`으로 경고 전환 가능) + degraded_reasons `embedding_warmup_failed` + watchdog 가짜 lag 경고 수정(틱 간격이 아닌 sleep 초과분 측정). **sitecustomize.py가 `MNEMOSYNE_EMBEDDING_MODEL`/`MNEMOSYNE_FASTEMBED_CACHE_DIR`을 무조건 강제** — 부모 env(raw 명) 상속으로 인한 warmup 실패 재발 구조적 차단. 검증: `experiments/verify_p1_embed_status.py` 11/11 + `verify_watchdog_regression.py` PASS + `verify_p1_core.py` ALL PASS.

**★ PerfectRecall 대비 검증 + 운영 골든셋 최적화 사이클 완료 (2026-10-01) — R3~R5 + Run G~N**

> PR(`arslanr-com/perfectrecall`) 대비 격차 규명(R3~R5, 외부 AI 3종 3회 검토)과
> 운영 골든셋(45 gold × 2축 = 90쿼리 + 무답 10) 기반 파이프라인 최적화가 **모두 종결**된 상태.
> SoT: `docs/design/perfectrecall-review-r5-final-20261001.md` (부록 1·2 포함, `15fb90a`).

| 항목 | 결과 | 커밋 |
|---|---|---|
| R5 격차 규명 | 0.556 vs 0.806 격차 = **평가 조건 차이**(55-way vs 5-way) — 시스템 품질 차이 아님 | `b9ced71` |
| P0 게이트 완화 | 어휘 게이트 `(2, 0.30)`→`(1, 0.0)` (strict 게이트가 vec 기반 정답 38% 사살) | `c3aee3a` |
| union vs RRF | 180쿼리 전수 실측 **정확한 동률** (0.5556 vs 0.5556) → RRF 유지 | `f5d7441` |
| **vec-rank 커버리지 예외** | `VEC_RANK_EXEMPT=2` (vec_rank≤2 ∧ overlap≥1 → 게이트 탈락 무시). 라이브: Pool Recall 82.2→**90.0%**, Acc@1 75.6→**83.3%**, hit@5 81.1→**88.9%**, 이탈 0 → **운영 반영 완료** | `ac2c608` |
| Run K excerpt 200 | Acc@1 84.4% (+1.1%p) but JEV 토큰 **+50%** → **기각** (120 유지, `JEV_EXCERPT_LIMIT` env 추기 스위치 유지) | `a0bd5f9` |
| Run L PR full-scan | 운영 골든셋에서 Acc@1 **52.2% vs 83.3%** — 군집 코퍼스에서 rank2 밀림(31%) → **기각** | `275cd03` |
| Run M 탈락 해부 | 탈락 9건 = 완전 의역 3(overlap=0) + 깊은 vec 순위 5 + 레인 부재 1. 예외 ≤20 확장도 회복 4/9 → **vec-rank 예외 레버 소진** | `159908d` |
| Run N 어간 정규화 | 회복 **0건**, 90.0→82.2% 순손실 — **음절 단위 토큰화가 이미 pseudo-stemming 역할** → **기각** | `ca69db4` |
| **Run O abstain** | **무답 오주입 10/10 → 0/10 (완전 해결), gold 59/59 보존, wrong→none 17/17 정화, 토큰 +1.0% → 채택·라이브 적용** (`JEV_ABSTAIN`, abstain 라벨 c<N>, abstained=True → 빈 context) | `556615922209` |

**★ fail-open 장애 복구 파이프라인 완성 (2026-10-03) — P1/P2a/P2b/P3a 전체**

> JEV API 장애(402/403) 기간 fail-open KEEP으로 저장된 메모리를 식별→격리→재판정하는 파이프라인.
> 상세 문서: `docs/review/2026-10-03_failopen_{P1,P2a,P2b,P3a}_완료.md` + `2026-10-03_failopen_P3_설계안.md` (외부 AI 3종 검토 종합).

| 단계 | 내용 | 상태 |
|---|---|---|
| P1 | 장애 기간 저장분 식별·태깅(`fail_open:*`) + 재판정 (49 keep / 15 skip archived) | ✅ |
| P2a | fail-open 불변식 반전(allowlist 폐기 → NORMAL_REASONS 밖 전부 fail_open) + failure_class(billing/auth/transient) + `/v1/status` human_alert | ✅ |
| P2b | 상태 머신 6→11 확장(fail_open_quarantine/rejudge_*) + gate_outage 테이블 + rename-swap 마이그레이션 | ✅ |
| P3a | core 내부 자동 재판정 worker — 회복 감지(실호출 streak 3회) + lease + half-open 브레이커 연동 + op_loop 마이크로 배치. **실데이터 잔여 26건 소진(20 keep/6 skip), pending 0** | ✅ |

- P3a 검증: `tools/jed_failopen_p3a_verify.py` 20/20 · `tools/jed_failopen_p3a_syncpath_verify.py` 7/7 (InvalidStateError 회귀) · `tools/jed_failopen_p3a_live_verify.py` 실통합 (실 JEV 호출)
- **라이브 버그 3건 발견·수정**: ① HTTP 실패-응답 skip 오분류 → 예외 승격 ② quarantine 재처리 무한루프 → `NOT LIKE '%rejudged%'` 필터 ③ `writer.submit()` wrap_future vs `.result()` 불일치 → `submit_sync()` (raw Future) 신설 + sync 호출부 6곳 전환 + `_note_recovery`/op_loop `asyncio.to_thread` 경유
- 자동 재판정 비활성 스위치: `JEV_AUTO_REJUDGE=0` (수동 도구만). 재판정은 KEEP 자동 승격만, SKIP은 staged(`rejudged:skip` + archived + valid_until)까지 — 수동 승인 불변식 유지

**★ archived(skip) recall 누출 수정 (2026-10-03 후속, 커밋 f5aa4ef)** — 재판정 skip 행 24건이 live recall에서 실제로 제외되지 않던 2중 결함:
- **결함 A**: P3 `recover.py`·`rejudge_v2.py`가 skip 시 `valid_until`을 metadata에만 쓰고 **컬럼 누락** → recall 필터(컬럼 기준: `valid_until IS NULL OR valid_until > ?`) 무력. P1 apply는 정상이었고 P3 경로만 누락. → writer 수정 + 24건 백필(컬럼 NULL 0 확인)
- **결함 B**: 컬럼을 채워도 **FTS/imp/graph lane + hydration에 temporal 필터 없음**(vec lane만 보유) → archived 행이 FTS 경유로 pool 재유입(실측: '좋아 진행해줘' pool 3건). → hydration(`j1_engine.hydration_get`·`backends.get_hydrated` — pool 단일 choke point) + `_imp_search`·`_graph_lane_search`에 `superseded_by IS NULL AND (valid_until IS NULL OR valid_until > ?)` 강제
- 검증: 신규 `tools/jed_failopen_archived_recall_regress.py` (수정 전 24/24 누출 FAIL → 후 8/8 PASS) + 라이브 E2E(`/v1/prefetch` pool_ids archived 0, JEV 200 OK) + p3a 20/20·syncpath 7/7 회귀
- 상세: `docs/review/2026-10-03_failopen_archived_recall_누출_수정완료.md`. **미결**: rejudged 마커 포맷 2종(태그형/JSON형) 신규 기록부 단일화 → **완료 (2026-10-03, 커밋 82f87bd)** 아래 참조

**★ rejudged 마커 canonical 통일 + gate 원본 복원 (2026-10-03, 커밋 82f87bd)** — 외부 AI 3종 검토(a/b/c) 종합 반영:
- 백필 96행: gate 원본 복원(스냅샷 체인 P1 13:10:28 + 403 13:32:31, 96/96 커버, 402:40 / 403:56) + canonical(`gate`=원인 불변 · `rejudged`=결과 + `rejudged_at`+`rejudged_at_source`). rejudged_at은 `rejudge_verdicts`(32) + P1 dry-run `run_at`(64) — 스냅샷 fallback 미사용. valid_until 컬럼 전 행 불변. 부수 결함(archived 2건 누락) 보충
- 신규 기록부: `jev_mem_core/rejudge_markers.py` 공용 헬퍼(`apply_rejudge_patch`) — gate 불변·mutation 후 직렬화·metadata_json만 UPDATE. `recover.py`·`rejudge_v2.py` 이식. `server.py` pending predicate 공용 상수화
- 레거시 tag-format writer(`403_apply.py`·`p1_apply.py`) → `tools/legacy/` 이동 + Exit Guard
- 검증: markers_verify 22/22 · backfill post-verify PASS · recall regress(레거시 0건 포함) · p3a 20/20 · syncpath 7/7 · 라이브 `/v1/status` skip_staged=24 pending=0
- **잔여(별도 승인 후)**: `rejudge_verdicts` P1 64건 백필(감사 SoT 정합 — recall/동작 무영향) → **완료 (2026-10-03)**: `tools/jed_failopen_verdicts_backfill.py` — dry-run JSON에서 verdict/reason/latency_ms + 판정 시각(`run_at`)으로 64건 INSERT(사전검증 0 중복·0 불일치, 사후검증 96건 전수 대조 0 불일치, 멱등성 가드 확인). 상세: `docs/review/2026-10-03_failopen_마커포맷_통일_완료.md`

- **최종 확정**: Pool Recall 90.0%는 현 구조의 사실상 상한. 커버리지 변수는 게이트 자체뿐
  (`min_coverage`/`min_distinctive`/vec-rank 예외) — POOL_BUDGET(40)/LANE_VEC_BUDGET(60)은
  컷오프라 커버리지와 무관(Run M에서 "게이트 통과 후 순위 밀림" 0건 확인).
- **운영 지표 최종** (n=90 gold + 무답 10, JEV 실호출): Pool Recall **90.0%**, Acc@1 **83.3%**,
  hit@5 **88.9%**, MRR 0.946, p95 336ms.
- **운영 최적화 사이클 종결**: 남은 개선 경로는 임베딩 모델 교체(의역 강화)뿐이며,
  X1 실측상 a8m 운영 도메인 유효성 확인됨 → 교체 근거 현재 없음.
- Run 상세: `experiments/operational-golden/GOLDEN_RUN{1,2,3_GATE_EXCEPTION,K,L,M,N}*.md` +
  `FREELEVER_REPORT.md`. 평가 스크립트: `scratch/perfectrecall/` (골든셋 `golden_final_v2.json`).
- **pitfall**: 운영 전체 코퍼스 테스트 시 `jev_recall.visible_memories`는 `cross_session=False`
  기본 → `_filters(cross_session=True)` 필수. `build_lane_pool`의 recall_raw는 `(kind, arg, k)`
  3인자이며 **"get" hydration 핸들러 누락 시 pool이 조용히 0이 됨**.

**★ Avinash-jetwani/jevmem(npm CLI) 검토 — fit/audit 실측 종결 (2026-10-05, 커밋 3e1c7ee·42e3c32·5a09a44)**

> 이름만 유사한 별개 프로젝트(학술 Jev-Mem arXiv 2609.23986과도 별개). 7차 "배울 점 → 실측 → 사람 판정 → 채택/기각" 프레임으로 검토 종결.

| 제안 | 실측 | 판정 |
|---|---|---|
| fit (라벨 기반 threshold 튜닝) | gold50 5-fold 헬드아웃: COMMITMENT conf τ=0.65는 full-data FP 10→7이지만 **유실 0 유지 0/10** (gold50에 conf<0.65인 KEEP 2건 — goal 0.62/commitment 0.69 — 이 어떤 폴드에서도 유실 유발) | ❌ **기각** — '유실 0 + FP 절감' 구조적 동시 불가. 자동 약한 라벨도 부재(α supersede 111/113이 외부 에이전트 자동주입, β 교정발화 1건) |
| 자동 약한 라벨 (fit용) | α supersede 113건 중 111건 `[opencode/codex session]` 자동주입, β 교정발화 trace 1건 | ❌ 부재 — fit은 사람 라벨 시트 의존 구조만 가능 |
| audit T1 (0콜 결정적 검증) | env/url/model/port/db 키워드 155/1,584행 검증, **결정적 stale 1건**(port 48000) | ✅ 유효 — 오판 불가, 밀도 낮아 주기 점검 용도로만. **shadow enforcement 판정 후 채택 재검토(보류)** |
| audit T2 (의미적 모순 스윕 1콜/행) | 전체 1,589행 스캔(=약 $0.06) STALE 119건(7.5%), 사람 판정(prob 상위 20) **precision 5%** (REAL 1 / PAST 16 / STILL_TRUE 3) | ❌ **기각** — noul이 '과거 행위 보고'를 stale로 오판(에피소드 기록과 질문 설계 부정합), STILL_TRUE 15%는 유실 사고 위험 |

- **fit/audit T2는 재실험 금지**(do not re-run). 도구: `experiments/operational-golden/run_fit_gold50_{sweep,holdout}.py`·`probe_weak_labels.py`·`run_audit_tier{1,2}_probe.py`·`run_audit_tier2_full.py`·`build_stale_review_html.py`
- 상세: `docs/review/2026-10-05_fit-audit-실측-결과.md` + `2026-10-05_audit-stale-사람판정-기각.md`
- **부수 수확(운영)**: ① 대량 배치(free 레인) 안전값 = **병렬 2 + 60s 드레인 + 429 연속 20회 자동 종료(체크포인트 재개)** — 병렬 3은 429 폭주로 3회 hang 실측. ThreadPoolExecutor `shutdown(wait=False)` + 체크포인트 저장 후 `os._exit(0)`(non-daemon 워커 종료 방지) ② systemone candidates는 `{"id":"t<i>","label":...}` + `criteria` 필수(`choices` → 400) ③ JEV 직접 호출은 jev-mem venv python(httpx) 필수
- **추후 검토(보류)**: audit T1 주기 점검(0콜)은 shadow enforcement(3~5일 축적) 판정 **완료 후** 재검토. 에피소드 기록은 stale 감사 대상 제외, 사실/설정/선호만 대상으로 하는 설계 원칙도 그때 함께 검토.

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
| 키 | `EXPLABS_API_KEY` + `EXPLABS_API_KEY2` (HKCU\Environment) — 2026-10-04부터 데몬/게이트 모두 이 우선, `TYPESAFE_API_KEY` 최후 폴백 |
| 런타임 venv | `C:\Users\mandu\AppData\Local\hermes\installs\315db7b763fb0d0a\environments\746564964b1042b79add42260378503b\venv\` |
| Jev API | `https://api.experientiallabs.ai/v1/systemone` (EXPLABS 키 존재 시), model `jev-latest`, 무료 레인 자동 우선 (cost=0.0) |
| 스냅샷 | `data/snapshots/snap-20260927.db` (실험용, 프로덕션 DB와 분리) |
| 평가셋 | `data/dataset_curated.json` (52쿼리, 6유형, gold 16자리 ID) |
| 로그 | `C:\Users\mandu\AppData\Local\hermes\logs\agent.log` (`grep "Jev choice"`) |
| **Jev trace 로그** | `C:\Users\mandu\AppData\Local\hermes\logs\jev_trace.log` (ring buffer 512KB, `JEV_TRACE_PATH`로 경로 변경 가능) |
| **쓰기 게이트** | `JEV_WRITE_GATE=0` → 비활성(KEEP). **KEEP/SKIP 모두** `jev_trace.log`에 `write-gate`(user) / `write-gate-as`(assistant) 기록 (2026-09-29 B: unconditional, `keep=keep`/`keep=skip`) |

## 10. 세션 전환 방법

- **새 세션**: Hermes desktop에서 `/new` → 이 핸드오프 문서를 참조해 "다음 단계" 중 하나 요청
- session_search로 과거 진행 복구 가능: 세션 ID `20260927_170219_d102fe` (Phase 1), `20260927_183939_2d9e83` (런타임 디버깅)