# STAGE50C/D — RRF·lane 분해 실측: "답이 rank 8~9"는 시점 필터 pool 인공물, 실운영 RRF는 답을 1~3위로 정렬 (2026-10-06)

## 배경

- stage49d에서 "답 있는데 top-5에 답 없음" 21건이 pool 안 **rank 6~60(표본 rank 8~9)**에 있다고 판정 → rerank 실패로 해석.
- 사용자 요청으로 ①RRF 순위 개선 ②lane 분해 ③noul 재정렬 3축을 0콜 실측.

## 실측 1 — lane 분해 (stage50c, 0콜, 21건)

답 후보의 lane 단독 순위 (fts/vec, budget 200):

- **FTS 단독 1~2위 11/18, vec 단독 1~2위 12/18** — 답은 검색에서 이미 잘 잡힌다.
- fts도 vec도 안 잡힘: #37·#44·#58 (3건) — graph/imp 전용이거나 답 후보 탐색 키워드 한계.
- lane 조합: fts+vec 16건, fts+vec+graph 2건 — **imp lane은 답에 기여 0건**.

## 실측 2 — RRF 정밀 재현 (stage50d3, 0콜)

실제 코드(`_rrf_merge`, RRF_K=30, 예산 fts 60/vec 60/imp 8/graph 10)를 재현해 ans rank 계산:

- **답은 RRF에서 rank 1~3 (18건 중 15건)** — #51(9), #54(5), #45(3)만 열위.
- **49d의 "rank 8~9"는 시점 필터 pool(created_at<10-05, 135행 제거)에서의 순위** — 평가용 축소 pool의 인공물.
- **실운영 pool(시점 필터 없음)에서는 RRF가 답을 이미 1~3위로 정렬** → ① RRF 개선 여지 없음, ③ lane 개선 여지 없음 (0콜 반증).

## 실측 3 — noul 재정렬 (0콜, stage50 raw 재분석)

- 18건 전부 `winner_noul == noul_top` — **JEV choice는 이미 noul 1위 후보를 고르고 있음** (재정렬·재choice = 동일 결과).
- noul 점수는 답 후보도 0.79~0.97로 높음 — answerability 변별력 없음 (stage50/50b와 일치).

## 종합 판정

| 실측 | 결과 |
|---|---|
| ① RRF 순위 개선 | ❌ 불필요 — 답이 이미 RRF 1~3위 (실운영 pool) |
| ③ lane 개선 | ❌ 불필요 — FTS/vec 단독 1~2위 |
| noul 재정렬 | ❌ 무효 — choice가 이미 noul 1위 선택, noul 변별력 없음 |

**→ 37% "답 놓침"의 진짜 원인은 JEV choice가 답(1~3위)을 못 고르는 rerank 실패이며, RRF·lane·noul·문구·구조 실측으로 이미 소진. 검색/병합 레버는 모두 기각 — 남은 축은 rerank 결정 로직(신호 설계) 또는 판정자 교체.**

## 추가 교훈

- **시점 필터를 적용한 pool(평가용)의 순위는 실운영 pool 순위와 다르다** — 49d가 "rank 8~9 rerank 실패"로 해석한 것도 이 때문. 평가 셋 판정 시 "어느 pool 기준"인지 명시하지 않으면 실운영과 다른 결론이 난다.
- 평가용(시점 필터) pool과 실운영 pool의 순위 차이가 판정을 바꾸는 경우 → **실운영 pool로 재검증**이 표준.

## raw

- `data/stage50c_lane_decomp.json` (21건 lane 순위)
- `data/stage50d_lane_ranks.json` (18건 lane 4종)
- `data/stage50d3_decomp.json` (18건 RRF 정밀)
- 러너: `stage50c_lane_decomp.py`, `stage50d_rrf_sim.py`, `stage50d_rrf_top8.py`, `stage50d3_rrf_decomp.py`