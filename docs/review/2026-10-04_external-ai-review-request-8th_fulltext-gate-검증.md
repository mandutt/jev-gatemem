# 외부 AI 검토 요청 — full-text Winner Gate 도입 검증 (2026-10-04, 8차)

- **작성일**: 2026-10-04
- **요청자**: jev-memory-middleware (개인 운영 시스템) 개발자
- **문서 성격**: **자가완결형**. 수신 AI는 저장소·논문 접근 권한이 없으므로, 시스템 구조·비교 대상·전체 실측 이력을 이 문서 안에 모두 기술했습니다. **다른 정보 없이 이 문서만으로 판단 가능합니다.**
- **주의**: **"jev-mem"(본인)과 "Jev-Mem"(arXiv 2609.23986)은 서로 다른 프로젝트입니다.**

---

## 0. 목적 — "3종에서 배울 점을 실측으로 검증해 반영"

이 검토의 궁극 목적은 jev-mem의 강점 방어가 아니라, **타 메모리 프로젝트 3종(Mnemon / Jev-Mem / PerfectRecall)에서 배울 점을 찾아 우리 프로젝트에 실제로 반영**하는 것입니다. 7차 검토(3개 AI)에서 **"1위 후보를 한 번 더 직접 검증하는 게이트"**(Mnemon식 2단계 검증)가 공동 1순위로 제안됐고, 이후 **8개 실측**으로 검증·재설계를 진행했습니다. 본 문서는 그 전 과정과 최종 제안 구조를 정리하고, **프로덕션 통합 전 최종 검토**를 요청합니다.

---

## 1. 시스템 개요 (jev-mem)

Hermes(로컬 AI 에이전트) 메모리 파이프라인의 미들웨어. Windows 11, CPU 전용(RAM 15.6GB), Docker 불가.

### READ PATH (J1 rerank)
```
[사용자 질의] → lane pool: FTS(60)+vector(60)+importance(8)+graph(10)
  → RRF(k=30) 병합 → conservative gate(어휘 중첩) → Jev choice 1콜
  → winner lift / abstain("No candidate is usable evidence")
```
- choice 후보: 최대 40개, excerpt **120자** (`EXCERPT_LIMIT`, 프로덕션 기본값)
- abstain 시 빈 컨텍스트("메모리 없음")
- Jev 실패 시 pool 순서 fallback (예외 미전파)

### WRITE PATH
- 턴당 Jev 2콜 (store 판정 + 13종 type 분류), 규칙 기반 KEEP/SKIP, fail-open

### 핵심 실측 수치 (7차까지)
| 항목 | 값 |
|---|---|
| op 90쿼리 hit@3 (A choice) | 80.0% (5차 85.6%와 Wilson 구간 중첩) |
| LGO(정답 제거) acceptance | 41.1% → **사람 판정 후 실제 해로운 오주입 5.6%** |
| fresh noans FP | 12.0% → **사람 판정 후 2.0%** |
| 6차 "τ=0.65 검증" | **철회** (쉬운 noans 세트 인공물) |

---

## 2. 비교 대상 3종 (핵심만)

| 시스템 | write-time | read-time | 특징 |
|---|---|---|---|
| **Mnemon** | Jev 0회, raw 저장 | System 2 쿼리 생성 + Jev 다중 yes/no 판정 (질문당 5~10콜, waves) | record-level 판정 — "검색했으면 evidence인지 다시 판단" |
| **Jev-Mem** | 전부 보존(admission OFF) + 그래프 | 적응형 폐루프 (최대 16콜), evidence_sufficient / missing_evidence | 증거 충족도/결손 별도 판단 |
| **PerfectRecall** | gate 없음 | 전체 코퍼스 스캔 → 전 후보 Jev 판정 (쿼리당 10콜) | exhaustive 판정, 임베딩 없음 |

**7차 검토에서 3개 AI 공동 결론**: "관련 memory를 찾는 것"과 "그 memory가 실제 질문의 evidence인지 판정하는 것"을 분리할 가치 검증 — **Winner Entailment Gate**(Mnemon식)가 1순위 제안.

---

## 3. 7차 검토 이후 진행 실측 (8단계, 전부 FREE 레인 0원)

### ① 문서 오류 10건 수정 (b AI 지적)
payload_json NULL 실측 반영, Acc@1 갱신, §3.1/3.2 전사 오류 정정, hit@3 5건 변동, LGO 명칭 → "hard-negative acceptance rate(상한)" 등.

### ② 0콜 오프라인 파레토 분석 — **τ 단독 게이트 기각**
```
규칙: A choice 선택 + pointwise max_score < τ → 강제 abstain (τ 스윕)
```
| τ | op hit@3 | LGO acc | noans FP |
|---|---|---|---|
| 0.0 (=A) | 80.0% | 41.1% | 12.0% |
| 0.65 | 71.1% | 28.9% | 6.0% |
| 0.70 (5% 충족) | 67.8% | 23.3% | **2.0%** |
| 0.90 | 18.9% | 2.2% | 0.0% |

→ **단순 pointwise τ 게이트로는 5% 가드레일 달성 시 hit@3 급락 (-12pp). 기각.**

### ③ Winner Entailment Gate 파일럿 (43콜) — "1위 후보 직접 답인가" YES/NO
대상: LGO 37건 + noans 6건 (A choice가 선택한 전 건). excerpt **평균 79자**로 판정.
결과: NO 30/43 (69.8%), 오차 0건. noans 6건 전부 NO (완벽 차단).

### ④ 수동 3분류 판정 (사용자 43건) — **7차 오주입률 과대평가 증명**
사람이 43건을 VALID/PLAUS/IRREL로 판정:
| 조건 | VALID | PLAUS | IRREL |
|---|---|---|---|
| LGO | 32 | 5 | 0 |
| noans | 5 | 1 | 0 |

- **해로운 오주입률 = PLAUS/전체: LGO 5.6% [2.4-12.4], noans 2.0% [0.4-10.5]** — 7차의 "41.1%/12.0%"는 선택률이지 오주입이 아니었음 (86.5%가 정당한 대체 증거)
- Winner Gate 교차: **gate YES precision 100%** (13/13), but **과다거부 80%** (NO 30건 중 24건이 사람 VALID)
- → **단독 게이트 abstain은 운영 hit@3를 크게 깎을 것**

### ⑤ gate 재설계 오프라인 시뮬레이션 — R2 규칙
관찰: gate NO + 사람 VALID(오탐)의 pointwise score가 높음(0.52~0.9) → **score 조건부 완화**
```
R2: gate=YES → 주입
    gate=NO & score≥θ → 주입 (pointwise 확신)
    gate=NO & score<θ → abstain
```
θ=0.7: LGO PLAUS 1건 누출, VALID 차단 10 (gate_only 19의 절반)

### ⑥ full-text 재실험 (43콜) — **excerpt 절단이 게이트 성능 악화 증명**
사용자 지적: "100자 내외로는 사람도 판단 어려움 → 게이트도 동일?" → DB 원문 전문으로 재판정:
| | excerpt 80자 | full-text |
|---|---|---|
| 판정 변화 | — | **6건 NO→YES (전부 사람 VALID — 잘린 꼬리에 답)** |
| PLAUS 누출 | 0 | 0 |
| VALID 과다거부 | 24 | 18 (-25%) |

### ⑦ full-text 게이트 op 적용 (80콜) + 토큰 캡 설계
**op 90건 non-abstain 80건에 full-text 게이트 적용:**
| 적용 | hit@3 |
|---|---|
| A 단독 | 72/90 (80.0%) |
| **+ 게이트 (R2 θ=0.5)** | **72/90 (80.0%) — 0손실** |
| + 게이트 (θ=0.6~0.7) | 71/90 (78.9%) |

게이트: YES 75 / NO 5 / err 0.

**토큰 부담 실측** (운영 DB 1,627건): p50 340자(238tok), p90 1,423자(996tok), **max 107,885자(75,520tok — 로그 덤프)** → full-text 무제한은 토큰 폭탄. 캡 800자에서 현 코퍼스 판정 손실 0건 + max 차단. **`GATE_FULLTEXT_LIMIT=800` 채택.**

### ⑧ noans 선택 대상 재검증 — **중대 발견 + θ 결정**
- **exp7d가 choice 선택 id 미저장** → 기존 noans 게이트(③⑥)는 pointwise top1을 대용 → **6건 중 3건이 완전히 다른 메모리였음** (기존 noans gate 결과 무효)
- 결정적 파이프라인으로 pool 재현 → choice 실제 선택 복원 → full-text 게이트 재실행 (exp7i, 6콜): **YES 2 / NO 4** → noans FP **6/50 → 2/50 (4.0%)** — 5% 가드레일 충족 (YES 2건은 사람 VALID와 일치)
- θ 스윕 (LGO+noans, 사람 판정 기준):
| θ | LGO PLAUS | LGO V차단 | noans PLAUS | noans V차단 | op hit@3 |
|---|---|---|---|---|---|
| 0.4 | 3 | 2 | 1 | 0 | — |
| **0.5** | **3** | **3** | **0** | **0** | **80.0% (0손실)** |
| 0.65 | 3 | 5 | 0 | 1 | 78.9% |
| 0.7 | 1 | 7 | 0 | 3 | 78.9% |

→ **θ=0.5 채택** (op 80.0% 완전 보존 + noans FP 4.0% + LGO PLAUS 3건만 누출. θ=0.7은 PLAUS 1건 더 막지만 op 1건+VALID 4건 추가 희생)

---

## 4. 최종 제안 아키텍처

```
A(choice) 1콜 (excerpt 120자, 기존) → winner 선정
  ↓
full-text 게이트 1콜 (원문 ≤800자): "Does this memory directly state or entail
  the answer to the question? YES if it contains the specific fact/value/rule
  the question asks for. NO if only topic/keywords/background."
  ↓
R2 주입 규칙 (θ=0.5):
  gate=YES           → 주입
  gate=NO & score≥0.5 → 주입 (pointwise 확신)
  gate=NO & score<0.5 → abstain
```

| 지표 | A 단독 | **A + 게이트 (θ=0.5)** |
|---|---|---|
| op hit@3 | 80.0% | **80.0% (0손실)** |
| noans FP | 12.0% (6/50) | **4.0% (2/50)** ✓ 5% 가드레일 |
| LGO harmful FP | 5.6% (5/90) | 3.3% (3/90) |
| 추가 비용 | — | 쿼리당 1콜 × ≤800자 (FREE 0원) |
| 추가 지연 | — | ~0.23s (choice 실측 latency) |

---

## 5. 검토 요청 (Q1~Q6)

### Q1. 최종 아키텍처 (full-text 게이트 + R2 θ=0.5)의 타당성
**(a)** 통합 승인 — 실측이 모든 지표를 뒷받침 (op 0손실, noans 가드레일 충족)
**(b)** θ 재검토 필요 — θ=0.5의 LGO PLAUS 3건 누출이 우려, θ=0.65~0.7 채택
**(c)** 게이트 자체 재설계 — "직접 답" 판정이 너무 보수적/진보적

### Q2. 토큰 캡 800자의 적절성
**(a)** 적절 — p50 340자, 현 코퍼스 판정 손실 0건, max 차단
**(b)** 상향 필요 — p90 1,423자도 통째로 보내야 함 (캡 1,500자)
**(c)** 하향 가능 — 500자도 실측상 1건만 위험

### Q3. noans 검증 방법론 (결정적 pool 재현)
exp7d가 choice id 미저장 → 결정적 파이프라인(임베딩+RRF)으로 pool 재현 → choice 인덱스로 후보 복원. **재현 pool 크기가 raw와 4/6건 정확 일치** (2건 1개 차이 — 코퍼스 변화로 추정).
**(a)** 방법론 타당 — 결정적 파이프라인 재현은 표준 절차
**(b)** 재실험 필요 — 2건 불일치는 코퍼스 스냅샷 차이로, 같은 스냅샷에서 재실행해야 함
**(c)** choice id 저장하도록 실험 코드 수정이 선행

### Q4. 운영 통합 전 추가 확인 사항
**(a)** 통합 바로 진행 — 남은 리스크는 운영에서 shadow로 관찰
**(b)** shadow 병행 — 게이트를 shadow 모드로 N일간 병행 후 전환
**(c)** 추가 실측 — op 90건 3회 반복 + gate 적용, roster 포함 전체 재측정

### Q5. [3종 관점] 이 설계가 3종의 어떤 아이디어를 제대로/못 살리고 있나
Mnemon(record-level 판정), Jev-Mem(evidence_sufficient), PerfectRecall(exhaustive) 중
이 설계가 실제로 흡수한 것과 **아직 흡수 못 한 가치 있는 아이디어** 판정.
특히: 게이트 1콜이 Mnemon의 "5~10콜 waves"와 비교해 어떤 질문 유형에서 부족할지.

### Q6. 통합 후 예상되는 운영 리스크 Top 3
게이트 오판정(과다거부 잔여 3건/VALID 차단), 토큰 비용(크레딧 레인 전환 시),
지연 증가(~0.23s 추가), noans 2건 YES 통과(남은 FP) 등 — 실제 운영에서 가장 먼저
만날 리스크와 모니터링 지표 제안.

---

## 6. 핵심 데이터 파일 (참고)

| 파일 | 내용 |
|---|---|
| `experiments/operational-golden/data/exp7f_winner_gate_raw.json` | 43건 excerpt 게이트 + 후보 |
| `experiments/operational-golden/data/exp7g_gate_fulltext_raw.json` | 43건 full-text 게이트 |
| `experiments/operational-golden/data/exp7h_op_gate_raw.json` | op 90건 full-text 게이트 (80콜) |
| `experiments/operational-golden/data/exp7i_noans_gate_fix_raw.json` | noans 6건 choice-fix 게이트 |
| `experiments/operational-golden/data/exp7d_choice_repro.json` | noans choice 실제 선택 재현 |
| `Downloads/wgate_3class_verdicts.json` | 사용자 수동 3분류 43건 |

---

*커밋 이력: ad01032(문서 10건) → d902048(파레토) → 6d5a417(게이트 파일럿) → e431b1e(수동 판정) → 572b1ec(R2 설계) → de0d8ab(full-text 재실험) → 00192d1(종합+토큰 캡) → f0f79b9(θ 결정+noans 검증). 전부 FREE 레인 ($0).*