# 외부 AI 검토 요청 3차 — Read 2×2 Ablation 설계 확정 + SKIP 후회율 감사 프로토콜

- **작성일**: 2026-10-03
- **성격**: 자가완결형 검토 요청서 (2차). 저장소 접근 권한 없는 수신 AI가 이 문서만으로 답변 가능하도록 작성.
- **전제**: 이 문서의 모든 실측 수치는 **2026-10-03 운영 코드/라이브 DB/커밋 해시** 기준이며, 아래 "§1 재의심 불필요"에 있는 항목은 1·2차 라운드에서 실측으로 확정된 것이므로 **다시 뒤집지 말 것**.
- **요청 범위**: ① Read 2×2 ablation의 조건 정의·지표·판정 기준 확정, ② SKIP 후회율 감사 프로토콜 설계. **두 쟁점에만 답변**할 것 (다른 주제의 새 제안은 불필요).

---

## 0. 시스템 요약 (1장 — 이전 라운드와 동일 구조)

```
[WRITE] 발화 → JEV write gate (턴당 2회: user/assistant 각 1회, 내부 store+type 2질문 배치)
        → G-qual/G-AS 규칙 → KEEP만 mnemosyne.db(working_memory) 저장, SKIP은 미저장
        → 결정 기록: core_state.db ingest_ledger (idem_key, decisions_json, status)
[READ]  lane pool (FTS60 + vec60 + imp8 + graph10) → RRF(k=30) → 어휘 게이트
        → JEV choice 1콜 (후보 ≤40, excerpt 120자, abstain 라벨 포함) → winner lift
```

| 항목 | 값 |
|---|---|
| 운영 게이트 | **md=1, mc=0.0** (커밋 `c3aee3a`, 10-01 반영) — 실측 커버 49.4%→80.6% |
| 운영 골든셋 90 | Acc@1 **90.0%** / MRR 0.946 / p95 336ms / 무답 오주입 0/10 (Run J·O) |
| 합성 180 벤치 | Acc@1 0.539 (gate 완화+choice) / relevance 실측 +0.017~0.028 (통계 미유의) |
| PR frozen 재현 (419span, 180쿼리) | Acc@1 0.806 / MRR 0.849 (Jev 1,800콜) |
| Run L (운영 코퍼스 1,234span, full-scan) | Acc@1 52.2% vs 우리 83.3% (**31.1pp, 동 시점**) — rank2 집중 31% |
| vec 단독 (같은 코퍼스) | 0.494 — RRF는 -0.027 소폭 손해. "0.672"는 후보 5~40개 직접 유사도(다른 태스크) |
| 라이브 DB | working 1,424 / episodic 113 / facts 24 / graph_edges 26 (24.9MB) |

---

## 1. 재의심 불필요 (실측 확정 — 이번 라운드에서 그대로 전제)

1. **요청서 §3.1 수치 오류 확정 (2차 라운드 원문 재대조)**:
   - `77.78` / `84.11`은 **EverMemOS**의 multi-hop/temporal 값 (Mnemon Table 2) — Mnemon은 91.8/91.3.
   - `82.9`는 **원문에 없는 숫자** (C가 §6.6의 temporal gap 8.4점에서 역산 추정).
   - `77.7‡`은 **Jev-Mem overall LoCoMo** (Table 3, adversarial 포함) — 유형별 수치가 아님.
   - **정확한 사실**: Jev-Mem 유형별 수치는 Mnemon 논문에 없음. 전체 재실행 84.4% vs Mnemon 91.7% (7.3pp), 유형별 gap은 multi-hop 14.2pp / temporal 8.4pp만 보고. Jev-Mem 자체 보고 overall 0.777 (gpt-4o-mini).
2. **2×2 용어 확정**: C/D 조건은 **pointwise relevance batch** (후보별 yes/no 점수화 → 재정렬)이며, **multi-evidence set selection (복수 증거 동시 선택)과 다른 개념**.
3. relevance vs choice 실측: 0.539 → 0.556~0.567 (+0.017~0.028) — 선택지 교체로 "크게 좋아진다"는 증거 없음.
4. gate·vec-rank 예외 확장은 레버 소진 (Run M/P: 예외 2→20 확장 시 회복 4/9, 잔여 미스는 overlap=0 완전 의역).
5. PR 0.806은 **jev-mem이 재현한 frozen PR baseline 실측**이며, 최신 PR(main: 128 workers/decision cache/10,000건 실험)과는 다른 구현 — "PR 현재 성능"으로 쓰지 않음.
6. quarantine(재판정 skip) 행 recall 누출 2중 결함은 `f5aa4ef`(10-03)로 수정·검증 완료 — **hot retrieval에서 완전 제외됨**.
7. 운영 골든셋 90쿼리는 **튜닝 반복에 재사용된 세트** (dev/test 미분리) — "동결 test"로 취급 불가. `0/10`은 "표본 10건에서 오류 0 관측"이며 Wilson 95% 상한은 26~30%.
8. 효과 크기 +0.02대 × n=180에서 "유의할 때만 채택"은 사실상 채택 불가 고정 → **짝지은 검정( McNemar) + Recall@3/다중 gold + 사전 채택 기준** 필요.
9. 커버리지 수학: 풀 스캔 0.806 − 풀 안 0.556~0.567의 차 25pp 중, 커버리지로 설명 가능한 최대는 19.4pp → **기대 풀 안 정확도 0.612보다 4.5~5.6pp 낮음** (후보 집합 의존 Jev 점수 신호, 미확정).
10. 문맥 주입: "전체 문맥 주입 −8.1pp" (P8+CTX 1,975건) 실측 — 단, **20자 미만 단답에만 직전 턴 병기** 방식은 미검증 (이번 범위 밖, 보류).

---

## 2. 신규 실측 (이번 지시문 — 반드시 반영할 것)

### 2.1 SKIP 원문의 잔존 실태 — "ledger에 원문이 있다"는 전제 불성립

`core_state.db ingest_ledger` (라이브, 2026-10-03 22:21 기준):

| 항목 | 실측 |
|---|---|
| 전체 행 | **338** (stored 283 / **skipped 40** / fail_open_quarantine 15) |
| `payload_json` | **338/338 전부 NULL** — 원문 미저장. SKIP 40건도 0건 보유 |
| `decisions_json` | user/assistant별 keep·store·type·conf·reason 기록됨 (예: `{"user": {"keep": false, "store": "NO_STORE", "store_conf": 0.76, "type": "NO_STORE", ...}}`) |
| `received_at` 분포 | 2026-09-29 ~ 10-03. skipped: 09-29 31건 + 10-01 9건 (09-29는 **pi-test 시절 테스트 발화** — decisions에 `"reason": "empty"` keep=true 행 혼재) |
| spool | 디렉토리 7개(agent별) 모두 **빈 상태** — replay 완료 후 원문 삭제된 것으로 보임 |

- **의미**: "ledger 재생 → SKIP 원문 복구 → 후회율 감사"는 **현재 불가**. SKIP 발화 원문의 잔존 후보: ① Hermes 세션 아카이브/로그 ② `%LOCALAPPDATA%/jev-mem/backups/` DB들 ③ (전향적) payload 저장 활성화.
- **전향적 방안**: `payload_json` 기록 활성화(크기 cap 포함) 또는 별도 원문 보존 테이블.

### 2.2 PR pointwise 배치의 스케일 전제

- PR `_rank(query, corpus)` = `jev.relevance(query, texts)` **1회 전체 배치** (eval_pr.py docstring 확인). 419span을 1콜로 처리.
- **미확인**: 배치 최대 질문 수·가격·타임아웃 (B 1차 불확실성 목록과 동일). 라이브 1,424행 pointwise 1콜 가능 여부는 **미실측** — 이번 실험 설계 시 가정을 명시하고 검증 필요.

---

## 3. 검토 질문 (Q1~Q6 — 2개 쟁점)

> 답변 형식: **Q별 ① 동의/반박/대안 ② 근거(위 실측 인용) ③ 구체 수치·설계** (실측과 추측 구분). 각 Q에 선택지가 있으면 a/b/c 중 하나를 고르고 이유를 붙일 것.

### 쟁점 1: Read 2×2 ablation 설계 확정

**Q1. 조건 축의 재정의 — "gate 제거"는 정보가치가 소진됐다?**
현행 운영 게이트가 이미 md=1/mc=0.0 (사실상 무력)이므로, "gate 제거" 축(A→B)은 거의 변화가 없을 것으로 예상됩니다. 그래서 2×2의 축을 **retrieval scope**로 재정의하는 방안을 검토합니다:

| 조건 | 후보 공급 | Jev 판정 |
|---|---|---|
| A | lane pool + RRF (현행) | choice 1콜 |
| B | **full corpus (1,424행 전체)** | choice 1콜 |
| C | lane pool + RRF | **pointwise relevance 배치** |
| D | full corpus | pointwise relevance 배치 |

- (a) 이 재정의(B=full-scan, D=full-scan+pointwise)가 맞다 — B는 PR 방식의 조작적 정의로, "커버 100%" vs "후보 집합 의존 판정"을 분리하는 대조군이 된다.
- (b) 원래 2×2 (gate 제거 축)를 유지하라 — A→B가 0임을 **확인하는 것 자체**가 문서화 가치다.
- (c) 다른 축 (예: excerpt 길이 120 vs 전체 span, 또는 RRF vs vec 단독) — 어떤 축이 정보가치가 더 높은가?

**Q2. 지표·검정·표본 구성 확정**
다음 후보 중 채택 기준을 확정해 주십시오:
- 지표: Acc@1, MRR, **Recall@3** (다중 증거 이득 관측용), gold-in-pool, nDCG 중 필수/선택?
- **다중 gold 쿼리** (정답 2~5개가 필요한 질문)를 합성 세트에 몇 개 추가할 것인가? (단일 gold Acc@1은 multi-evidence 이득이 구조적으로 안 보임 — 확정분 §1-8)
- 검정: McNemar 짝지은 검정 + 사전 채택 기준(significance level, 최소 효과 크기)?
- 표본: 합성 180 + 동결 운영 90(현재는 dev/test 미분리 — §1-7) 병행, **운영 Acc@1 ≥90.0% 훼손을 Hard Constraint**로 두는 방안?
- 판정 규칙 초안: "C 또는 D가 운영 Hard Constraint 유지 + 합성 Recall@3 +5pp 이상 + McNemar p<0.05일 때만 채택" — 타당한가, 아니면 기준이 너무 엄격/느슨한가?

**Q3. 후보 집합 의존성 대조군 (커버리지 수학 균열 검증)**
같은 pointwise 판정기를 (a) pool 40~60 / (b) pool 상위+절단 없음 / (c) full corpus에 각각 적용해, "커버 100% 효과"와 "후보 집합·절단(excerpt 120자 vs 전체)에 따른 Jev 점수 변화"를 분리하는 실험을 2×2에 포함할 것인가? (기대치: 풀 안 0.612 vs 실측 0.556~0.567의 4.5~5.6pp 차이의 원인 규명) — 포함한다면 최소 조건은?

**Q4. full corpus pointwise의 비용·지연 전제**
라이브 1,424행을 1콜로 던질 수 있는지 **먼저 probe**(작은 스크립트, 10쿼리 × 1,424행)로 확인하고, 실패 시 청크 분할(예: 300행 × 5콜)을 쓰는 설계 — 이 순서에 동의하는가? probe 실패 시 어떤 대안(청크 크기, 부분 샘플링 500행, 임계값 0.5 유지 등)을 제안하는가?

### 쟁점 2: SKIP 후회율 감사 프로토콜

**Q5. 원문 복구 전략 — payload NULL 상태에서 무엇으로 감사하는가?**
- (a) **전향적 감사**: `payload_json` 기록 활성화(또는 별도 원문 보존) 후, 향후 N주간 SKIP 발화를 모아 감사 — 기존 SKIP 40건은 대상에서 제외.
- (b) **사후 복구**: Hermes 세션 아카이브/백업 DB에서 SKIP 원문 재구성 시도 (09-29 31건은 테스트발화로 제외, 10-01 9건만 대상) — 복구율과 신뢰성 한계를 어떻게 검증할지 포함.
- (c) (a)+(b) 병행.
- 어떤 조합이 정보가치/비용 최적인가? 또한 감사 시점 기준을 "received_at 시점 이전 턴만 후보"로 하는 **시간 분할(time-partitioned) 검색**의 구체적 구현(쿼리 선정, 후보 범위 확정, 판정기 통일)을 설계해 주십시오.

**Q6. 후회 판정 기준·통계 확정**
- 후회 후보 판정: "KEEP∪SKIP에서만 pointwise p≥τ인 쿼리" — τ는 무답 쿼리 ≥50개로 보정한다(1차 B). τ 초기값과 보정 절차?
- 후회율 임계: "≥2~3% 또는 고심각 1건이면 cold tier 도입" (1차 B) — 합리적인가? SKIP 40건(실제 라이브 9건) 표본에서 이 임계가 갖는 통계적 한계(Wilson 상한)는?
- SKIP 유형·store_conf 구간별 분포 집계 — 어떤 집계 축이 cold tier 설계(보존 우선순위)에 가장 유용한가?
- **추가 질문**: payload NULL 발견(§2.1)이 "cold tier 도입" 판정 자체의 순서를 바꾸는가? (cold tier 도입 = SKIP 원문을 처음부터 보존하는 변경이므로, **감사는 도입 전에 오히려 못 돌리고 도입 후 전향적으로만 가능** — 이 순환을 깨는 방법은?)

---

## 4. 답변 시 반드시 지킬 것

1. **§1의 10개 확정분은 전제** — 다시 의심·재검토하지 말 것.
2. 실측(§2) vs 추측 구분: "데이터가 보여줌"과 "그럴 것 같음"을 문장마다 명시.
3. 각 Q의 선택지 (a)/(b)/(c) 중 하나를 명시적으로 선택하고 이유를 근거(§2 실측)로 제시.
4. 환경 제약: Windows 11 / CPU 전용 / RAM 15.6GB / Docker 불가 / Jev는 원격 API(요금 발생) / 라이브 DB 함부로 변경 불가 (스크래치 DB 또는 읽기 전용 probe만).
5. 답변 길이: Q당 5~10문장. 총 3페이지 이내.

---

## 5. (참고) 추가 실측이 필요한 경우의 실행 제약

- probe 스크립트는 스크래치 DB/읽기 전용으로만 실행 (라이브 DB 무접촉).
- Jev API 호출은 예산 소액(수백 콜)으로 제한 — probe 실패 시 재시도 없이 이 문서 Q4의 대안으로.
- 개인용 시스템이므로 정확도 1~2%p 수준의 개선은 실용 가치가 낮음 — 2×2 판정 기준에 이를 반영할 것.

---

*이 문서는 2026-10-03 기준 jev-memory-middleware v0.2.0 (커밋: `c3aee3a` 게이트 완화 / `59e5b11` Run O abstain / `f5aa4ef` quarantine 누출 수정 / `fd32a31` excerpt env) 및 라이브 DB 실측을 근거로 작성되었습니다.*