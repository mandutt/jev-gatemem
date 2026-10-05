# Stage-1 Probe: 장문 메모리 문제 실측 (jev chunking 파일럿 0단계)

- 날짜: 2026-10-05
- 방법: 0콜 결정적 probe — JEV 호출 0회, DB read-only
- 스크립트: `experiments/operational-golden/stage1_longmem_probe.py`, `stage1_vector_dilution.py`
- 판정: **jev chunking 기각 (2단계 JEV 비교 실험 불필요)**

## 배경

supermemory 트윗(DhravyaShah)의 jev chunking(문장별 continuation 판정으로 청크 경계 선택)을
우리 jev-mem에 적용할지 검토. 가설: 장문 메모리가 (a) full-text 게이트 800자 절단으로
답이 잘림, (b) 512토큰 clamp 임베딩으로 벡터가 희석돼 회수 불량을 만든다.

## 실측 1 — DB 장문 분포 (working 1,625 + episodic 113 = 1,738행)

| 버킷 | 행 수 | 비율 |
|---|---|---|
| ≤800 | 1,275 | 73.4% |
| 801–1,350 | 266 | 15.3% |
| 1,351–3,000 | 122 | 7.0% |
| 3,001–10,000 | 46 | 2.6% |
| >10,000 | 29 | 1.7% |

>1,350자 = 197행(11.3%). 상위 장문 15건의 구성:
- 대부분 `[USER] @file:` 첨부·`[CONTEXT COMPACTION — REFERENCE ONLY]`·`[opencode]/[codex]` 세션 덤프
- 자동/파일 주입이 압도적, "장문 대화 KEEP"은 드묾

## 실측 2 — op-90 골드 메모리 길이 (게이트 절단 손실 상한)

DB 원문 기준 gold 메모리 45건: **min 23 / p50 371 / p90 572 / max 687 — 전부 800자 미만**.

- full-text 게이트(800자, head600+tail200) 절단 손실: **0건**
- exp7g의 "절단으로 6건 NO→YES"는 43건 표본(gold 비공식 조회)의 현상이었고,
  op 90 골드셋에는 절단 대상 장문 gold가 아예 없음
- "답이 중간에 잘려 게이트가 NO를 준다" 시나리오: op 90 기준 존재하지 않음

## 실측 3 — 벡터 희석 시뮬레이션 (로컬 bekko-a8m, 0콜)

저장 벡터 1,633개(전부 bench/bekko-a8m, 384dim)를 실 DB에서 로드. 장문 116행 표본에서
head-300/mid-300 자기발췌 쿼리 232건 → whole(저장 벡터) vs chunk(규칙 기반 800자 청크,
max cos) 순위 비교:

| 지표 | whole(통째) | chunk(최대) |
|---|---|---|
| top-10 | 1.0% | 1.0% |
| top-30 | 2.5% | 2.0% |
| top-100 | 8.3% | 4.9% |
| median rank | 956 | 755 |

- top-100 진입 기준: lifted 5건 vs hurt 12건 → **청킹이 순위를 개선한다는 증거 없음,
  오히려 역효과 경향**
- median은 개선되나(956→755) 꼬리 행 이동일 뿐 top 회수에 실질 영향 없음
- 한계(정직 표기): 쿼리는 행 자기발췌라 실제 사용자 쿼리 분포와 다름. "개선 없음"은 주장하지만
  "악화"는 시뮬레이션 아티팩트일 수 있음. 어느 쪽이든 채택 근거는 아님.

## 판정 — jev chunking 기각

1. **게이트 절단 손실 0건** (op 골드 전부 ≤687자) — 글의 핵심 이득 시나리오가 우리 골드셋에 없음
2. **vec 희석 개선 근거 없음** — 청킹 top-100 진입 오히려 감소, hurt > lifted
3. **대상 행의 실체** — 장문의 대부분은 파일 첨부/컴팩션/타 에이전트 덤프라 "의미 단위 chunking"의
   대상이 아니라 "제외/필터" 대상에 가까움

→ 2단계(continuation vs boundary choice vs 규칙 기반 JEV 비교)는 근거 소멸로 **불필요**.
JEV 콜·비용·rate limit 부담 없이 종결.

## 잔여 관찰 (별도 이슈로 분리할 가치)

"토큰 폭탄"(107,885자 등 비정상 대형 행)은 읽기/회수 문제가 아니라 **prefetch 컨텍스트·비용
오염 문제**로 여전히 존재. 해법 후보는 청킹이 아니라: ① 메타 프리픽스(`[opencode]`/`[codex]`/
`@file:`/COMPACTION) 기반 prefetch 제외 ② 길이 캡. 후속 결정 필요 시 별도 검토.