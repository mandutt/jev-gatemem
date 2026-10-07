# STAGE83 — 60 vs 5 candidate control: confound 분리 확정 (2026-10-07, 360콜, err 0)

> 3종 AI v4 검토(c-ai 필수 제안) — 10-06(abstain 0/60, JEV 60 후보) vs 10-07(abstain 36/38, JEV 5 후보)의
> confound를 같은 세션에서 후보 수만 60/5로 바꿔 분리했다.

## 결과 (live60, 같은 세션, 3-run)

| 조건 | block abstain (3-run) | valid+yes 오차단 | abstain_p 중앙 |
|---|---|---|---|
| **k60** (production = stage48 조건) | 0 / 0 / 0 (0/38) | 0 / 0 / 0 | **0.00** |
| **k5** (stage61~66 조건) | 36 / 36 / 36 (36/38) | 2 / 2 / 2 | 0.84~0.86 |

- 3-run 전부 0플립 — 결정적
- same snapshot / same query / same prompt / same model / **only candidate count 60 vs 5**

## 결론

1. **"10-07 모델/서버 변경으로 abstain이 작동" → 기각**
   - k60(production)에서 abstain 여전히 0/38 — JEV 모델/서버는 10-06과 동일
2. **abstain 유발 요인 = JEV 입력 후보 수 (60→5)** — b-ai "후보 수가 abstain 민감도 지배" 추측이 **실측으로 입증**
3. **10-06 "abstain 무력"(60 후보) 결론 유효** — production은 abstain이 안 나옴 (회귀 아님, 운영 정상)
4. **stage60~66(k=5) 전부 인공물로 확정** — "정직 abstain"·"노출 한계"·"캡1 트레이드오프"는
   production(60 후보)에 적용 불가. 단, "candidate count → abstain" 관계는 실측 발견으로 유효

## 함의 (차기 레버)

- 후보 수 축소(60→20 등)는 abstain을 유발할 수 있음 — **pool20 채택 시 이 효과를 함께 평가해야 함**
  (b-ai: 후보 수 곡선 {5,10,20,40,60}로 최적점 — pool20 판정 + abstain 관계 동시 도출)
- **candidate diversification** (c-ai): 60개 유지 + 규칙 2~3 + 사실 2~3 구성 — abstain 유지 + 사실 회수
  (k=5 인공물 아님 — 60 후보 기반 실험으로 재설계 필요)
- stage61~66 러너의 `rows[:5]`는 **실험 설계 오류** — 이후 러너는 JEV 입력 후보 수를 운영(60)과 일치시킬 것

## raw

- `data/stage83_60vs5_control.json` (3-run × 2조건 × 60 = 360 레코드)
- 러너: `stage83_60vs5_control.py` — k 파라미터로 60/5 전환
- 로그: `data/stage83_run.log