# STAGE61 — 오늘(JEV 모델 변경 후) base 기준선 재확인 (2026-10-07, 60콜) ★게임체인저

> stage60(k 실험)에서 abstain_p가 어제(0.0 중앙)와 극단적으로 다름(0.95) — JEV 서버/모델 변경 의심.
> 오늘 모델에서 base(k5, current 라벨, 시간 필터)를 라이브 60으로 재실행.

## 결과 — 어제 vs 오늘 (같은 쿼리·라벨·k=5·스냅샷)

| | 어제(stage48, 10-06) | 오늘(stage61, 10-07) |
|---|---|---|
| block abstain | 0/38 (0%) | **36/38 (94.7%)** |
| valid+yes 오차단 | 0/22 | 2/22 (아래 재해석) |
| abstain_p 중앙 | 0.000 | **0.860** |
| chose_abstain (실제 abstain 라벨 선택) | 0/60 | 38/60 |
| abstain_p > 0.3 | 0/60 | 38/60 |

## 오차단 2건 — **라벨(49c) 문제로 재해석 (실질 오차단 0)**

1. `Hermes 데스크톱 워치독 런처 어디 있어?` (yes) — 답(런처 경로)이 **pool에 없음** (cands = 규칙 행뿐).
   JEV abstain이 오히려 정확 — 49c의 "yes"는 대화 맥락 기준이었을 가능성.
2. `코드 설명과 구조 라벨 언어 규칙?` (valid) — cands에 "언어 규칙" 직접 답 없음. 동일.

→ **노출 top-5에 답이 없는 yes/valid는 "라벨이 너그러운" 케이스. JEV abstain이 맞는 판정.**

## pick 유지한 block 2건 (잔여 약점)

- `리뷰 전용 턴에서 커밋해도 돼?` (ap 0.23)
- `verifier-pilot은 코딩 품질만 보면 돼?` (ap 0.28)
- → abstain 직전(τ 0.3) — "규칙 행에 답이 실제로 있는" 것처럼 보이는 block 케이스.

## 의미 — ★어제의 "abstain 무력" 결론 뒤집힘

- **JEV 모델/서버가 10-06 밤~10-07 사이 변경** → abstain 라벨을 실제로 선택하기 시작.
- 오늘 모델 기준: **라이브 무답 94.7% 차단 + 실질 오차단 0** — u_true=29.8% 환경에서
  **오주입률 ~30% → ~2%** 로 급감 가능.
- **stage48~59의 "abstain 무력·레버 전수 소진" 결론은 전부 어제 모델 기준 — 재검토 필요.**

## ⚠️ 검증 필요 (다음 단계)

1. **3-run 안정성**: 오늘 abstain이 일시적 서버 상태인지, 안정적인지 (180콜)
2. **op-90 회귀**: abstain이 강해지면 WHY(원인) 질문 등 op 정답도 abstain될 위험 — op-90 재실행 (360콜)
3. **noans hard 50**: 하드 noans FP도 abstain 증가로 더 줄어드는지 (→ 150콜)
4. 오늘 모델에서 **hard noans vs live IRREL** 분리 재확인 — "구조적 한계"가 실제로 해소됐는지

## raw

- `data/stage61_base_recheck.json` (60 레코드, abstain_p·chose_abstain 포함)
- 러너: `stage61_base_recheck.py`
- 대조: `data/stage48_live60_cross.json`