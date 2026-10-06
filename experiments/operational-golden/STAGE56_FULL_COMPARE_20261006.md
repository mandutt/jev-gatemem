# STAGE56 — base vs pool20 풀 비교 (같은 세션 3-run paired, 2026-10-06, 840콜, err 0)

> stage54(1-run)/stage55(3-run)는 **세션이 달라 비결정성이 섞였다** (base 79/80 vs pool20 78/79 의 -1).
> 같은 세션에서 두 구조를 각 3-run으로 paired 비교해 확정.

## 결과 (op-90 + noans-50, 각 구조 3-run)

| 구조 | hit@1 (3-run) | hit@3 | abstain | noans FP (3-run) |
|---|---|---|---|---|
| base | 78 / 78 / 78 | 79 / 79 / 79 | 2·2·3 | 21 / 22 / 21 (평균 **21.3**) |
| pool20 | 78 / 78 / 78 | 79 / 79 / 79 | 2·2·2 | 13 / 13 / 13 (평균 **13.0**) |

## 핵심 발견

1. **op hit@1/3 표면 동일 (78/79)** — 그러나 **"동일"이 같은 78이 아님** (3-AI v3 검토 + 0콜 재검증, 2026-10-06):
   - pool20 손실 2건은 **구조적 회수 불가** (gold가 rank 21~60에 존재):
     - #80 deepseek 장문 (gold **rank 41**) — base [1,1,1] vs pool20 [None,None,None]
     - #87 camelai-serial-proxy (gold **rank 36**) — base [1,1,1] vs pool20 [None,None,None]
   - pool20 개선 2건은 **우연** (#58 KoDialogBench, #72 pi 프록시 — gold rank 8, 어떤 구조든 20 안)
   - → **같은 78은 "구조적 손실 2 + 우연 개선 2"의 상쇄** — 비결정성이 아니라 **pool20의 실질 op 성능은 76/90**.
2. **noans FP: 21.3 → 13.0 (−8.3, −39%)** — 같은 세션에서 확고한 개선. 단 **"일방"이 아님**: 쿼리별 3-run 대조에서 개선 10건 / 동일 39건 / **악화 1건** (#41 web_extract JS 렌더링: base abstain 2/3 → pool20 0/3 전부 FP).
3. **쿼리별 majority 대조: 4건 차이, 구조적 손실 2 + 우연 개선 2** — "2:2 상쇄 = 무작위" 해석은 오류였음 (C AI 지적 + 0콜 검증).
4. **50d3 실운영 RRF에서도 rank 5·9 각 1건** (16/18이 rank≤3, 2건이 경계 밖) — pool20은 이 2건도 회수 불가 (B/C AI 지적).

## 최종 판정 — pool20 조건부 채택

- **op 구조적 손실 2건 (deepseek·camelai) + noans FP −39% (개선 10·악화 1)** — **명시적 트레이드오프** (일방 개선 아님).
- h 재계산: op 정답 2건 손실 vs noans 오주입 8.3건 감소.
- **부수 효과**: criteria 61→21 → 토큰 ~35% 절감 + latency 감소 (단 %는 요청 전체 기준 추정치 — 토큰 실측은 아님, C AI 지적).
- **채택 조건**: ① C AI의 production-exact live60 paired 3-run(360콜, 시간 필터 제거) 통과 ② B AI의 rank-veto 시뮬(0콜) 결과 확인 ③ "answer-support rank>20이 1건이라도 나오면 pool20 전면 채택 말고 30/40 재평가" (C AI 롤백 규칙).
- 코드 반영 보류 유지.

## 채택 시 반영 사항

- `gateway/j1_pipeline.py`: `POOL_BUDGET = 60 → 20` (채택 조건 통과 시)
- 릴리스 게이트(§protocol): production-exact live60 paired 3-run 통과 후 반영
- ⚠️ retrieval ceiling: **underlying 60-pool recall은 유지되나 JEV rerank-stage의 effective recall ceiling은 낮아짐**
  (rank 21~60 후보가 JEV 평가에서 완전히 제거 — C AI 지적). pool20 채택 = 이 ceiling 감소를 명시적으로 수용.

## raw

- `data/stage56_full_compare.json` (2구조 × 3-run × 140 = 840 레코드)
- 러너: `stage56_full_compare.py`
- 로그: `data/stage56_run.log` (err 0, 429 0)