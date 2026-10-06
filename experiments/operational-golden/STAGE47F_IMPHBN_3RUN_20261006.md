# stage47f: imphbn 3-run 재검증 — WHY 구제 확정, gold50 손실은 라벨 문제 (2026-10-06)

stage47e 1-run의 imphbn(improved 라벨 + head150+겹침150 non-overlap) 우위를
3-run majority로 재검증. 6쿼리 × 3회 × 2 cond = 36콜.

## 결과 (majority = 2/3)

| 쿼리 | cur | imphbn | 판정 |
|---|---|---|---|
| 코덱스 WHY | 0/3 | **3/3** | ✅ imphbn 구제 확정 |
| 마우스 WHY | 0/3 | **3/3** | ✅ imphbn 구제 확정 |
| pi 프록시 | 0/3 | **3/3** | ✅ imphbn 구제 확정 |
| gemini 별칭 | 3/3 | 3/3 | = head 보존 확정 |
| codex CLI | 3/3 | 3/3 | = head 보존 확정 |
| **gold50 기준선** | **3/3** | 0/3 | 🔻 imphbn 열위 |

## 해석

1. **WHY 3건 구제 = 3-run 100% 일관** (cur 전부 abstain, imphbn 전부 hit) —
   1-run 착시가 아님. head+겹침 윈도우의 실재 효과.
2. **head 정답 보존 확정** (gemini/codex 양쪽 3/3) — win150 약점 해결.
3. **gold50 손실 1건 = improved 라벨 고유 효과** (0콜 확인):
   - gold50 gold는 329자 "운용 관측 중·추정치" 텍스트. cur 라벨 abstain_p 0.17~0.19
     (통과) vs improved 라벨 0.33~0.36 (0.3 초과 → abstain).
   - **excerpt가 아니라 라벨 문구 문제** — improved가 "specific fact/value/version"을
     요구해 불확정·추정 텍스트를 답으로 인정 안 함. 사안 1의 WHY 손실과 동일 부류.

## 결론 — 최종 후보: current 라벨 + head겹침(non-overlap)

- imphbn의 WHY 3건 구제는 **윈도우(head+겹침) 효과**, gold50 손실은 **improved 라벨 효과**
- 두 효과는 독립 → **current 라벨 + head겹침** 조합이면:
  WHY 3건 구제(윈도우) + gold50 보존(라벨) + noans 방어(윈도우) 모두 가능할 것
- 1-run으로 검증 필요 (140콜): cur 라벨 + head겹침 vs cur(현행)

## raw

- `data/stage47f_imphbn_3run.json` (36 레코드)
- 러너: `stage47f_imphbn_3run.py`, 로그: `stage47f_run.log`