# 외부 시스템 검토: agentmemory (rohitg00/agentmemory)

- 날짜: 2026-10-09
- 대상: https://github.com/rohitg00/agentmemory (main @ df3d4a8, TypeScript/Node, iii-engine 기반)
- 방식: GitHub tree API(851 파일) → 핵심 54개 파일 raw fetch → 소스 대조 (git clone·설치 없음, 0콜)
- 판정 요약: **직접 반영 없음 / 설계 정합 2건 / 보류 등록 4건 (선행 0콜 실측 조건)**

> ⚠️ 사전 명시: 본 프로젝트('jev-mem')와 학술 'Jev-Mem'(arXiv 2609.23986)은 이름만 유사한 별개 프로젝트다. 이 검토는 외부 시스템 **agentmemory**와 우리 jev-mem의 비교이며, 학술 Jev-Mem과 무관하다.

---

## 1. 대상 요약

`#1 Persistent memory for AI coding agents` 표방. 코딩 에이전트(Claude Code/Copilot/Cursor/Codex/Hermes/pi 등 20개)의 lifecycle hook(12종)에서 원시 관측(raw observation)을 캡처 → LLM 또는 **synthetic(0-LLM) 압축** → 관측/메모리/그래프/슬롯 4계층 → BM25(자체 역색인, stemmer+CJK 세그멘터+동의어)+vector+graph **3-stream RRF** → 선택적 cross-encoder rerank(ms-marco, 로컬 q8). keyless 모드(벡터 비활성, BM25만) 지원. 저장소 구조: `src/state`(검색·인덱스), `src/functions`(기억 수명주기), `plugin/hooks`, `benchmark`(LongMemEval-S retrieval 95.2% 자체 측정).

벤치 수치(95.2% R@5 등)는 **자체 보고 + 모델 고정(all-MiniLM-L6-v2, retrieval-only)** — 우리 실측과 분리 표기.

## 2. 우리 대비 축 표

| 축 | agentmemory | jev-mem (현행) | 판정 |
|---|---|---|---|
| 후보 풀 구성 | BM25 + vec + graph 3-stream RRF k=60, 가중 0.4/0.6/0.3 + agreement bonus + | FTS + vec + imp + graph lane RRF **k=30** (grep `RRF_K = 30`) | ⏸️ 보류 (k 30↔60) |
| rerank | cross-encoder(ms-marco-MiniLM-L6, 로컬) top-20 재정렬, `RERANK_ENABLED` | JEV choice(LLM 판정)로 pick/abstain | — (구조 상이) |
| 재정렬 후처리 | min-rank tie-break + **세션당 diversification(max 3)** | `_adjusted = score·0.65 + signal·0.35 + import·0.05` (stage50c 실측: 8~9위 강등 사례) | ✋ 겹침·후순위 |
| retrieval fallback | BM25-only (keyless) | RRF (FTS+vec) — lane 단독 폴백은 stage50c로 **기각** | ❌ 기각 |
| 캡처 압축 | 0-LLM **synthetic 압축** 기본(`AGENTMEMORY_AUTO_COMPRESS` 옵트인) | G-qual/G-AS 게이트 + JEV | —
| 모순/중복 처리 | Jaccard 유사도 >0.9 → **자동 supersede** (auto-forget) | supersede (113행) + valid_until (159행) | ✋ 겹침 (임계 라벨링 필요) |
| 지식 갱신 전파 | **cascade-update**: supersede → 그래프 노드/엣지 stale 마킹 | 그래프 lane 없음(imp lane만), corrected_by 0건 | 🔵 신규 후보 |
| 쿼리 확장 | **LLM reformulation 3-5개 + temporal concretization + entity 추출** → 다중 RRF 병합 | stage18 기각 (쿼리 확장 = 오염 단어 주입) + AnchorMind 합성 역질의 보류 | ❌ 기각(우리 실측) |
| CJK 검색 | 스크립트 분기(한/중/일) + 자체 세그멘터 | FTS unicode61 공백 분리 (한국어 형태소는 stage103 기각) | ✋ 참고 (경량 개선 여지) |
| 동의어 | 43개 코딩 동의어 그룹, BM25 가중 0.7 | 없음 | 🔵 신규 후보 |
| 자동 망각 | TTL(forgetAfter)·저중요도(180d)&lt;=2·Jaccard 모순·retention 점수 | read-time valid_until 필터 | ✋ 설계 동일 취지 |
| retention | `salience·e^{-λt} + access 강화`(λ=0.01, σ=0.3), hot/warm/cold 티어 | 없음 (stage57~66 규칙 도배 캡 기각) | 🔵 신규 후보 (코퍼스 상한 회귀 전제) |
| 액세스 로그 | `mem:access` count + 최근 타임스탬프 → retention·강화 | 없음 | 🔵 신규 후보 |
| 작업 지시 메모리 | **slots (persona/user_preferences/tool_guidelines/project_context/guidance/pending_items 등 pin 1~3k자)** — `renderPinnedContext`로 프롬프트 주입 | stage96 실측: abstain 91%가 작업 지시 오판 → τ로 미해결 | 🔵 신규 후보 (전용 솔루션) |
| 프라이버시 | 저장 전 stripPrivateData (시크릿 제거) | 없음 (메모리 원문 저장) | 🔵 신규 후보 |
| 감사 | 모든 변이 recordAudit (삭제 이유·before/after) | trace 로그 + canary | ✋ 일부 겹침 |
| 지식 그래프 | LLM 추출 + 시간 유효성(tvalid/tvalidEnd) + 버전 | 그래프 lane은 수동 | — (비교 생략) |

## 3. 개별 사안 판정 (기각/보류/정합 각각 근거)

### 3.1 설계 정합 확인 (변경 없음) — 2건

1. **RRF 상수**: agentmemory `RRF_K = 60` (BM25+vec+graph). 우리 RRF_K=30. **정합 판정**: RRF 계열·상수 30~60 범위 사용은 우리 설계 표준성 지지 (Honcho k=60 정합과 동일 부류).
2. **'타인 발언 사실 추론 금지' 동등 규칙**: agentmemory는 관측 origin(channel: user/tool/agent)을 캡처에 기록해 출처를 구분. 우리 G-qual 사용자 발언 대상·stage86 생산 B와 취지 동일.

### 3.2 기각 (우리 실측과 충돌) — 3건

1. **LLM 쿼리 확장(3-5 reformulation + multi-RRF)**: 우리 stage18에서 쿼리 확장 = **오염 단어 주입**으로 기각, AnchorMind 합성 역질의(구제 0/4)도 보류. 지시문이 아무리 정교해도 라이브 트래픽(기능/원인/설정 질문)엔 확장 여지가 적고, 실측된 retrieval miss 원인(의역/한영 단절)은 reformulation으로 연결 불가능. **do not re-run.**
2. **BM25-only fallback 강조**: 우리 stage50c/d에서 lane 단독 순위 1~2위가 RRF 병합 후 밀리는 '답 강등'이 실측됐지만, lane 폴백은 시점 필터 제거 후 15/18이 rank 1~3으로 회복(특수성) — 단일 lane만 쓰는 설계는 우리가 이미 기각한 방향. 단 우리 `_adjusted` 재정렬(0.65/0.35/0.05)의 강등 사례(exp8a)와 **min-rank tie-break 아이디어는 아래 보류 1**로 등록.
3. **'중요도 5 미만 관측은 consolidate 제외' (agentmemory는 importance>=5만 메모리 승격)**: 우리 stage57~66 실측에서 규칙/프로필 행이 importance 0.05 가중이어도 90쿼리 중 81~99% top5 진입 — **중요도 컷은 도배 행을 못 막고 정답 유실만 만든다** (캡이 유일한 효과 레버, 그마저 stage86 기각). 중요도 기반 승격 게이트 재실험 금지.

### 3.3 보류 등록 — 4건 (선행 0콜 실측 전 채택 금지)

1. **`_adjusted` 강등 방지: min-rank tie-break + 세션 diversification(maxPerSession=3)** — 우리 실측(exp8a: gold가 score 0.65+signal 0.35 재정렬로 8~9위 강등, stage50c와 동일 패턴)의 후처리 해법 후보. **선행 조건**: ① 중요도·signal 재정렬을 제거/완화한 변형의 production-exact 회귀(정답군 90 + noans 50, rank>20 gold 유지 확인) ② 최근 raw에서 강등 건수 실측(0콜). **주의**: diverisify는 우리 stage66 캡1과 같은 '노출 구성 변경'이라 op·라이브·noans 세 셋 동일 세션 측정 필수.
2. **자동 supersede(Jaccard >0.9)** — 현재 모순 갱신은 G-qual이 새 행을 만들고 superseded_by는 113행 사용 중이지만, **우회 경로**(같은 규칙이 '버전 2'로 중복 저장) 유병률 미실측. **선행 조건**: supersede로 못 잡은 모순쌍 유병률 사람 라벨링 (Honcho 자동 모순 감지 보류와 동일 선행, 0-콜).
3. **retention 점수(`salience·e^{-λt}` + access 강화) + hot/warm/cold tier eviction, 액세스 로그** — 2,085행 코퍼스에서 importance 분포가 0.15(728)·0.5(1127)로 양극화라 Ebbinghaus 곡선이 실질 레버인지 미검증. **선행 조건**: live rank>20 gold 유지 3-run 회귀 + 유병률 실측 (pool20 기각과 동일 전제). λ·σ 기본값(0.01/0.3)은 코드 복사 금지 — 우리 데이터로 재튜닝.
4. **pinned slots (작업 지시·선호·툴 가이드라인 전용 저장소) + LLM 쿼리 확장과 분리된 'slot-reflect' 자동 적재** — stage96 실측 'abstain 91% = 작업 지시 오판'과 stage93/94 'k=2 노출 보류'는 **작업 지시 계열이 일반 사실 메모리와 한 풀에 섞여 문제가 되는 것**이라는 해석 가능 → 분리 저장소가 최종 후보. **선행 조건**: ① 우리 2,085행 중 작업 지시/규칙/선호 행 유병률 실측 ② canary L2용 홀드아웃(작업지시/과다거부/정직거부 라벨)에 대한 재현 확인 ③ 이식은 read-path 최상단 주입이라 **소비 측 변경 = 사용자 승인 영역** (프레이밍 실험과 동일 파이프라인).

### 3.4 참고 (채택 후보 아님, 정보만)

- **동의어 확장**(43개 코딩 그룹, BM25 가중 0.7): 우리 retrieval miss 원인이 의역/한영 단절이라 동의어는 'auth→authentication'류 표면 정규화만 — 미미. 한국어 동의어 그룹을 만들면 형태소와 같은 한계(stage103). 참고만.
- **CJK 세그멘터**(한/중/일 스크립트 분기: 한=바이트 bigram, 일=tiny-segmenter, 중=jieba): 우리 `_cjk_like_search`(고유 CJK 자수 스코어링)의 단점(짧은 한국어 쿼리 답 행이 공통어 행에 밀려 탈락)을 부분 보완할 수 있으나, 작은 코퍼스에서 재구현 대비 이득 미검증. 참고만.
- **capture 필터**(`AGENTMEMORY_CAPTURE_ALLOW/DENY`, memory_* 기본 제외, 출력 8k 절단): 우리 G-qual 이미 write gate로 제어. 참고만.

## 4. 재현 경로

- 저장소 소스: `C:/Users/mandu/hermes-made/reviews/agentmemory-review/src/` (main @ df3d4a8, 54개 핵심 파일)
- GitHib 원본: `https://github.com/rohitg00/agentmemory` (tree API: `git/trees/main?recursive=1`)
- DB 실측(0콜, 2026-10-09): `AppData/Local/hermes/mnemosyne/data/mnemosyne.db` — superseded_by 113·valid_until 159·corrected_by 0, importance 분포 0.15×728/0.5×1127
- 우리 재정렬 공식: `gateway/j1_pipeline.py:231` (`_adjusted`)

## 5. 결론

- **직접 반영 없음**. 코드 변경 없음.
- 정합 2건(RRF 계열 표준성) — 우리 설계 표준성 근거로 HANDOFF에 기록.
- 보류 4건 전부 **선행 0콜 실측**(유병률 라벨링 또는 production-exact 3-run 회귀) 조건부 — 3.3의 순서로만 재검토.
- 소스에서 발견한 우리 대비 참신한 축: **액세스 로그 기반 강화/퇴화(우리는 아예 없음)·시간 유효성 그래프 버전(tvalid/tvalidEnd)·consolidation의 Jaccard 자동 supersede** — 이번엔 보류지만 '그래프 lane'을 도입하면 cascade/temporal은 재검토 가치 있음.