# STAGE86 — candidate diversification JEV 검증 (2026-10-07, 600콜, err 0)

> c-ai·a-ai 제안 — 규칙/사실 슬롯 분리. production-exact pool (시간 필터 없음), JEV 입력 60개 유지,
> 노출 상위 5개만 규칙 cap 슬롯 구성. 최종 로직: stage56 표준 lift (JEV가 gold를 고르면 hit@1).

## 결과 (op90 + live60, 4조건)

| 조건 | op hit@1 | op hit@3 | abstain | live block abstain | valid 오차단 |
|---|---|---|---|---|---|
| base (현행) | **78** | 79 | 3 | 0/38 | 0/22 |
| cap1 (규칙 1) | **78** | 79 | 2 | 0/38 | 0/22 |
| cap2 (규칙 2) | **78** | 79 | 3 | 0/38 | 0/22 |
| cap3 (규칙 3) | **78** | 79 | 3 | 0/38 | 0/22 |

## 판정 — diversification 기각 (14번째 레버 소진)

1. **cap1/2/3 모두 base와 동일 (78/79)** — 규칙 슬롯 구성은 op performance 무영향
   - 0콜 시뮬의 "gold top5 19→70"은 **노출 기준 계산**이었고, 실제 lift 로직에선 JEV가 60개에서
     gold를 고르므로 노출 구성이 hit을 바꾸지 않음 (시뮬-실측 괴리 교훈)
2. **live block abstain 전부 0** — diversification으로 라이브 무답 방어 불가 최종 재확인
3. **production-exact hit@1 = 78 확정** (시간 필터 무관) — v4 평가 결론 전부 유지
4. 중간에 "hit@1 18"으로 보인 것은 gold_after 계산 로직 버그 — stage56 표준 lift로 정정

## 교훈

- **0콜 노출 시뮬레이션 ≠ JEV lift 실측** — "top5 진입" 지표는 JEV가 60개에서 고르는 실제와 다름.
  이후 슬롯/구성 실험은 JEV 실측 전제 (또는 따로 "노출 전" 지표로 명시).
- **JEV 입력 60개 유지 + 노출 구성 변경은 hit@1에 영향 없음** (JEV가 lift하기 때문).

## raw

- `data/stage86_diversification.json` (4조건 × 150 = 600 레코드, run3 최종)
- 러너: `stage86_diversification.py` (build_slot_exposure + stage56 lift 로직)
- 로그: `data/stage86_run3.log`