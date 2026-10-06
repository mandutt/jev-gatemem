# 외부 AI 검토 요청 — jev-mem 라이브 무답 차단 한계 (판정자 관점, 2026-10-06)

- 목적: 라이브 무답 질문의 오주입을 JEV(SystemOne)로 막을 수 없음이 9종 레버 실측으로 확정됨.
  남은 선택지의 판단을 외부에 자문.
- 전제: 아래 모든 수치는 실측(raw JSON·러너 포함). **추가 정보 없이 답변 가능하도록 자족적으로 기술.**

## 1. 시스템 요약

- 파이프라인: SQLite 메모리(1,721+113행) → 4-lane RRF(FTS5+vec+importance+graph) → 게이트 → pool 60
  → JEV(SystemOne API) choice 1콜 rerank → abstain 시 빈 컨텍스트, pick 시 **top-5 노출**
- 임베딩: bench/bekko-a8m (384d, 로컬 fastembed) / 일반 LLM 사용 금지 원칙 (JEV 전용)
- soft gate: choice의 abstain 라벨 확률 > 0.3 → 빈 컨텍스트 (현재 라이브에서 dead code — 아래)

## 2. 핵심 실측 (stage48~50b, 모두 스냅샷 고정 + 데몬 venv)

### 2.1 라이브 60쿼리 사람 라벨링 (2회 보강 완료)

- 원래 라벨: 답 있음 35 / 답 없음 22 / 모호 3
- 보강 1 (해로움·정답노출): no 22건 = **IRREL 15 / PLAUS 2 / VALID 5**,
  yes 35건의 top-5 정답 포함 = **YES 16 / NO 19**
- 보강 2 (rank 6~60 스캔): yes-NO 19+2건 = **IN 21/21** — 답이 전부 pool 안 rank 8~9에 존재
- **u_true 보정 = 29.8%** (17/57)

### 2.2 라이브 실태 3분할 (57 유효 쿼리)

| 상태 | 비율 | 원인 |
|---|---|---|
| 정답 노출 | 37% | — |
| **해로운 오주입** (IRREL+PLAUS) | **30%** | abstain 무력 |
| **답 있는데 놓침** | **33%** | rerank 실패 (답 rank 8~9) |

### 2.3 abstain 무력 확정 (측정 오염 배제 완료)

- 리플레이 abstain 0/60 — **자기참조 누수 기각**(복제 0건), **시점 필터 후에도 0**(135행 배제),
  **win-300 증폭 기각**(head-100에서도 0), trace 잔존 라이브 이벤트도 abstain_p 0.12~0.13 저값
- abstain_p 분포: 0.00~0.17 — **soft gate τ=0.3은 라이브 dead code**

### 2.4 소진된 레버 9종 (전부 실측 기각)

1. abstain 라벨 문구 2종 (improved: 골든 noans FP −5, 라이브에서는 1/60뿐)
2. excerpt 윈도우 8종 (win150/head+겹침/개선 라벨 조합 — 3-run에서 전부 순손실)
3. soft gate τ (abstain_p≈0이라 무효)
4. noul 구조 (1콜 hybrid/2콜 재선택 — 골든 기각)
5. **noul 프롬프트 3종** (아래 §3)
6. retrieval floor (pool[0] sim<0.25: IRREL 77% vs 정답 49% — 분포 겹침, 분리 불가)
7. 시점 필터 (효과 없음)
8. 게이트 완화 (pool 확보 목적, 완료)
9. 쿼리 확장 write/read-path (복구 0/10, 2/11+오염)

## 3. 결정적 실측 — noul이 라이브 무답을 못 잡는 이유

200쿼리 × 1콜(choice+noul30 병렬)에서 cls별 **noul_top 중앙값**:

| 클래스 | noul_top |
|---|---|
| 골든 noans (이웃 부재형 무답) | **0.26** — 완벽 분리 |
| **라이브 IRREL (이웃 존재형 무답)** | **0.91** |
| 라이브 VALID (실제 답) | 0.94 |
| op 정답 | 0.92~0.94 |

- noul 프롬프트 3변형으로도 간격(op−irrel) +0.03~+0.07 — 분리 불가
  (v2 "same-topic is NOT an answer"는 오히려 정답(0.83)을 무답(0.87)보다 낮게 깎는 역전)
- **해석**: 라이브 무답 질문은 "주제가 겹치는 과거 기록"이 존재하고, JEV는
  "이 후보가 질문 주제를 다룬다"를 answerability로 오판. relevance와 answerability의
  구분이 모델 수준에서 불가.
- 단, 골든 noans(명백 무답)는 noul_top<0.5로 **FP 50→8 (op 손실 5)** — 회귀 방어용으로 유효

## 5. 자문 사항

0. **〔신규: rerank 실패 축의 재규명〕답 있는데 top-5에 답이 없는 33% 손실에 대해**:
   stage49d pool-in-pool 스캔(21/21 IN)을 "답이 rank 6~60 = rerank 실패"로 해석했으나,
   후속 0콜 실측(stage50c/d)에서 이 pool이 **시점 필터 적용 평가용 pool**임이 밝혀졌고,
   **실운영 pool(시점 필터 없음)에서는 답이 RRF 1~3위**(18건 중 15건)였다. 즉 RRF 병합·lane은
   답을 이미 상위로 정렬하고 있고, **진짜 실패 지점은 JEV choice가 답(1~3위)을 못 고르는 것**이다.
   - 이 답(1~3위)을 JEV가 놓치는 원인이 무엇이라 보는가? (choice의 relative competition이
     60개 pool에서 답을 1위로 못 올리는 구조적 한계인지, 아니면 다른 이유인지)
   - "RRF 상위 1~3위를 choice 없이 그대로 노출"하는 정책(choice를 우회)의 가치는? 실제로
     JEV choice lift가 RRF 상위 1~3위보다 나은 경우와 나쁜 경우가 있는지(0콜 가능한지 포함)

1. **라이브 IRREL(이웃 존재형 무답) 차단이 정말 불가능한가?** — 위 9종 레버가 모두 실패한
   조건에서, JEV(SystemOne의 choice/noul 프리미티브)만으로 남은 방법이 있는가?
   (예: 질문 분해, 2단계 질문 구조, 후보 그룹화, 대조적 프레이밍 등)
2. **부분 채택 판단** — noul_top<0.5 게이트를 골든셋 회귀 방어로만 운영 반영하는 것(noans FP
   50→8, op −5, 라이브 영향 약간)의 손익은? op −5(정답 5건 abstain)의 h가 높다면 위험한가?
3. **rerank 실패 축 —〔수정된 실측 반영〕** 원래 "답이 rank 8~9"로 본 것은 시점 필터 평가용 pool의
   인공물이었고, 실운영 pool에서는 답이 RRF 1~3위다. 즉 rerank 실패는 "답이 상위인데 choice가 못 고름"
   형태다 — JEV choice를 우회하고 RRF 상위 1~3위를 그대로 노출하는 정책의 가치(0번 질문)와,
   choice가 1~3위 답을 놓치는 이유에 대한 추가 견해를 부탁드린다.
4. **판정자 교체** — 일반 LLM 금지 원칙을 유지한다면 사실상 소진인가? 원칙의 근본 이유는
   비용·속도(jev는 저렴·빠름)인데, "오주입 30%의 해로움"과 비교하면 원칙 재검토가 정당한가?
5. **수용 판단** — IRREL 15건(26%)을 상시 노이즈로 수용하는 것이 top-5 노출 구조에서
   에이전트 품질에 미치는 영향은? 노출 수 축소(top-5→2)는 C AI가 반대한 바 있음
   (틀린 후보의 양만 줄임) — 이 견해에 동의하는가?

## 5. 참조 (필요 시)

- 종합: `experiments/operational-golden/RECALL_ABSTAIN_INVESTIGATION_20261005.md` §9~13
- raw: `data/stage48_live60_cross.json`(라이브 교차), `stage49a_leak_diagnosis.json`(누수 진단),
  `stage49b_timeconsist.json`(시점 일관 540콜), `stage49c/d`(라벨 보강·pool 스캔),
  `stage50_noul_answerability.json`(200), `stage50b_noul_prompt_variants.json`(300)
- 러너: `experiments/operational-golden/stage4x~50*.py`
- 판정 JSON: stage49c(60건 해로움/정답노출), stage49d(21건 IN/OUT) — 사용자 제공본

## 요청 형식

각 질문별 ① 판정 ② 근거(위 실측 인용) ③ 구체 다음 실험 설계(콜 수 포함)를 부탁드립니다.
```
