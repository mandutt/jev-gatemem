# 메모리 솔루션 생태계 스크리닝 기록 (2026-10-10)

> GitHub star 상위·웹·레딧·아카이브에서 메모리 솔루션을 스캔한 기록.
> **참고할 만한 사항이 있었던 경우만 문서화** — 아래는 확인했던 목록만 남긴다.
> 심층 검토: `2026-10-10_tigerless-agent-memory-review.md` (보류 1건·기각 1건)
> 재탐구 트래킹: TencentDB Agent Memory (L0~L3 계층 증류) — §3 참고

## 1. GitHub star 검색 (agent memory / llm memory / memory layer / long-term memory)

검색 쿼리 4종, 총 19개 후보 스크리닝 (기존 검토 완료 제외 후):

| 저장소 | ★ | 비고 |
|---|---|---|
| mem0ai/mem0 | 66.9k | **이미 검토 완료** (mem0-review) |
| letta-ai/letta | 25.1k | **이미 검토 완료** (synix 8종) |
| topoteretes/cognee | 31.9k | **이미 검토 완료** (synix 8종) |
| rohitg00/agentmemory | 29.3k | **이미 검토 완료** (agentmemory-review) |
| vectorize-io/hindsight | 47.7k | **이미 검토 완료** (synix 8종) |
| volcengine/OpenViking | 39.5k | ❌ 클라우드/RAG 통합 — 우리 아키텍처와 대척 |
| TencentCloud/TencentDB-Agent-Memory | 27.9k | ⏸️ **참고 — L0~L3 계층 증류, §3** |
| gastownhall/beads | 27.8k | ❌ 이슈 트래커 (Dolt 버전관리 DB) — 메모리 아님 |
| MemoriLabs/Memori | 17.1k | ❌ 클라우드 API 키 의존 (LoCoMo 자체 보고) |
| memvid/memvid | 16.6k | ❌ Rust 스마트프레임(비디오 코덱 압축) — LLM 어사이드 |
| EverMind-AI/EverOS | 13.4k | ❌ 마크다운 SoT, 우리 SQLite+게이트와 중복 |
| MemTensor/MemOS | 11.8k | ❌ 메모리 OS/큐브 KB — 신규 레버 없음 (벤치 자체 보고) |
| MemMachine/MemMachine | 3.1k | ❌ 그래프+에피소딕, 신규 레버 없음 (자체 보고 91.7%) |
| tigerless-labs/agent-memory | 3.4k | ✅ **심층 검토 — Manage 레이어 보류 등록** |
| Dataojitori/nocturne_memory | 1.4k | ❌ 그래프 메모리 서버, 신규 레버 없음 |
| ClaudioDrews/memory-os | 1.4k | ❌ Hermes 전용 7레이어 메모리 OS (Qdrant) — 신규 레버 없음 |
| Sibyl-Labs/Sibyl-Memory | 172 | ❌ 파일 기반·임베딩 없음 — 우리 하위 |
| Siddhant-K-code/distill | 196 | ❌ write-time dedup·감도 태깅 — 우리 supersede/valid_until 커버 |
| bandr-ai/vektori | 136 | ❌ 사실+문장 그래프 — 신규 레버 없음 |
| cmoraes10/loci | 28 | ❌ Hermes 플러그인, 미성숙 |
| indigokarasu/chronicle-agent-context | 9 | ❌ Hermes 전용 컨텍스트 압축 — 미성숙 |
| campfirein/byterover-cli | 5.0k | ❌ 컨텍스트 트리+브랜치 병합 — 메모리 아키텍처 아님 |
| heymi/aldus-palace | 102 | ❌ 약속/결정 메모리 — 미성숙 |
| sqliteai/adam | 124 | ❌ C 에이전트 라이브러리 — 우리와 다른 레이어 |
| MemoriLabs/Memori (Hermes 어댑터) | — | ❌ 클라우드 의존 |

## 2. 웹/레딧/아카이브 스캔

| 출처 | 내용 | 판정 |
|---|---|---|
| agentmemorybenchmark.ai LongMemEval leaderboard (2026-10-10) | 등재 솔루션 5종 신규 검토 — **참고 2·정합 2·기각 3, 직접 반영 없음** (reranker=JEV 순서 무영향 Run R·시간 캘린더=발동률 1.1~1.3%·dynamic prompting=0콜 원칙 위반). TiMem 계층 통합 경계는 백그라운드 합성 재검토 트리거로 참고 등록. 상세: `2026-10-10_longmemeval-leaderboard-review.md` | 📋 참고 — 검토 문서 1벌 완료, 보류 신규 0 |
| arXiv 2606.24775 "Are We Ready For An Agent-Native Memory System?" | 12개 메모리 시스템·5벤치·11데이터셋 실증 — **"단일 아키텍처가 모든 워크로드 지배 못함, 워크로드 병목 정렬이 핵심"**, "로컬라이즈드 유지보수 > 글로벌 재조직" | 📋 참고 — 우리 선택 근거와 정합 |
| arXiv 2606.29914 MemDelta | **임베딩 모델만 교체해도 정확도 ±6포인트** — 승자가 뒤집힘 | ✅ 정합 — 우리 embedding-fullpath-gate(S4)와 독립 일치, "임베딩 고정 비교" 규칙 |
| benchd.ai 벤치마크 가이드 | 무메모리 LLM 기준선 57.6% > 대부분 메모리 시스템 (Mem0 OSS 32.4% 검증) — 자체 보고와 검증 격차 | ✅ 우리 실측 우선주의 재확인 (자체 보고 수치 분리 표기 규칙) |
| maximem.ai "claimed vs observed" | Mem0 4월 업데이트 실측 57.5→73.8% 진짜 개선, 93.4% 발표는 **판정 프롬프트에 숨겨진 CoT** 때문 | ✅ 검증 회의론 — 우리 자체 보고 분리 규칙 지지 |
| Reddit r/AI_Agents Signet | 세션 종료 후 별도 LLM 파이프라인 추출, 대화 중 툴콜 없음 (80% F1 LoCoMo 자체 보고) | 🔭 후보 — 비동기 증류 패턴 (우리 보류와 동일 방향) |
| Reddit r/AI_Agents Genesys | 인과 그래프 기반 저장 (89.9% LoCoMo 자체 보고) | 🔭 후보 — 미검토 축 (인과 그래프), 단 자체 보고 |
| Reddit r/mcp 70+ 시스템 개요 | "저장 포맷보다 검색 아키텍처가 중요" — 포인터 기반 인덱스 선호 | 📋 참고 |
| Reddit r/aiagents "which system" | Mem0(추출)·Engram(진화)·Zep(시간 그래프)·Letta(런타임)·LangMem(배경 형성)·Supermemory(컨텍스트) | 대부분 이미 검토 완료 |

## 3. TencentDB Agent Memory — 재탐구 트래킹

- **구조 (README + hermes-plugin 소스 확인)**: L0 대화 → L1 Atom(구조화 사실) → L2 Scenario(시나리오) → L3 Persona(페르소나) **4단계 계층 증류**. Hermes 플러그인 공식 제공 (`hermes-plugin/memory/memory_tencentdb/`). 클라우드 SDK(`client.py` — Tencent Cloud API 호출) 의존.
- **흥미로운 점 (우리가 안 해본 축)**: 플랫한 working_memory 2,085행을 **계층(L2/L3)으로 집계**하는 개념. 우리 consolidated_at 595행이 메타데이터 필드만 채운 것과 대비.
- **이유로 보류**: 클라우드 SDK 의존 + 계층 증류가 실질적으로 우리 보류(L2/L3 집계)와 교차.
- **재탐구 트리거**: ① 코퍼스가 수만 행으로 성장 ② 백그라운드 합성(Manage) 실험이 시작될 때 — 이때 L2/L3 계층 증류를 우리 스키마로 매핑할 가치.
- 판정: **참고 등록 (보류 아님)** — 지금은 문서만, 재탐구 시점 인식용.

## 4. 보류 등록 요약 (심층 검토 2건 → 기각 1건·보류 1건으로 확정)

| 항목 | 판정 | 근거 |
|---|---|---|
| tigerless 백그라운드 Manage (merge/supersede/split/delete 제안) | ⏸️ 보류 | Honcho 보류(백그라운드 합성)와 동일 레버, 코퍼스 2,085행 시기상조 |
| tigerless 읽기 횟수 boost (recall_count 활용) | ❌ **기각 (0콜 실측)** | recall_count 상위 = 도배 군집(50% 토론 복사) + **자기 강화 루프**(노출→bump→재노출) + stage85 gold rank 41·36 밀림 위험. **do not re-run** |

## 5. 원본 소스

- 스크리닝 README 원문 22종: `reviews_tigerless/survey-sources/` (저장소명.md)
- tigerless 소스 미러: `reviews_tigerless/src/`