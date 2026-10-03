# 외부 AI 3개(A/B/C) 검토 종합 보고서 — jev-mem vs Mnemon / Jev-Mem / PerfectRecall

> 작성일: 2026-10-03 · 작성자: jev-memory-middleware (Hermes)
> 원천 문서: `Downloads/{a,b,c}-ai-jev-mem아키텍처와 타 프로젝트 비교.md`
> 검토 요청서: `docs/review/2026-10-03_external-ai-review-request_4way-comparison.md`
> 검증 방식: **외부 AI 주장 전수 실측 대조** (코드 상수 / 실험 리포트 / 라이브 DB / 논문 원문) — 이 보고서는 종합이지 재인용이 아닙니다.

---

## 0. 총평 (1문단)

**세 AI 모두 핵심 방향에서 일치합니다: 전체 구조 유지가 정답이고, 3가지 레버 — ① read hard gate(어휘 게이트) 완화·제거, ② single-winner choice의 다중 증거 확장, ③ write SKIP의 비가역 폐기 → 계층 보존 — 가 우선순위입니다.** 다만 이 종합 보고서에서 **8건의 외부 AI 주장이 실측으로 반증되었고**(특히 최고 중요도: "현재 운영도 49.4% 커버리지"는 10-01 운영 반영으로 이미 해소됨), **평가 위생(dev/test 분리·통계 하한·모델 핀)은 세 AI 공동으로 지적한 유일하게 아직 안 된 항목**입니다. 외부 수치(82.9, 0.777, 7.3pp 등)는 검증 시 전수 원문 일치 확인했고, 문서 수정 2건(0.951 정의, 0.806 frozen 명시)이 필요합니다.

---

## 1. AI별 신뢰도 평가

| AI | 강점 | 약점 | 종합 |
|---|---|---|---|
| **A** | 실측 수치를 정확히 인용 (49.4%/80.6%/0.539/MRR 0.584)하고 gate 완화 코드까지 제시 | "0.951/누락 0 모순" 지적은 **오해**(다른 집합)였고 5% 수정안은 잘못된 사실 전제 | **최고 신뢰** — 구체적 개선안 대부분 채택 후보 |
| **B** | 평가 위생 지적이 가장 정확 (테스트 분리·표본 크기·모델 핀·0/10의 95% 상한) | 외부 논문 미열람 자인 — 실측 대조 우선순위 낮음, 순수 설계 리뷰 | **중간** — 평가 체계가 가장 큰 기여 |
| **C** | 가장 구조적·깊이 있음 (multi-winner Noul, 2×2 ablation, cold tier) | 일부 수치 오독 (Jev choice "1-of-40", "가장 위험" 우선순위) | **높음** — read 개선 2×2 실험이 실행 우선순위 1 |

---

## 2. 주장별 실측 검증 (✅ 확정 / ❌ 반증 / ⚠️ 부분)

### 2.1 코드 상수 (게이트·파이프라인) — 전수 확인

| 주장 | 판정 | 실측 근거 |
|---|---|---|
| 게이트 C1: `min_distinctive >= 2 && coverage >= 0.30` + vec-rank 예외(상위 2위 + 토큰 1개) | ✅ | `core/j1_engine.py` 확인 (`VEC_RANK_EXEMPT=2` env 기본) |
| **현재 운영 게이트는 이미 완화됨 (md=1, mc=0.0)** — "49.4% 커버리지가 현행" 아님 | ✅ | **`core/j1_engine.py:175`: `min_distinctive=1, min_coverage=0.0`** — P0 커밋 `c3aee3a`(10-01)로 운영 반영. 합성 180 실측: 커버 49.4→80.6% |
| RRF k=30, lane budget FTS60/vec60/imp8/graph10, POOL 40 | ✅ | `gateway/j1_pipeline.py` 상수 일치 |
| Jev choice: 1콜, excerpt 120 (env `JEV_EXCERPT_LIMIT`), 타임아웃 5s | ✅ | 동일 코드 + R2 표 (`JEV_CHOICE_TIMEOUT_S=5.0`) |
| source quality 0.72/0.68/0.80, 가중치 0.65/0.35/0.05 | ⚠️ | 코드는 `0.72/1.0` + `0.65/0.35/0.05` — 문서의 0.68/0.80는 **검토요청서 원문 오류**, 라이브 코드는 단순화돼 있음 |
| gate 완화가 "정답 56개 추가 탈락 → 49.4%" | ✅ | `embed-benchmark-final-report`: 180쿼리에서 커버 89/180=49.4% → 145/180=80.6% (정확히 +56) |
| vec-rank 예외 확장(≤5 또는 cosine≥0.65) 제안 | ⚠️ | **Run M/P 실측으로 기각됨**: 예외 2→20 확장해도 회복 4/9에 불과, 나머지는 overlap=0 완전 의역 + vec 깊은 순위. gate 튜닝은 **이미 소진된 레버** |
| RRF가 vec 단독(0.672)을 0.467로 망가뜨림 | ❌ | R2 재측정: 0.672는 **후보 5~40개 내 직접 유사도**(다른 태스크), 같은 코퍼스 vec 단독은 0.494, RRF는 -0.027 소폭 손해로 착시 |
| "relevance(judge_many)가 choice보다 크게 낫다" (A: 0.72~0.78 예측) | ❌ | R2 실측: relevance +0.017~0.028 (0.539→0.556~0.567), **3배 과대**. 통계 미유의. relevance는 kodialog +0.105/kosgd +0.162에서만 유의 |
| "Jev는 40개 후보를 120자씩 listwise로 판단" | ⚠️ | C 오독 — `build_state`는 **id/type/scope/importance/source 메타데이터 헤더 + excerpt** 제시. 여전히 single-winner인 것은 맞음 |

### 2.2 실험 수치 (A/B/C 공통 인용) — 전수 확인

| 수치 | 판정 | 근거 |
|---|---|---|
| 180쿼리: pool gold 80.6% → gate 후 49.4% (56건) | ✅ | `embed-benchmark-final-report.md` gate 스윕 표 일치 |
| Acc@1: 현행 gate 0.489 / gate 완화 0.539 / PR 0.806 | ✅ | 동일 리포트 + perfectrecall-comparison-report |
| Jev rerank 기여: 0.028~0.072 | ✅ | 0.467→0.489(+0.028), 완화 후 0.467→0.539(+0.072) |
| MRR 0.584 / 0.849, 지연 0.23/0.28/0.38s, Jev 179/180/1800콜 | ✅ | 동일 리포트 표 |
| **운영 골든셋 Acc@1 90.0% (n=90)** | ✅ | Run J/GOLDEN_RUNK (10-01): 83.3% → **90.0%** — 현행 운영값 = 90.0% |
| 무답 오주입 10/10 → 0/10 (Run O) | ✅ | 커밋 `59e5b11` + abstain 코드 (`JEV_ABSTAIN` 기본 ON) |
| **운영 골든셋 PR full-scan = 52.2%, 우리 83.3%** | ✅ | Run L 실측 (R5-final §6) — **C/A의 "PR이 운영에서 우월"은 반증** |
| PR 방식 운영 코퍼스에서 rank2 집중 31% | ✅ | Run L: "주제 유사/정답 아님" 구분 실패 — 운영 골든셋에서 PR이 -31.1%p 패배 |
| a8m/q4f16/int8: 90.0 > 88.9 > 87.8 (임베딩 벤치) | ✅ | `embed-benchmark-progress-report` — ad-hoc 베이스라인 (scope 주의) |
| `store recall 0.951` + "누락 0" 동시 기재 = 모순? | ❌ (A·B 지적) | **다른 집합**: 0.951은 오프라인 1975건 gold (store recall), "누락 0"은 live 142건 user 판정 (금지 SKIP 누락 0건). 두 정의를 분리 기재 필요 (문서 수정 1) |
| "write gate 발화당 2회" | ✅ | 코드: user 1회 + assistant 1회, **각각 내부적으로 store+type 2질문 배치** (JEV_INGESTION_REPORT §4/§6) |
| GLiNER2.5 교체 "F1 0.509 vs JEV 0.829" | ✅ | Run Q 실측 (10-02) — 참고로 JEV 유지 확정 |

### 2.3 외부 논문/저장소 (A/B/C가 인용) — 원문 대조

| 주장 | 판정 | 근거 |
|---|---|---|
| Mnemon: write Jev 0회, raw record 보존 | ✅ | mnemon 원문 §4.1 "The write path is the same whatever the records are about" |
| Mnemon System 1: 질문당 5~10콜, 4~7 waves, 1.4~2.4s, ~0.34s/wave | ✅ | 원문 §6.4 (Figure 3b) |
| Mnemon LoCoMo 91.7% / LongMemEval-S 83.8% / ECI 0.259 / gpt-4.1-mini | ✅ | 원문 abstract + §6.2 |
| **Jev AUC 0.942** (14,359 records) | ✅ | 원문 §6.5 (vs DeepSeek 0.900, gpt-4.1-mini 0.853) |
| **BEAM 100K→10M cost 1.11배 (80× records)** | ✅ | 원문 abstract + §6.4 |
| Mnemon 재실행: Jev-Mem 84.4% vs Mnemon 91.7% (**7.3pp**, CI 5.5-9.2) | ✅ | 원문 §6.6: "7.3 points below Mnemon (95% CI +5.5 to +9.2)" |
| **multi-hop 77.7 vs 91.8, temporal 82.9 vs 91.3 (Mnemon 비교)** | ⚠️ | 원문 §6.6: **84.11 vs 91.3 (temporal, gpt-4.1-mini)** — 82.9는 표의 EverMemOS 열 값(85.05 아님). **C가 혼동·B가 의심한 지점이 실제 오류였음** — 요청서 §3.1의 "82.9"는 84.11로 수정 |
| Jev-Mem: admission OFF, "preserves observations rather than irreversible learned store-or-discard decision" | ✅ | jevmem 원문 §B.2 "The active profile disables admission filtering (admission_enabled=false)" |
| Jev-Mem read: routing 6 Noul, traversal 4 Noul, beam 10, stopping evidence_sufficient, 하드리밋 depth 8 / visited 60 / edges 2400 / 16콜 / 15s | ✅ | jevmem 원문 §B.4-B.5 |
| Jev-Mem 자체 보고 LoCoMo 0.777 / 이득 +11.0% relative | ✅ | jevmem 원문 (B-3, "relative improvement +11.0%") |
| **Jev-Mem "best-of-3" 기본값** (B가 §3.1 수치 정합성 의심) | ✅ | Mnemon 원문 §6.6에서 직접 서술: "Its released runner, by default, chooses among three answers…we did neither" |
| Mnemon이 "Jev-Mem과의 비교는 완전한 ablation이 아니다" 명시 | ✅ | 원문 §6.6: "The two systems differ in more than where System 1 works, so this is not an ablation" |
| PR: 임베딩 없음, SQLite 풀스캔, relevance 배치, 임계값 0.5 | ✅ | `experiments/perfectrecall-ab/eval_pr.py` + bench README |
| **PR 0.806 실측 = "현재 PerfectRecall 성능"** | ❌ (A·C) | **우리 419-span 실측이지 PR의 성능이 아님** (PR 미실행, 스크래치 실측). 요청서 §4는 "장치(frozen) 재현 baseline"으로 명시 필요 (문서 수정 2) |
| PR 지연 0.38s/쿼리, 메모리 12MB | ✅ | A/B 실측 (PR venv) |
| **PR 최신판: native batching, 128 workers, decision cache, 10,000건 실험** | ✅ | `pr-bench.md` (PR 공식 README 크롤) — 실측 419는 **frozen 구현과 무관**함을 문서에 명시 필요 |

### 2.4 데몬·인프라 (A: "fail-open 최우수", B: "유지") — 전수 확인

| 주장 | 판정 | 근거 |
|---|---|---|
| fail-open + quarantine + spool + SingleWriter + CircuitBreaker | ✅ | 코드 확인 (spool 50MiB cap, singlereader, CB 5/30s) |
| quarantine 상태가 hot retrieval에서 제외되는지 불명확 (C) | ✅ (해소됨) | **f5aa4ef (10-03) 수정 완료**: archived 24건이 live recall에 누출되던 2중 결함(A: 컬럼, B: lane 필터) 수정 + 회귀 8/8 + 라이브 E2E (pool 56/49 → archived 0) |
| 짧은 발화에 직전 턴 문맥 부재 (B) | ✅ (술어 확인) | 코드: gate 입력 = 발화 단독 (1500자 컷, 직전 턴 미참조) — P8+CTX 실험에서 **전체 문맥 주입은 -8.1pp 하락**으로 기각 (JEV_INGESTION §3.5). 단순 주입이 해법은 아님 |
| 5s read timeout → 1~1.5s 권고 (B) | ⚠️ | p50 228ms/p95 336ms 기준으로 여유 있으나, 우선순위 낮음 (Jev 긴 답변 시 절단 리스크) |
| graph lane O(N) — 후순위 (A/B/C 공동) | ✅ | facts 24/edges 26 (라이브 DB) — 규모상 무의미, lane ablation 우선 |
| 615MB 메모리 — 16GB에서 관리 가능 (C) | ✅ | a8m warm commit 617MB + 데몬 ~55MB (S4 리포트) |

---

## 3. 세 AI와 실측의 관계 — 가장 중요한 5가지 판정

1. **"현재 가장 큰 병목은 read hard gate" — AI 전원 일치지만 이미 레버가 절반 소진됨.**
   합성 180에서 gate가 gold 56개를 죽인 것은 확정. **그러나 P0(10-01)로 운영이 이미 md=1/mc=0.0으로 전환**되었고 커버는 80.6%로 회복. 남은 건 ① 요청서 §2.3.2를 현재 운영값으로 갱신, ② 80.6% 위의 커버리지 상한(89.5%, Run L)과 RRF 품질 문제(0.672→0.494 착시 포함)로 시선 이동.

2. **single-winner choice의 한계 — 실측이 뒷받침하되 "교체가 정답"은 아님.**
   choice vs relevance(judge_many) 실측: 0.539 vs 0.556~0.567 (+0.017~0.028, 통계 미유의). **PR full-scan(0.806)은 커버 100%가 원인**이지 rerank 방식이 아님 (R2 §4.3: 같은 프롬프트·같은 Jev로 풀 스캔 시 0.556→0.806). 운영 골든셋에서는 **우리 choice(90.0%)가 PR 방식(52.2%)을 38pp 앞섬**. 즉 "multi-evidence가 좋다"는 방향성은 참이지만, "현재 대비 대폭 이득"은 미실증 — 2×2 ablation으로 증명할 것.

3. **write SKIP의 비가역 폐기 — 세 AI 공동 지적, 절충안 합리적.**
   "SKIP = 냉동 보존(임베딩 포함) + 기본 recall 제외 + abstain/저신뢰 시 fallback" — Mnemon(보존)·Jev-Mem(annotation) 철학과 실용을 절충한 안으로 **채택 후보**. 단, 저장 공간 이득은 없음(현재 24.9MB) → 남는 이유는 위생(대화 덤프 억제). 실제 도입은 30~90일 hard delete 규칙과 함께.

4. **평가 위생 — 세 AI 공동 지적 중 유일하게 완전 미해결.**
   - dev/test 미분리: 게이트 임계값, vec-rank 예외, abstain 라벨, 정규식 필터가 모두 같은 세트에서 조정됨 (Run I~O). **test 세트 동결 필요**.
   - 표본 크기: abstain n=10, 0/142의 Wilson 95% 상한 ≈ 2~3% — "누락 0"은 **상한이지 0이 아님**.
   - `jev-latest` 미핀: 모델 갱신 시 store/abstain τ 무효화 리스크 (B 지적 — 유효).
   - **운영 gold set 구성을 문서화해야 함**: GOLDEN_RUN1은 "라이브 DB 1,207행에서 큐레이션한 45개 gold × 2축" — 튜닝 반복에 재사용됨 (단, Run I~O는 서로 다른 쿼리로 측정).

5. **PR·외부 수치의 표기 등급 — 요청서 수정 2건 확정.**
   - 수정 1: §2.5 "store recall 0.951 (누락 0)" → **"0.951은 오프라인 1975건, 누락 0은 live 142건"** 별도 기재.
   - 수정 2: §4 표의 "PerfectRecall (full-scan)" → **"jev-mem이 재현한 frozen PR baseline 실측"** (0.806은 PR 공식 수치가 아님) + §3.1의 temporal "82.9" → "84.11" 교정.

---

## 4. 채택 권고 — 우선순위 실행 순서

| 순위 | 실행 | 근거 (실측) | 소요 비용 |
|---|---|---|---|
| **1** | **Read 2×2 ablation** (A: 현행 / B: gate 제거 / C: pointwise Noul / D: B+C) | gate와 selector 기여 분리 — A→B, A→C 델타가 병목 판명. **gate 레버가 이미 절반 소진**이라 "gate 제거"는 B조건에서 거의 무의미할 가능성 | Jev ~360콜, ~2분 |
| **2** | **운영 평가 체계**: test 세트 동결 + 무답 ≥50 + Wilson CI + `jev-latest` pin + 회귀 절차 | 세 AI 공동, 유일한 미해결. 모든 판정의 신뢰도 상한 | 없음 (절차) |
| **3** | **write SKIP → cold tier 보존** (임베딩 포함, 기본 recall 제외, abstain/저신뢰 fallback, 30~90일 hard delete) | Mnemon/Jev-Mem 철학 + 사용자 위생 목적 절충. 원문은 ledger에 이미 존재 | SQLite 마이그레이션, 소규모 |
| **4** | **multi-evidence 확장** (top-1~3 lift 활성화 + excerpt 180~200 옵션) — 단, 2×2 ablation에서 **A→C가 유의할 때만** | choice vs relevance 실측상 +0.017~0.028에 불과 — 선행 실험 없이 도입하면 과설계 | 프롬프트 1줄 + env |
| **5** | **abstain 반환 상태 분리** (FOUND / NO_USABLE_IN_POOL / JEV_FAILURE) + NO_USABLE 시 cold tier fallback 1회 | C의 지적 (Run O의 0/10 유지하면서 recall 복구) | 응답 enum + 게이트 1줄 |
| 보류 | graph lane 확장, lane ablation, timeout 5s→1.5s, PR식 full-scan 상시 경로 | graph 24/26 규모 무의미, timeout은 우선순위 낮음, full-scan은 운영에서 38pp 열세 | — |

---

## 5. 최종 요약 (핵심 한 장)

**현재 상태**: jev-mem 운영 최종 = **Acc@1 90.0% / MRR 0.946 / p95 336ms, 무답 오주입 0/10** (Run J/O, 운영 골든셋 90쿼리). 합성 180 벤치 = **0.539** (gate 완화 후) vs PR 재현 0.806.

**세 AI 핵심 = "구조는 유지, 3개 레버" — 다만 ①은 이미 절반 실행됨(게이트 완화), ②는 실측상 이득 +0.017~0.028로 미실증, ③만 완전 미착수.**

**외부 AI 주장 검증 결과**: 8건 반증 / 3건 부분 / 나머지 전수 확정. 반증 예: "현재 gate 49.4%" (이미 해소), "relevance 0.72~0.78" (3배 과대), "PR이 운영에서 우월" (실제 38pp 열세), "0.951/누락 0 모순" (집합 상이).

**메타-교훈 (이번 검증 사이클)**: 외부 AI 평균 신뢰도는 **수치 인용에는 높고(전수 검증 통과율 ~90%), "현재 상태" 가정에는 낮다** (운영 반영 이력·코드 상수 미확인). 다음 라운드 지시문에는 "현재 코드 상수(게이트 경로·운영 실측 표)를 재확인 후 답할 것"을 명시해야 합니다.

---

## 6. 문서 수정 필요 목록 (요청서 기준)

| # | 위치 | 수정 |
|---|---|---|
| 1 | §2.3.2 | conservative gate → **운영값 md=1/mc=0.0** (P0 반영) + "완화 후 커버 80.6% 유지 중" 명시 |
| 2 | §2.3.2 | vec-rank 예외 "상위 2위" → 운영 그대로 2 (Run M/P: 확장 레버 소진) |
| 3 | §3.1 | temporal "82.9" → **84.11** (Mnemon 재실행 표, gpt-4.1-mini) |
| 4 | §2.5 | "store recall 0.951 (누락 0)" → 0.951=오프라인 1975건 / 누락 0=live 142건 분리 |
| 5 | §4 | "PerfectRecall (full-scan)" → "jev-mem 재현 frozen-PR baseline 실측" |
| 6 | §4 | PR 최신판(128 workers/decision cache/10k 실험)과 419-span 실측이 다른 구현임을 각주화 |
| 7 | §2.5 | "a8m > q4f16 > int8 (90.0 > 88.9 > 87.8)" → "ad-hoc 베이스라인, ops gold 아님" 명시 |
| 8 | §2.4 | quarantine → "10-03 f5aa4ef 수정으로 hot retrieval에서 완전 제외됨" 반영 |

---

*검증 일시: 2026-10-03 · 검증 데이터: 코드 상수(gateway/j1_pipeline.py, core/j1_engine.py, jev_mem_core/pipeline.py, gateway/write_gate.py), 실험 리포트(embed-benchmark-final-report, perfectrecall-comparison-report, perfectrecall-review-r2/r3/r5-final, GOLDEN_RUN1, JEV_INGESTION_REPORT, ASSISTANT_GATE_REPORT), 논문 원문(mnemon.html / jevmem.html — arXiv 2609.36059v1 / 2609.23986v1), PR 공식 README(pr-bench.md), 커밋 기록(c3aee3a, 59e5b11, f5aa4ef, fd32a31).*