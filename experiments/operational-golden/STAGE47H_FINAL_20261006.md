# stage47h: imphbn vs curhb 3-run 교차 검증 — 두 후보 모두 기각 (2026-10-06)

stage47e/g 1-run에서 유망했던 head+겹침(non-overlap) 두 변형의 최종 3-run 검증.
6쿼리 × 3회 × 3 cond = 54콜.

## 결과 (majority = 2/3)

| 쿼리 | cur | imphbn | curhb |
|---|---|---|---|
| gold50 기준선 (op) | **3/3** | 0/3 | **3/3** |
| 주석 영어 규칙 (noans) | **3/3 방어** | 0/3 FP | 0/3 FP |
| 테스트 생략 커밋 (noans) | **3/3 방어** | **3/3 방어** | 0/3 FP |
| 로그 한국어 (noans) | **3/3 방어** | **3/3 방어** | 1/3 FP |
| browser.backend (noans) | **3/3 방어** | 2/3 방어 | 0/3 FP |
| Exa (op, pool 밖) | 0/3 | 0/3 | 0/3 |

## 해석

1. **curhb(현재 라벨+head겹침) 규칙형 noans 방어 붕괴** — 규칙 확인형 4건 모두
   FP (0/3~1/3). 1-run stage47g의 FP 24(+3)는 **과소평가** — 3-run에서 4건 전부
   오주입 확정. head+겹침 윈도우가 "규칙 확인 질문"에 정답처럼 보이는 head(질문
   서술)+겹침 메모리를 만들어내는 것이 실재.
2. **imphbn(improved+head겹침) gold50 붕괴** — op 정답 1건을 0/3 abstain (improved
   라벨이 "추정치" 텍스트 거부). 이는 stage47f에서 확인된 대로.
3. **WHY 3건 구제는 두 후보 모두 유효했지만**, 대가가 큼:
   - curhb: 규칙형 noans 4건 오주입 (+4 FP)
   - imphbn: gold50 1건 손실 + (stage47e에서 규칙형 일부 FP)
   - WHY 3건(코덱스/마우스/pi) vs 규칙형 4건+gold50 1건 → **순손실**

## 판정 — head+겹침 계열 기각 확정

- **curhb 기각**: 규칙형 noans 방어 붕괴 (4건 FP)
- **imphbn 기각**: gold50 3/3 abstain (op 정답 손실)
- **현행(cur, 300→150 절단 + current 라벨) 유지** — WHY 3건을 포기하지만
  규칙형 noans 3/3 방어 + gold50 보존이 유일하게 균형
- WHY 질문 구제는 **excerpt가 아니라 다른 레버**(프롬프트/라벨/사후 처리)로만
  가능 — win150·head겹침 계열 전부 소진 (do not re-run)

## raw

- `data/stage47h_imphbn_curhb_3run.json` (54 레코드)
- 러너: `stage47h_imphbn_curhb_3run.py`, 로그: `stage47h_run.log`
- 연쇄: stage47(win150) → 47b(3-run 기각) → 47c(improved+win150) → 47d(head+겹침)
  → 47e(non-overlap) → 47f(imphbn 3-run) → 47g(curhb) → 47h(최종 기각)