# 외부 AI 검토 요청서 v5 — 보류 7건 + stage83~89 confound 해소 실측 (2026-10-07)

- 작성일: 2026-10-07
- 대상: 메모리 파이프라인 (jev-mem) — SQLite + 로컬 임베딩(bekko-a8m) + 4-lane RRF + JEV choice 1콜 + soft gate
- **성격**: ⏸️ **보류 5건에 대한 판단 요청** + 📋 **v4 검토 후 실측(stage83~87) 보고**.
  당장 답변 불필요 — **추후 요청 건이 쌓이면 일괄 검토 예정** (사용자 지시).
- **전제**: 전 수치는 실측(raw JSON·러너 포함, err 0, 데몬 venv 고정, 스냅샷 고정). 자족적으로 기술.

---

## 0. 시스템 요약 (10-07 현재)

| 항목 | 값 |
|---|---|
| 저장소 | SQLite 스냅샷 1,721+113행 (2026-10-06 동결) |
| 임베딩 | bekko-a8m 384d (운영) — gemma2 3-way 기각 |
| 검색 | 4-lane RRF → 게이트 (1, 0.0) → **pool 60** |
| rerank | JEV choice 1콜, abstain 라벨 cN (current 동결) |
| soft gate | abstain_p > 0.3 → 빈 컨텍스트 (라이브 dead code — abstain_p≈0) |
| 노출 | **rows[:5] Top-5** (k=2 검토 보류 중, 아래 사안 A) |
| 평가 프로토콜 | 같은 세션 paired 3-run + **production-exact pool** (시간 필터 없음, 10-07 확립) |

**10-07 확립된 핵심 사실 (v4 이후)**:
- **모델/서버 불변** (stage83: k60 abstain 0/38 — 10-06과 동일)
- **abstain 폭증은 k=5 러너 인공물** (후보 수 60→5 효과) — stage60~66 전부 무효화
- **production-exact op hit@1 = 78** (시간 필터 무관 — 평가 인프라 정상)
- **read-path 레버 14종 소진** — 라이브 무답(IRREL) 방어는 read-path로 불가 확정

---

## 1. 📋 v4 검토 후 실측 보고 (stage83~87, 전부 커밋·푸시)

### stage83 — 60 vs 5 candidate control (360콜, 같은 세션 3-run)
| 조건 | block abstain | valid+yes 오차단 | abstain_p 중앙 |
|---|---|---|---|
| k60 (production) | **0/38** (0·0·0) | 0 | 0.00 |
| k5 (실험) | **36/38** (36·36·36) | 2 | 0.84~0.86 |

→ **"10-07 모델 변경" 기각. abstain = 후보 수 효과** (b-ai 추측 실측 입증). 10-06 "abstain 무력" 유지.

### stage84 — 후보 수 곡선 {5,10,20,40,60} (1,000콜)
| k | op hit@1 | noans FP | live block abstain |
|---|---|---|---|
| 5 | 19 | 1* | 36/38 |
| 10 | 71 | 6 | 2/38 |
| 20 | 78 | 15 | 0 |
| 40 | 77 | 18 | 0 |
| 60 | 79 | 20 | 0 |

→ abstain은 k=5 극단에서만. k 안전 하한 20. k20 vs k60 = 정답 -1 vs FP -5.

### stage85 — production-exact pool20 게이트 (400콜)
- **op90 gold rank>20 = 2건** (rank 41·36) → **C AI 롤백 규칙 발동: pool20(및 30/40) 채택 금지**
- live60 paired 3-run: k20/k60 모두 block abstain 0/38 — 라이브 방어 무영향
- noans FP: k20 15 vs k60 22

### stage86 — candidate diversification (600콜)
- cap1/2/3 × (op90+live60) — **모두 base와 동일 (78/79, live 0, 오차단 0)** → 기각 (14번째 소진)
- 교훈: **0콜 노출 시뮬(top5 19→70) ≠ JEV 60개 lift 실측** — JEV가 60개에서 gold를 고르므로 노출 구성 무영향

### stage87 — 노출 k 실측 (200콜, 같은 JEV 결과 재해석)
| 지표 | k=5 | k=2 |
|---|---|---|
| op hit@1/3 | 78/79 | **78/79** (보존) |
| noans FP율 | 21/50 | 21/50 (동일) |
| **noans 노출 행 수** | 105 | **42 (-60%)** |
| **live block 노출 행 수** | 190 | **76 (-60%)** |
| valid 오차단 | 0 | 0 |

→ **k=2: 정답 회수 100% 보존 + 오주입 피해 60% 감소** — abstain 불가 구조의 유일한 피해 축소 레버.

---

## 2. ⏸️ 보류 5건 — 판단 요청

### 사안 A: 노출 k=2 (최우선 — 유일한 적용 가능 레버)
- 실측: stage87 — hit@1/3 보존, 오주입 노출 -60%, FP율 동일(21/50)
- **판단 요청**: k=2 채택 vs k=3(절충) vs 유지(5). "FP율이 안 줄어드는데 의미가 있나" — 노출 수 감소의
  실질 가치(소비 에이전트 앵커링·환각 근거 축소)를 어떻게 정량화할 수 있을지.
- 참고: 노출 자체는 Hermes 시스템 프롬프트 주입 경로 — k=2로 줄면 "오주입 5개"가 "오주입 2개"가 됨.

### 사안 B: IDF v2 (특정성 감지기) — **실측 기각 근거 확보 (2026-10-07, stage90)**
- stage57 0콜 시뮬: winner-only 13구제·0오차단 / top5-any 12구제·0오차단 — 유망해 보였으나
- **stage90 JEV 실측 (200콜)**: 라이브 60에서 **IDF 발동 1/60 (1.7%)** — 실질 무가치
  - 라이브 쿼리 대부분이 식별자 미포함 ("~기능 정리해줘", "~왜 실패해?") — 발동 기회 자체가 없음
  - 49c 셋의 "12구제"는 식별자 쿼리 밀집의 특수성 — 실제 트래픽과 괴리
- k2+idf 조합도 추가 이득 0 (IDF가 안 걸림) — noans FP 21/50 동일
- **판단 요청**: 기각 확정 여부 (실측상 파이프라인 레버로 무가치)

### 사안 C: 소비 측 프레이밍 (미실측)
- "참고용 메모리 — 직접 답이 아니면 무시" 블록 헤더 (B·A 수렴, ~57콜)
- **판단 요청**: Hermes 시스템 프롬프트에 이 완화문을 넣는 것이 방법론적으로 타당한지
  (메모리 경로 밖 = 원칙 충돌 없음 주장). 실측 설계 자문.

### 사안 D: 일일 canary (미구축)
- 고정 쿼리 30~40개 매일 실행 → abstain율·pick 분포 drift 감지 (40콜/일)
- **판단 요청**: canary 쿼리 선정 기준 (무엇을 잡아야 하나 — 모델 변경? 파이프라인 회귀?),
  운영 통합 방식 (cron? 데몬?).

### 사안 E: pool20 재론 여부
- stage85 게이트에서 기각 (rank>20 2건) — 그러나 k=2 채택 시 "노출 수 축소"라는 대안 경로가 생김
- **판단 요청**: k=2 채택 시 pool20 재론이 의미가 있는지 (criteria 토큰 절감 ~35% vs 정답 2건 유실),
  아니면 영구 종결인지.

### 사안 F (신규, 10-07 보강): abstain_p 상향 추세 — soft gate τ 재조정?
- 실측 (stage88, 0콜): 라이브 데몬 trace — abstain_p 중앙 **10-06 0.00 → 10-07 0.11** (n=14),
  abstain 선택 1/14 (7%), abstain_p>0.3 0건 (gate dead code 유지)
- **판단 요청**: ① 이 추세가 실질적인가 (14건 표본 한계) ② τ=0.3 유지 vs 0.2/0.1 하향 —
  abstain_p가 천천히 오르면 gate가 "곧" 걸리기 시작 — 그때까지 기다릴지, 선제 조정할지
  ③ canary(사안 D)로 추세를 모니터링하는 설계가 충분한지

### 사안 G: 2질문 분리 구조 — **실측 기각 (2026-10-07, stage89~92)**
- API 2질문 동시 전송 1콜 지원 확정 (probe) — 기술적 가능성은 확인
- **stage89 (rule6+fact20)**: rule_q abstain 76% ★ (b-ai 가설 실측 확인) but op hit@1 -11
- **stage91 (rule6+fact60)**: op 78 복원 (base 79와 -1), rule_q abstain 74% 유지
  - 0콜 시뮬 "규칙 노출 제거" 결합: 무답 노출 -59% + op 손실 0 (op-90 기준)
- **stage92 (3-run 안정성)**: rule_q abstain 77% 안정적 (플립 2/38) **but valid/yes 규칙 오차단 2.3/22 (10%)**
  - 정답이 규칙 행인 쿼리에서 규칙 노출 제거 → **정답 유실 위험 10%**
  - stage91의 "손실 0"은 op-90 셋 특수성 (규칙 답 gold 없음) — 라이브에는 규칙 답 존재
- **최종 판단**: k=2(사안 A)가 동급 피해 축소(-60% vs -59%) + 정답 유실 0 + 구현 1줄로 **우월** → **G 기각

---

## 3. 참고 — 확정·기각된 사안 (재검토 불필요)

- abstain 라벨 current 동결 (3-way) / 스냅샷 표준 (3-way) / gemma2 기각 (3-way) / 게이트 재정렬 기각 /
  noul 구조 전수 기각 / excerpt 전수 기각 / 허브·meta 라벨·rank-veto 기각 / **pool20·diversification 기각**
- "모델 변경" 의혹 종결 (stage83)

---

## 부록: raw 자료 (전부 커밋·푸시됨)

| 파일 | 내용 |
|---|---|
| `experiments/operational-golden/STAGE83_60VS5_CONTROL_20261007.md` | confound 해소 (360콜) |
| `experiments/operational-golden/STAGE84_CANDIDATE_CURVE_20261007.md` | 후보 수 곡선 (1,000콜) |
| `experiments/operational-golden/STAGE85_POOL20_GATE_20261007.md` | pool20 게이트 (400콜) |
| `experiments/operational-golden/STAGE86_DIVERSIFICATION_20261007.md` | diversification 기각 (600콜) |
| `experiments/operational-golden/STAGE87_EXPOSURE_K_20261007.md` | 노출 k 실측 (200콜) |
| `experiments/operational-golden/STAGE88_TRACE_TIMESERIES_20261007.md` | 데몬 trace 시계열 (0콜) |
| `experiments/operational-golden/STAGE89_DUAL_QUESTION_20261007.md` | 2질문 분리 실측 (400콜) |
| `experiments/operational-golden/STAGE90_K2_IDF_20261007.md` | k2+IDF 조합 실측 (200콜) |
| `experiments/operational-golden/STAGE91_DUAL2_20261007.md` | 2단 구조 실측 (400콜) |
| `experiments/operational-golden/STAGE92_DUAL2_3RUN_20261007.md` | 사안 G 3-run 검증 (180콜) |
| `experiments/operational-golden/data/stage{83,84,85,87}_*.json` | raw (stage86 raw 유실 — 로그 대체) |
| `experiments/operational-golden/stage{83,84,85,86,87}_*.py` | 러너 (재현 가능) |
| `docs/review/2026-10-07_external-ai-review-request_v4_종합개정판.md` | v4 + §8(사안9) |

## 요청 형식 (추후 일괄 검토 시)
사안별로: **① 판정 (채택/기각/수정/보류 유지) ② 근거 (실측 인용) ③ 권장 다음 단계 (콜·비용 포함)**.
특히 사안 A(k=2)의 실질 가치 정량화를 중점 부탁드립니다.