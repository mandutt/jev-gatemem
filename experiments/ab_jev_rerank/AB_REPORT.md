# JEV_RERANK 실사용 A/B — 1차 결과 (2026-09-27)

> **상태**: 완료(1차) → **데이터 축적 후 재평가 예정**
> 사용자 판정: 실사용 체감 차이를 구분하기 어려움 → 보류

## 개요

실사용 user 쿼리에 대해 OFF(베이스 Mnemosyne prefetch)와 ON(J1 pipeline)이
생성하는 `## Mnemosyne Context` 블록을 페어와이즈 비교.

- 실험 스크립트: `experiments/ab_jev_rerank_render.py`
- 데이터: `state.db` 최근 21일 user 메시지 → 12쿼리 선별 (지시/질문 위주, 중복 제거)
- 실행 DB: **live** `mnemosyne.db` (읽기 전용)
- 블라인드 UI: `experiments/ab_jev_rerank/pairs.html` (A/B 랜덤 배치)
- 스냅샷: `experiments/ab_jev_rerank/run_20260927_201639.json`

## 실측 결과

| 지표 | 값 |
|---|---|
| 총 쿼리 | 12 |
| 유효 비교 (pool ≥2) | 9 |
| **완전 동일 (disagree=0)** | **5/9 (56%)** |
| **순서 변경 (disagree)** | **4/9 (44%)** |
| 평균 후보 수 | 6.5 (OFF=ON) |
| Jev 지연 | ~230ms/쿼리 (ON만) |

### disagree 4건 실측 상세 (라벨 공개)

| # | 쿼리 | OFF top1 | ON top1 | 차이 유형 |
|---|---|---|---|---|
| 1 | gateway.py retrieve API 완성 | Codex↔Mnemosyne 연동 (task) | 게이트웨이 워치독 (insight) | 1↔2 스왑 |
| 3 | J1 런타임 재검증 | Codex 연동 (task) | camelAI 내부모델 고정 재검증 (tool) | 1위 교체 (다른 메모리) |
| 10 | 데스크톱 재시작 후 명령 | opencode 플러그인 (decision) | 게이트웨이 워치독 (user) | 1↔2 스왑 |
| 11 | memory prefetch 검증 | 작업 스케줄러 금지 (preference) | Hermes 18080 프로바이더 설정 (tool) | 1위 교체 (다른 메모리) |

**관찰**:
- 5/9 쿼리는 Jev 호출이 **결과를 전혀 바꾸지 않음** (순수 비용 ~230ms)
- 4/9 쿼리에서 순서/1위 변경 — 대부분 1↔2위 스왑 수준
- [11]만 "서로 다른 카테고리 메모리 교체"라 의미 있는 차이 (preference vs tool)

## 사용자 피드백 (기록)

> "실질적으로 그냥 읽어서는 어느 쪽이 더 좋은지 차이를 모르겠어. 다만 똑같은
> 내용이 나오는 경우도 있는 것 같아" + "A/B 선택지가 뭘 의미하는지 잘 모르겠다"
> → **메모리 수가 적어(766 rows) 실사용 쿼리에서 두 파이프라인 결과가 거의
> 수렴하는 것이 원인으로 보임. 데이터 축적 후 재평가하기로 결정.**

## 결론 (1차)

1. **현재 규모(766 rows)에서는 J1이 실사용 체감 차이를 만들지 못함** —
   lane pool + gate가 이미 충분히 특정돼 Jev가 바꿀 여지가 적음
2. **Jev 자체는 정상 동작** (idx 선택, ~230ms, 실패 없음) — 문제는 "효과 여지"
3. J1의 수치상 이점(recall@1 0.712)은 스냅샷 평가셋(gold 있는 52쿼리)에서만
   확인된 것이며, **골드 없는 실사용 쿼리에서는 두 경로가 수렴**

## 재평가 조건 (이후)

- [ ] 메모리 2,000+ rows 도달 후 동일 스크립트 재실행
  (`--limit 12` → disagree율 상승 확인)
- [ ] disagree 4건 이상 + 사용자 판별 가능 시 → 선호 집계로 J1 유지/제거 판정
- [ ] 그 전까지는 **J1 유지** (스냅샷 수치 개선 + fallback 안전성 보유)

## 산출물

- `experiments/ab_jev_rerank_render.py` (재사용 가능)
- `experiments/ab_jev_rerank/run_20260927_201639.json`
- `experiments/ab_jev_rerank/pairs.html`
- 이 보고서