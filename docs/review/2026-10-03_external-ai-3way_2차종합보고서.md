# 외부 AI 3개 2차 검토 종합 보고서 — "종합검증보고서"에 대한 재검토

> 작성일: 2026-10-03 · 원천: `Downloads/{a,b,c}-ai-3way_종합검증보고서 검토.md`
> 대상: `docs/review/2026-10-03_external-ai-3way_종합검증보고서.md` (1차 종합)
> 검증 방식: 2차 주장 실측 대조 + **1차 보고서 자체의 오류를 원문 HTML에서 재확인**

---

## 0. 총평

**1차 종합 보고서의 방향(구조 유지, 그대로 실행 금지)은 세 AI 모두 유지하나, 이번 라운드의 진짜 가치는 "1차 보고서 자체의 오류 교정"에 있습니다.** 특히 결정적인 발견: 1차 보고서가 요청서 §3.1의 "temporal 82.9"를 "84.11"로 교정했는데, **84.11은 Mnemon 표에서 EverMemOS(비교 대상 3사 중 하나, Mnemon이 아님)의 temporal 값**이었습니다. 즉 1차 교정이 원문을 다시 잘못 읽은 것이었고, B가 1차에서 의심한 "77.7/82.9 전사 혼동"이 정확히 맞았습니다. 2차 라운드의 5가지 핵심 수정 — ① multi-evidence ≠ pointwise relevance 용어 분리, ② gate를 더 이상 "주 병목"으로 부르지 않기, ③ cold fallback을 abstain 자동 후속 처리로 만들지 않기, ④ 평가 체계를 ablation보다 먼저, ⑤ SKIP 후회율 감사 복원 — 는 **전부 수용**합니다.

---

## 1. 이번 라운드 AI별 평가

| AI | 성격 | 핵심 기여 | 판정 |
|---|---|---|---|
| **C** | 구조적 수정 5건 | ① "세 AI 모두 3개 레버 동의"는 과장 → "의심점 공유"로 완화 ② 2×2의 C/D를 **pointwise relevance batch**로 재정의 (multi-evidence와 분리) ③ cold fallback은 abstain의 자동 후속이 아닌 **조건부 2차 retrieval** ④ 30~90일 hard delete 결정 보류 ⑤ cold record 임베딩 불필요 가능 | **수용 (5건 전부)** |
| **A** | 찬성 + 실행 함정 3건 | ① 평가셋 이원화: 합성 180 향상보다 **운영 90.0% 훼손 여부를 Hard Constraint**로 ② cold fallback latency 2배 (500~600ms) 리스크 ③ write cold tier ONNX 임베딩 **lazy** (embedding=NULL + 유휴 시 생성) | **수용 (3건 전부)** |
| **B** | 정밀 반박 7건 | ① 합의≠증거 ② "현재 상태 가정" 귀인 오류 + "코드 재확인 지시"는 요청서 전제와 모순 → **상수 자동 덤프** 해법 ③ 38pp는 숫자 혼용 (Run L=31.1pp) + 비대칭 비교 ④ 2×2 검정력 부족 (n=180, 효과 +0.02 → "유의할 때만 채택"은 채택 불가 고정) → **McNemar + Recall@3/다중 gold** ⑤ **커버리지 수학 균열** (아래 §3) ⑥ 평가 체계를 ablation 앞으로 + SKIP 후회율 감사 복원 + 문맥 주입 반박 범위 정정 ⑦ ❌ 4건인데 "8건 반증" + 77.7 원문 대조 부재 + 0.672 수정 누락 | **수용 (전부), ⑤는 실측으로 확정** |

---

## 2. 1차 보고서의 실제 오류 — 원문 재대조로 확정 (이번 라운드 최고 가치)

### 2.1 "temporal 82.9 → 84.11 교정" — 교정 자체가 틀림 ❌

Mnemon 논문 Table 2(원본 HTML에서 열 구조 직접 확인)의 실제 값:

| 질문 유형 | Mnemon (gpt-4.1-mini) | MemOS | **EverMemOS** | Mnemon (reasoning) |
|---|---|---|---|---|
| multi-hop (282) | 91.8 | 88.65 | **77.78** | 92.2 |
| temporal (321) | 91.3 | 85.05 | **84.11** | 92.2 |

- **84.11은 EverMemOS의 temporal 값** — Mnemon 값은 91.3 (gpt-4.1-mini) / 92.2 (reasoning). 1차 보고서가 "요청서의 82.9를 84.11로 교정"이라고 쓴 것은 원문을 다시 잘못 읽은 것.
- **82.9는 원문 어디에도 없는 숫자** (jevmem.txt/mnemon.txt 전수 검색 0건). C가 §6.6의 "temporal (8.4 points) gap"에서 91.3 − 8.4 = 82.9로 역산 추정한 것으로 보임 — 추정값이 원문 수치인 것처럼 요청서에 들어간 것.

### 2.2 "multi-hop 77.7 vs 91.8" — 전사 오류 확정

- **77.78 = EverMemOS의 multi-hop 값** (Table 2).
- 동시에 **77.7‡ = Table 3(각 프로젝트 최고 공개 결과)에 있는 Jev-Mem의 overall LoCoMo** (adversarial 포함, gpt-4o-mini 자체 보고). **B가 1차에서 의심한 "overall 0.777과 겹침"이 정확히 맞았음.**
- Mnemon 논문에는 **Jev-Mem의 유형별(multi-hop/temporal) 수치가 없음** — §6.6 본문의 "largest gaps on multi-hop (14.2 points) and temporal (8.4)"만 존재.
- 요청서 §3.1의 "multi-hop 77.7 vs 91.8, temporal 82.9 vs 91.3"은 **세 출처(Table 2의 EverMemOS 77.78, Table 3의 Jev-Mem 77.7‡, §6.6 gap 수치 역산)를 섞은 전사 오류**.
- **정확한 교정**: "Jev-Mem 유형별 수치는 Mnemon 논문에 없음. 전체 재실행 84.4% (Mnemon 91.7% 대비 7.3pp 격차), 유형별 gap은 multi-hop 14.2pp / temporal 8.4pp만 보고. Jev-Mem 자체 보고 overall LoCoMo 0.777 (Table 3, adversarial 포함)."

### 2.3 기타 집계·표기 오류 (B 지적 전부 타당)

| 1차 보고서 표기 | 실제 | 수정 |
|---|---|---|
| "8건 반증" (§5) | 표 내 ❌는 **4건** (0.672/RRF, relevance 3배, 0.951, PR 0.806) | "4건 반증 + 3건 부분"으로 정정 |
| "운영에서 38pp 열세" (§3) | Run L **동시 측정**은 83.3 vs 52.2 = **31.1pp**; 38pp는 이후 시점의 90.0%와 혼합 비교 | "Run L 동시 측정 31.1pp, 현재 90.0% 대비 37.8pp (시점 상이)"로 분리 |
| "PR full-scan이 운영에서 열세" 결론 범위 | 튜닝된 jev-mem vs frozen PR(τ=0.5 기본값, abstain 없음)의 **비대칭 비교** | "full-scan을 상시 핫패스로 쓰지 말라"까지로 한정 — pointwise 계열 일반 열등은 미증명 |
| "세 AI 모두 3개 레버 동의" (§0) | 실제는 "의심점 공유" (single-winner는 미확정) | "의심점"으로 완화 |

---

## 3. 새로 실측으로 확정한 쟁점

### 3.1 커버리지 수학 균열 (B-⑤) — 기존 "커버가 원인" 결론에 균열 확인

| 항목 | 값 |
|---|---|
| 풀 스캔 Acc@1 | 0.806 |
| 풀 안(60~100) relevance Acc@1 | 0.556~0.567 |
| 커버리지로 설명 가능한 최대 차이 | 19.4pp (100% − 80.6%) — **기대 풀 안 정확도 ≥ 0.806 − 0.194 = 0.612** |
| 실측과 기대의 격차 | **4.5~5.6pp 낮음** |

- n=180에서 노이즈일 수 있으나, **후보 집합에 따른 Jev 점수 변화(배치 구성·위치·excerpt 120자 vs 전체 span 절단) 신호**로 볼 수 있음. "커버 100%만이 PR 우위의 원인"이라는 기존 설명은 수치상 빠듯함.
- **반영**: 2×2 ablation에 "동일 프롬프트 × 후보 집합 크기(풀 vs 전체)" 대조군 추가.

### 3.2 2×2 ablation의 검정력 문제 (B-④) — 설계 수정 확정

- 효과 크기 +0.02대 × n=180에서 "A→C가 유의할 때만 채택"은 **사실상 채택 불가 고정**. 
- 수정: ① **McNemar 짝지은 검정** ② 지표에 **Recall@3 / nDCG 추가** (단일 gold Acc@1은 multi-evidence 이득이 구조적으로 안 보임) ③ **다중 gold 쿼리** 포함 ④ 채택 기준 사전 등록 ⑤ 합성 180 + 동결 운영 test 병행, **운영 90.0% 훼손 여부를 Hard Constraint** (A-①).

### 3.3 문맥 주입 반박 범위 정정 (B-⑥)

- "전체 문맥 주입 −8.1pp" (P8+CTX, 1,975건)는 **B가 제안한 "20자 미만 단답에만 직전 assistant 턴 ~300자"를 반박하지 않음** — 부분집합 조건은 미검증 상태. gate 단독 발화 판정의 약점(1차 A도 지적)에 대한 유효한 실험 후보로 남김.

---

## 4. 수용·기각 확정 (2차 라운드)

| # | 2차 주장 | 판정 | 근거/반영 |
|---|---|---|---|
| 1 | multi-evidence ≠ pointwise relevance (C) | **수용** | 1차 보고서가 "Pointwise Noul"과 "multi-evidence"를 혼용했음. 2×2의 C/D는 pointwise, multi-evidence는 별도 실험으로 |
| 2 | gate를 "가장 큰 병목"으로 부르지 말 것 (C·B) | **수용** | 운영은 이미 md=1/mc=0.0. 잔여 병목 3갈래: pool 상한 / RRF fusion / selector. lane ablation 짧게 1회 |
| 3 | cold fallback은 조건부 2차 retrieval (C) | **수용** | `NO_USABLE_IN_POOL` + "query가 memory-seeking" + cold pool Jev evidence check 통과 시만. **정밀도 회귀시험 없이 활성화 금지** |
| 4 | 30~90일 hard delete 결정 보류 + cold 임베딩 lazy (C·A) | **수용** | 운영 정책은 디스크 증가 관찰 후. cold는 원문+시간+메타만, 필요 시 재임베딩 |
| 5 | 평가 체계를 ablation보다 선행 (B) | **수용** | 1차 순위의 #1/#2 순서 교체 (또는 병행). "비용 없음" 표기도 오기 — 실제 작업 필요 |
| 6 | SKIP 후회율 감사 복원 (B) | **수용** | ledger에 원문이 이미 존재 → cold tier 도입 전에 후회율 실측이 정보가치 최대 |
| 7 | 상수 자동 덤프 체계 (B) | **수용** | "현재 코드 재확인" 지시는 저장소 접근 불가 전제와 모순 — 요청서에 상수 표 + 실측 표를 **커밋 해시와 함께 자동 생성** |
| 8 | 2×2 설계 수정 (McNemar/R@3/다중 gold/사전 기준) (B) | **수용** | §3.2 |
| 9 | abstain 상태 분리 + JEV_FAILURE 시 vec 하한 (B) | **수용** | Jev 사망 시 미검증 풀 주입 구멍 — 벡터 점수 하한으로 방어 |
| 10 | 평가 artifact에 모델 해상 정보 기록 (C) | **수용** | `jev-latest` pin 불가 시: resolved model/version + prompt/criteria hash + temperature + 날짜 기록 + 모델 변경 시 calibration 회귀 자동 실행 |
| 11 | "운영 38pp 열세" 결론 범위 한정 (B) | **수용** | §2.3 — "상시 핫패스 금지"까지만 |
| 12 | PR 최신판(0.806 단일 평가 금지) 강조 (C) | **수용** | 1차에서 반영됨, 유지 |
| 13 | 1차 "8건 반증" → 4건 정정 (B) | **수용** | §2.3 |
| 14 | 0.672 정정을 요청서 수정 목록에 추가 (B) | **수용** | 수정 9번 (§6) |

---

## 5. 최종 실행 순서 (1차 × 2차 병합, 수정판)

| 순위 | 실행 | 비고 |
|---|---|---|
| **0** | **요청서 정정 (최종 9건) + 상수·실측 자동 덤프 체계 구축** | 커밋 해시 포함. 다음 라운드부터 오류 전파 차단 |
| **1** | **평가 체계** (test 세트 동결 + 시간 분할 쿼리 + 무답 ≥50 + 다중 증거/갱신 유형 + Wilson CI + 모델 해상 artifact 기록 + 운영 90쿼리 = production regression set 고정) | ablation과 **병행** (1차 순위에서 앞당김). "0/10" = "표본 10건에서 오류 0 관측"으로 표현 |
| **2** | **SKIP 후회율 감사** (ledger 기반, KEEP vs KEEP∪SKIP pointwise 동일 판정기, 후회 후보 ≤50건) | 결과에 따라 cold tier 도입 결정 — 후회율 ≥2~3% 또는 고심각 1건이면 도입 |
| **3** | **Read 2×2 ablation** (C 재정의: A 현행 / B gate 제거 / C pointwise relevance / D B+C) | McNemar + Recall@3 + 다중 gold + 사전 채택 기준 + 후보 집합 효과 대조군(§3.1) + **운영 90.0% Hard Constraint** |
| **4** | **abstain 상태 분리** (FOUND / NO_USABLE_IN_POOL / JEV_FAILURE) | FAILURE 시 vec 점수 하한 적용 (미검증 풀 주입 방어). fallback은 3번 결과 + 정밀도 회귀 후 |
| **5** | **multi-evidence set selection 실험** | 2×2의 A→C가 유의할 때만. pointwise와 별도로 정의 |
| 보류 | 30~90일 hard delete / cold 임베딩 선행 생성 / graph lane / timeout 축소 | 관찰·실측 후 결정 |

**우선순위 1·2가 바뀐 이유**: 평가 체계 없이 ablation을 돌리면 (a) 튜닝 반복 세트에서의 수치라 해석 불안정, (b) "유의/미유의" 판정 자체가 신뢰 불가 — B의 지적이 정확.

---

## 6. 요청서 수정 목록 (최종 9건 — 1차 8건 중 1건 재교정 + 1건 추가)

| # | 위치 | 수정 |
|---|---|---|
| 1 | §2.3.2 | conservative gate → 운영값 **md=1/mc=0.0** (P0 반영) + "완화 후 커버 80.6% 유지" |
| 2 | §2.3.2 | vec-rank 예외 "상위 2위" — Run M/P 실측으로 확장 레버 소진 명시 |
| 3 | §3.1 | ~~"temporal 82.9 → 84.11"~~ **재교정**: "multi-hop 77.7 vs 91.8, temporal 82.9 vs 91.3" 행 **삭제** → "Jev-Mem 유형별 수치 미공개. 전체 재실행 84.4% (Mnemon 대비 7.3pp), 유형별 gap multi-hop 14.2pp/temporal 8.4pp. 77.7‡는 Table 3의 Jev-Mem overall (adversarial 포함), 84.11은 Mnemon 표의 EverMemOS 값" |
| 4 | §2.5 | "store recall 0.951 (누락 0)" → 0.951=오프라인 1975건 / 누락 0=live 142건 분리 |
| 5 | §4 | "PerfectRecall (full-scan)" → "jev-mem 재현 frozen-PR baseline 실측" |
| 6 | §4 | PR 최신판(128 workers/decision cache/10k)과 419-span 실측이 다른 구현임 각주화 |
| 7 | §2.5 | "a8m > q4f16 > int8" → ad-hoc 베이스라인 명시 |
| 8 | §2.4 | quarantine → f5aa4ef로 hot retrieval 완전 제외 반영 |
| **9** | §4 | "임베딩 단독 0.672" → **"후보 5~40개 내 직접 유사도(다른 태스크) 수치, 같은 코퍼스 vec 단독은 0.494"** 명시 — 다음 라운드 리뷰어의 같은 함정 방지 |

---

## 7. 다음 라운드 지시문 반영 사항

1. 요청서 상단에 **"모든 수치는 커밋 해시와 함께 10-03 운영 코드/실측에서 자동 덤프된 것"** 명시 — B-② 해법.
2. 1차 종합 보고서의 오류 교정분(§2)을 "재의심 불필요"로 먼저 제시.
3. 질문은 **2×2 ablation 설계 확정**(C 재정의 + McNemar/R@3/다중 gold/사전 기준)과 **SKIP 후회율 감사 프로토콜** 두 쟁점으로 한정 — 이번 라운드에서 이미 충분히 갈린 지점.

---

## 8. 최종 요약

**1차 보고서의 가치** (외부 AI 주장을 코드·실측으로 필터링) 는 유지되나, **1차 보고서 자체에 3개의 실제 오류**가 있었음: ① "84.11 교정"이 원문 재오독 (EverMemOS 값), ② "multi-hop 77.7 vs 91.8" 전사 오류 방치 (1차에서 ⚠️로만 남김), ③ "8건 반증/38pp/세 AI 동의" 집계·표기 과장. **이번 라운드의 최대 교훈: "1차에서 교정했다"는 것도 원문 재대조로 검증해야 한다** — 검증 사이클이 자기 자신에게도 적용되어야 함.

**최종 합의된 실행** (세 AI 공통): 요청서 정정 9건 + 자동 덤프 → 평가 체계(병행) → SKIP 후회율 감사 → 2×2 ablation(수정 설계) → abstain 상태 분리·조건부 fallback → multi-evidence(2×2 후). **5번 항목(abstain 상태 분리)만 즉시 실행 가능** — 나머지는 모두 평가 체계/감사 완료 후.

---

*검증 일시: 2026-10-03 · 원문 재대조: mnemon.html Table 2/Table 3/§6.6 (arXiv 2609.36059v1), jevmem.html (arXiv 2609.23986v1), R2 §4.3, Run L (r5-final), 요청서 §3.1/§4, 1차 종합 보고서 전수.*