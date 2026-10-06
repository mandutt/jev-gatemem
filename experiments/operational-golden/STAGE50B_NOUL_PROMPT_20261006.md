# stage50b: noul 프롬프트 변형 — 라이브 IRREL 분리 시도 (2026-10-06, 300콜, err 0)

> stage50에서 noul이 골든 noans(0.26)는 완벽 차단하지만 라이브 IRREL(0.91)은 못 잡는 것이 확인됨.
> "answerability vs relevance 구분 실패" 가설 하에 프롬프트 3변형을 실측.

## 설계

- 벤치: live 60 (IRREL 15/PLAUS 2/VALID 5/yes_miss 35/maybe 3) + op 20 + noans 20 = 100쿼리
- 변형 (상위 30 후보 × noul 1콜/쿼리):
  - **v1_cur**: "directly state or entail the answer" (현행)
  - **v2_spec**: "specific fact/value/version/date/decision — same-topic mention is NOT an answer"
  - **v3_abs**: 역방향 부재 판정 (1 = fully answers, 0 = absent/only topically related)
- 러너: `stage50b_noul_prompt_variants.py`, raw: `data/stage50b_noul_prompt_variants.json`

## 결과 — cls별 noul_top 중앙값

| cls | v1_cur | v2_spec | v3_abs |
|---|---|---|---|
| live_irrel | 0.91 | 0.87 | 0.85 |
| live_plaus | 0.72 | 0.70 | 0.73 |
| live_valid | 0.94 | 0.83 | 0.88 |
| live_yes_miss | 0.94 | 0.90 | 0.91 |
| op | 0.94 | 0.90 | 0.92 |
| noans_hard | 0.34 | 0.29 | 0.29 |

- **분리 간격 (op−irrel)**: v1 +0.03 → v2 +0.03 → v3 +0.07 — **프롬프트로 간격이 벌어지지 않음**
- v2는 오히려 valid(0.83)가 irrel(0.87)보다 낮아지는 역전 — **구체성 강조가 정답까지 같이 깎음**

## τ 게이트 평가 (합격선: IRREL ≥5 차단, 희생 ≤1)

| 변형 | 최적 τ | IRREL 차단 | 보호 희생 |
|---|---|---|---|
| v1_cur | 0.8 | 2/15 | 6 |
| v2_spec | 0.65 | 2/15 | 5 |
| v3_abs | 0.8 | 3/15 | 11 |

- **3변형 모두 합격선 미달** — IRREL 최대 3/15, 희생은 그때마다 5~11건
- 희생 없이(≤1) IRREL ≥5를 만드는 τ는 존재하지 않음 (irrel 분포 0.85~0.91과 보호 분포 0.88~0.94가 완전 겹침)

## 판정 — **noul 프롬프트 개선 기각**

1. 프롬프트를 어떻게 쓰든 JEV는 "라이브 무답 질문 + 주제 근접 이웃" 조합에서 noul 0.85+를 부여.
   이는 **모델의 판정 한계** — relevance와 answerability를 프롬프트 수준에서 분리 불가.
2. stage50(구조 실험)·stage50b(프롬프트 실험)를 통해 **noul 경로 완전 소진**:
   - 골든 noans(하드, 이웃 부재형)는 τ=0.5로 FP 50→8 — **단, 이는 이미 noans 셋 특성이 쉬운 것**
   - 라이브 IRREL(이웃 존재형 무답)은 **choice·noul·문구·excerpt·시점 필터 전부 무효**
3. 남은 유효 레버: ①**새 모델/판정자**(일반 LLM 금지 원칙과 충돌) ②**수용**(IRREL 15건=26% 노이즈 상시 노출)
   — 단, noans_hard τ=0.5 (FP 8, op 손실 5)는 **골든셋 회귀 방어용으로는 유효**하므로 운영 적용 가치는 별도 판단.

## 결론

라이브 IRREL 차단은 **JEV(SystemOne) 단일 모델 판정으로는 불가능**하다고 판정하는 것을 지지.
2026-10-06 기준 소진된 레버: abstain 라벨 문구·excerpt 윈도우 8종·soft gate τ·noul 구조(1콜/2콜)·
noul 프롬프트 3종·retrieval floor·시점 필터. **남은 것은 수용 또는 판정자 교체뿐.**

## raw
- `data/stage50_noul_answerability.json` (200쿼리 1-run, err 0)
- `data/stage50b_noul_prompt_variants.json` (300콜, err 0)
- 러너: `stage50_noul_answerability.py`, `stage50b_noul_prompt_variants.py`
