# synix.dev "Agent Memory Systems: A Source-Level Analysis of Eight Architectures" 검토 — 참고 5 · 보류 1 · 정합 1, 직접 반영 없음 (0콜 실측)

> 본 검토는 우리 'jev-mem' 프로젝트(과학적 내부 메모리 게이트 데몬)의 관점에서
> 외부 조사 아티클을 대조한 것이다. 학술 'Jev-Mem'(arXiv 2609.23986)·npm
> 'jevmem'(Avinash-jetwani)·혼동 금지 — 이름만 유사한 별개 프로젝트들이다.
> 판정은 아티클 본문(source-level 분석)과 우리 라이브 DB·trace 0콜 실측으로만
> 내렸다. JEV API 호출 없음. 코드 변경 없음.

- 검토일: 2026-10-10 (토)
- 대상: https://synix.dev/articles/agent-memory-systems/ — Mark Lubin, 2026-02-16. Letta v0.16.4 / Cognee v0.5.2 / Graphiti v0.27.1 / Tacnode(closed) / Mem0 v1.0.3 / Hindsight v0.4.11 / EverMemOS(commit 1f2f083) / Hyperspell(closed) 8종을 소스 레벨로 분석한 조사 아티클
- 방식: 아티클 전문 추출 + 우리 라이브 DB 2,085행·trace(10-07~10-09) 프로브로 각 주장·레버의 우리 대응·유병률 실측 (0콜)
- 재현 경로: 본 문서가 유일 산출물 (아티클 raw: `AppData/Local/hermes/cache/web/synix.dev-a4295a8cb7.md`)

## 0. 대상 요약 (아티클 주장)

8개 에이전트 메모리 시스템을 ingestion→storage→retrieval 코드 경로로 비교한 조사물. 핵심 주장:

1. 이 공간은 4가지 근본적으로 다른 베팅으로 나뉜다: **LLM 전권 관리**(Mem0, Letta) / **명시적 지식 구조 파이프라인**(Cognee, Graphiti, Hindsight, EverMemOS) / **데이터 인프라**(Tacnode — ACID·time travel·멀티모달 단일 DB) / **데이터 접근**(Hyperspell — 43개 OAuth 커넥터).
2. 파일럿 상수·메커니즘: Mem0 = 턴당 2콜(추출 + 기존 사실 대조·add/update/delete), 업데이트는 벡터 스토어 in-place overwrite + 별도 SQLite changelog(검색 경로 미통합). Graphiti = 에지당 4개 시각 필드(t_created/t_valid/t_invalid/t_expired), 모순 시 자동 invalidate, 엔티티 dedup 2-phase(결정적 MinHash/Jaccard + LLM). Hindsight = 4유형 사실(world/experience/opinion/observation) + observation은 백그라운드 합성, 4-way 병렬 검색 + RRF + cross-encoder, 인과 링크 가중. Letta = sleep-time `memory_rethink` 블록 전면 재작성. EverMemOS = MemCell 경계 탐지(하드 8,192토큰·50메시지 + LLM 판정).
3. 보편 패턴: **temporal handling이 일관되지 않다**(Cognee 시간 모델 전무, Letta는 대화 타임스탬프만). "지난주 화요일에 에이전트가 뭘 알았나"류 시점 쿼리를 답하는 시스템이 거의 없다.
4. **인프라/지식 분리: 어느 시스템도 둘 다 잘하는 케이스가 없다** (지식 파이프라인 계열은 트랜잭션 보장 부분적~전무, 인프라 계열은 추출·그래프 없음).
5. **평가의 문제**: 전 시스템이 retrieval accuracy로 평가되는데, 진짜 메모리 품질 = "에이전트 행동이 경험에 따라 적절히 변하는가". 합성(consolidation)이 평가 프레임워크 없이 retrieval 지표로만 재는 구조. 토큰 레벨 메모리 vs 잠재 표현(latent) 메모리 논의도 있음.

## 1. 축 대조 표 (우리 jev-mem vs 아티클 8종 패턴)

| 축 | jev-mem(우리, 실측) | 아티클 8종 패턴 | 관계 |
|---|---|---|---|
| write-time 게이트 | JEV G-qual/G-AS (턴당 기본 1콜, assistant opt-in 2콜) | Mem0 2콜(추출+대조)·Graphiti 에피소드당 3+N콜·나머지 무게이트 전량 저장 | 우리 우위(비용·저장 손실 제어) |
| 저장 단위 | 턴 단위 발화 verbatim (게이트 통과 행) | 원문 chunk(Cognee)·사실 스니펫(Mem0)·텍스트 블록(Letta) | - |
| 시간 모델 | read-time SQL 필터(superseded_by 113행·valid_until 159행·[since,before) 반개구간) + event_date 142행 | Cognee 전무 · Graphiti bi-temporal 4필드 · Letta 대화 타임스탬프만 | **정합**(아래 P2) |
| 중복/버전 | supersede(113행) + 재전송 dedup 후보(임시) | Graphiti 에지 auto-invalidate · Mem0 in-place overwrite | 우리 우위(read-time 보존) |
| 랭킹 퓨전 | RRF k=30/60 + lane 단독 | Hindsight RRF+RRF+RRF(cross-encoder 재랭크) | 동종 계열 |
| 무답 처리 | abstain 라벨 + soft gate τ=0.3 | 대부분 없음(유사도 floor 없음) | 우리 우위 |
| 백그라운드 합성 | 없음 (consolidated_at 595행은 메타데이터만) | Hindsight observation·Letta memory_rethink | 보류(아래 D1) |
| 시점/문맥 경계 | 없음 (문맥 = excerpt 300→150) | EverMemOS MemCell 8,192토큰/50메시지 경계 | 참고(아래 N3) |
| 평가 | op-90/noans-50/라이브 60 + 소비 QA(stage93/94) + canary L1/L2 | retrieval accuracy 일변도 (자체 보고 벤치) | 우리 우위(다축 평가) |
| 벤치 수치 | pool_recall 90.0%·op hit@1 78/79 (자체 실측) | 8종 자체 보고 수치 (LongMemEval/LoCoMo 등, 조건 상이) | 분리 표기 |

## 2. 판정 상세

전체 판정: **직접 반영 없음(0콜·코드 미변경)** — 참고 5 · 보류 1 · 정합 1.

### 정합(설계 표준성 근거)

- **P1. read-time 시점 필터 구조** — Hindsight가 가장 production-ready한 temporal retrieval로 평가되고 Graphiti가 bi-temporal 4필드를 쓰는 것과 독립적으로, 우리는 `superseded_by IS NULL AND valid_until > now` SQL read-time 필터(supersede 113행·valid_until 159행, `[since,before)` 반개구간)로 동일 문제(구버전/신버전 동시 노출)를 해결한다. 외부 구현이 다른 방식으로 같은 설계 방향을 잡는 것은 우리 read-path 시간 필터의 표준성 신호 (MemPalace·sift 검토에서 이미 정합 확인한 축과 동일).

### 참고 (아티클이 우리 실측 결론을 재확인한 항목)

- **N1. Mem0 2콜 구조·in-place overwrite — 우리가 이미 설계로 회피 (기각 대응)**: Mem0의 '추출 1콜 + 기존 사실 대조 1콜'은 우리 G-qual/G-AS(기본 1콜)와 '업데이트 overwrite + changelog 미통합'은 우리 write-time supersede + read-time 필터 구조로 이미 해결. 단 **우리 G-qual도 기존 행과의 모순/대체 관계를 보지 않아 '새 버전 별개 행 저장'이 기본 경로일 수 있다** — Honcho 검토에서 이미 보류 등록(자동 모순/지식업데이트 감지 배치, corrected_by 0건; supersede 113행은 그 우회의 발생 사례일 수 있어 **모순 유병률 사람 라벨링 실측이 선행 조건**). Mem0의 'LLM이 대조까지 전담'은 그 대안 중 하나라는 점에서 같은 보류 항목의 근거를 보강.
- **N2. Graphiti 모순 시 자동 invalidate — do not re-run (기각 대응)**: 에지 무효화가 "새 사실이 옛 사실을 대체"라는 가정에 기반하는데, 우리는 이미 실측 **자동 supersede 기각(84그룹 사람 판정: "진짜 새 버전 충돌 0건" — 재전송 중복 5·동일 지시 3)으로 이 가정이 우리 코퍼스에서 성립하지 않음을 확인**했다. same-topic 인접 메모리가 진짜 '버전 충돌'인지 사람 판정이 없으면 자동 무효화는 정답 행을 유실한다(fail-open 원칙).
- **N3. EverMemOS MemCell 경계 탐지 (하드 8,192토큰/50메시지 + LLM 판정) — 우리는 커버리지·비용 구조가 다르다**: 우리는 2,085행 코퍼스에 턴 단위 저장 + excerpt 300→150 윈도우로 문맥을 유지한다(stage17~18/47 계열 실측). LLM 경계 판정은 저장 경로의 콜 수를 늘리고(우리 기본 1콜 원칙), 8,192토큰 경계는 장문 청킹 문제를 소비 측으로 미룬다 — 단, **'어떤 하드/LLM 경계도 없이 excerpt만으로 문맥을 재구성'하는 우리 쪽이 시점·문맥 경계 축에서 취약**하다는 지적은 유효하며 drawer 문맥 재구성 보류(D1)와 같은 보류 항목에 합류한다.
- **N4. "인프라/지식 분리: 어느 시스템도 둘 다 잘하는 케이스가 없다" — 우리가 그 둘을 모두 보유한 유일한 구조**: 문단 주장(지식 파이프라인 = 트랜잭션 약함, 인프라 = 추출 없음)을 우리에 대입하면 — SQLite 단일 DB(read-time 필터·게이트 trace) + JEV 판정(write/read 모두) — 우리는 '저장 게이트(지식 판정) + ACID 단일 DB(인프라 보장)'를 동시에 갖고 있어, 이 문단이 지적하는 업계 공백이 우리에겐 존재하지 않는다. 외부 검토 문서에 우리 구조 표준성의 근거로 기록할 가치 있음.
- **N5. '행동 변화 = 메모리 품질' 평가 프레임워크 부재 — 우리가 이미 소비 측 QA로 보완 (채택 완료 축)**: 아티클의 핵심 개방 문제("retrieval accuracy ≠ 메모리가 잘 작동하는가")는 우리가 stage93/94 소비 QA(deepcombo 2×2 + LLM 판정, 제시된 메모리 기준) + canary L1/L2(drift) + 홀드아웃 동결(stage99)로 이미 실현·운영 중인 차원이다. 아티클이 "거의 어떤 시스템도 측정하지 않는다"고 한 것을 우리는 측정하고 있다 — 추가 채택 없음.

### 보류

- **D1. 백그라운드 합성(consolidation) — Hindsight observation / Letta memory_rethink 계열**: stage92 종결('2콜 구조 전체 종결')과 OptMem·Honcho 검토(요약 트리·비동기 추론 보류)와 같은 축. 아티클이 "consolidation은 retrieval 지표로만 평가된다"고 비판한 점은 우리 코퍼스(2,085행)에서 consolidated_at 595행이 메타데이터 필드만 존재(consolidation_claimed_at 0건)하는 상황과 합쳐져 **'저장된 발화의 재구성(문맥·패턴) 레버'가 미실측 상태**임을 지적한다. 단 채택 전제는 그대로 — 소비 측 구조 변경(사용자 승인 영역·stage93/94 프레이밍과 교차) + 코퍼스 성장(수만 행, OptMem과 동일 논리). 시기상조 보류.

### 분리 표기 (자체 보고)

- 8종 벤치 수치(Mem0/Graqiti 등 각 자체 보고, LongMemEval/LoCoMo/BEAM 등 데이터셋·조건 상이)는 우리 실측과 분리 표기 — 직접 비교 금지.
- Tacnode·Hyperspell은 클로즈드 소스로 소스 검증 불가(아티클 자체 한계 명시) — 실측 대상 아님.

## 3. 실측 근거 (이 문서의 근거, 0콜)

| 근거 | 내용 |
|---|---|
| 아티클 전문 | web_extract (full 36,640자, 캐시: `AppData/Local/hermes/cache/web/synix.dev-a4295a8cb7.md`) |
| 우리 라이브 DB (0콜) | `%LOCALAPPDATA%\hermes\mnemosyne\data\mnemosyne.db` working_memory 2,085행: superseded_by 113·valid_until 159·corrected_by 0·event_date 142/2,085·consolidated_at 595(consolidation_claimed_at 0)·정확 중복 content 최대 8건(벤치 태스크/승인류 — 24h 재전송 dedup 후보와 일치) |
| 우리 라이브 trace (0콜) | `logs/jev_trace_20261007~09.log`: \|jev\| 374건·\|pool\| 3,278건 — 상대시간 쿼리(좁은 패턴: 어제/내일/지난주/언제 등) JEV 4/374(1.1%)·pool 111/3,278(3.4%), 실질 참조는 '어제 날씨·내일 복권·지난주 금요일' 등 극소수, 나머지는 '언제 추가됐지?'류 기능 질문 — temporal 부스트 발동률 낮음 (MemPalace C4·stage90 IDF 1.7%와 동일 논리) |
| 우리 실측 재사용 | 자동 supersede 기각(84그룹 사람 판정)·stage92 2질문 종결·stage93/94 소비 QA·stage99 홀드아웃·canary L1/L2·OptMem/Honcho 보류(consolidation·비동기 추론)·MemPalace C4(시간 부스트) |

## 4. 결론

이 아티클은 8종 소스 분석 조사물로, **직접 이식할 코드·상수·메커니즘이 없다**(모두 우리가 이미 실측·기각했거나 설계로 회피한 레버 — Mem0 2콜/overwrite, Graphiti auto-invalidate, temporal 부스트, consolidation). 가치는 세 가지다: ① 우리 read-time 시점 필터가 업계 최선축(Graphiti bi-temporal·Hindsight temporal)과 정합함을 재확인 ② "행동 변화 = 메모리 품질" 평가 프레임워크 부재 지적이 우리 소비 QA(stage93/94)·canary L1/L2보다 뒤처진 상태임을 보여줌(우리 선행 확인) ③ 백그라운드 합성(observation/memory_rethink) 보류 항목의 근거를 보강.

**직접 반영할 사항 없음.** 후속 제안이 오면: Mem0 2콜·overwrite = do not re-run (우리 supersede/valid_until 구조가 기능 우위), Graphiti auto-invalidate = do not re-run (자동 supersede 84그룹 기각), temporal 부스트 = do not re-run (trace 유병률 1.1%), consolidation = D1 보류 유지(소비 측 승인 영역·시기상조).

- 다음 단계: 없음(직접 반영 0). D1만 코퍼스 성장·소비 측 실험 승인 시 재검토 가능.