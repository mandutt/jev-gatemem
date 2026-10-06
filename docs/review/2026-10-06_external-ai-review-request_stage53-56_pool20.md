# 외부 AI 검토 요청 — stage53~56 미실측 3건 실측 완료 + pool20 채택 판단 (2026-10-06)

- 목적: 지난 3종 AI 검토(v2, `2026-10-06_external-ai-review-request_보류3건+abstain무력_v2.md`)에서
  "미실측"으로 남았던 3건을 전부 실측 완료했다. 결과를 보고하고 다음 판단(코드 반영 여부 포함)을 자문한다.
- 전제: 아래 모든 수치는 실측(raw JSON·러너 포함, err 0). **추가 정보 없이 답변 가능하도록 자족적으로 기술.**

## 1. 시스템 요약 (현행 운영 구조)

- 파이프라인: SQLite 메모리(스냅샷 1,721+113행) → 4-lane RRF(FTS5+vec+importance+graph)
  → `_filter_and_rank` 게이트 (기본값 (1, 0.0)) → **pool 60** → JEV(SystemOne) **choice 1콜** rerank
  → abstain 시 빈 컨텍스트, pick 시 top-5 노출
- 후보 라벨: `_query_window`(쿼리 인지 300자) → `_excerpt`(150자) — **win-300 excerpt 전면 적용**
- soft gate: choice의 abstain 라벨 확률 > 0.3 → 빈 컨텍스트 (`JEV_SOFT_ABSTAIN_TAU=0.3`)
- 임베딩 bench/bekko-a8m (384d, 로컬) / 일반 LLM 사용 금지 원칙 (메모리 경로 LLM = JEV 전용)
- 평가 기반: `snapshots/mnemosyne_snapshot_20261006.db` (1721행, 2026-10-06 동결)

## 2. 배경 — v2 요청서의 미실측 3건

| ID | 제안 | 요지 |
|---|---|---|
| A-7 | pool 60→20 | 후보 축소로 softmax 집중 — 무답 abstain 증가 |
| B-4 | 두 abstain 라벨 | "같은 주제지만 답 아님" + "관련 없음" 분리 |
| C-4 | 진짜 2콜 | winner 1개를 noul로 재검증 (τ=0.5) |

## 3. 실측 결과

### 3.1 stage53 — 3건 실측 (100쿼리 {live 60 + op 20 + noans hard 20}, 500콜, err 0)

| 구조 | IRREL 차단 (17) | 정답희생 (38) | noans hard FP (20) |
|---|---|---|---|
| base (현행) | 0 | 0 | 13 |
| pool20 (A-7) | 0 | 0 | 8 |
| dual (B-4) | 1 | 0 | 7 |
| two_call (C-4) | 2 | 0 | 5 |

- **라이브 IRREL(이웃 존재형 무답) 차단은 3구조 모두 여전히 미미** (0~2/17) — abstain 무력 재확인.
- **정답희생 0** — 전부 안전.
- 하드 noans FP는 3구조 모두 절반 이상 개선 (13→5~8) — pool20=softmax 집중(A 지지),
  dual=라벨 분리(B 지지), two_call=winner 재검증(C 지지, 최강).

### 3.2 stage54 — op-90 회귀 1-run (360콜, err 0)

| 구조 | hit@1 | hit@3 | abstain |
|---|---|---|---|
| base | 79 | 80 | 3 |
| pool20 | 78 | 79 | 2 |
| dual | 77 | 78 | 6 |
| two_call | 76 | 77 | 7 |

- dual·two_call은 abstain +3~4 (과다거부) → op 손실 > FP 이득 → 기각.
- pool20만 -1 (비결정성 범위로 보임) → 유일한 후보.

### 3.3 stage55 — pool20 3-run (270콜, err 0)

- 3-run 전부 hit@1 78 / hit@3 79 / abstain 2 — **완전 동일, 비결정성 0**.
- → pool20의 "-1"은 실질·재현 가능해 보였으나, **이건 세션 분리 측정(다른 날·다른 시각)의 한계**였다.

### 3.4 stage56 — ★풀 비교 (같은 세션 3-run paired, op 90 + noans 50, 840콜, err 0)

| 구조 | hit@1 (3-run) | hit@3 | abstain | noans FP (3-run) |
|---|---|---|---|---|
| base | 78 / 78 / 78 | 79 / 79 / 79 | 2·2·3 | 21 / 22 / 21 (평균 **21.3**) |
| pool20 | 78 / 78 / 78 | 79 / 79 / 79 | 2·2·2 | 13 / 13 / 13 (평균 **13.0**) |

- **op hit@1/3: 두 구조 완전 동일 (78/79)** — stage54 base 1-run의 79/80은 세션 잡음이었고,
  **pool20의 "-1 회귀"는 착시** (같은 세션에서는 회귀 0).
- **noans FP: 21.3 → 13.0 (−8.3, −39%)** 같은 세션 확정.
- **쿼리별 majority 대조: 차이 4건뿐, 2:2 상쇄**:
  - pool20 개선 2건 (#58 KoDialogBench 검증, #72 pi 프록시 목록)
  - pool20 손실 2건 (#80 deepseek 장문 문제, #87 camelai-serial-proxy 기능)
  - → **체계적 손실 없음**, 무작위 변동 수준.
- 참고: stage53 noans 샘플 20의 base 13 vs stage56 noans 50 전체 21.3 — **noans 셋 크기 의존성** 확인.

## 4. 요청 사항 (판단 자문)

### Q1. pool20 채택 타당성
같은 세션 paired 3-run에서 **op 무회귀(78/79 동일) + noans FP −39% (21.3→13.0)** — 트레이드오프가 아닌
일방 개선으로 보입니다. 다만:
- (a) pool 60→20은 **retrieval 커버리지 상한을 낮추는 구조 변경** — 답이 rank 21~60에 위치하는 케이스는
  이전엔 choice가 건질 기회가 있었으나 이제 영구 소실. stage49d 실측("답 놓침 21건 전부 pool 안 rank 6~60,
  표본 rank 8~9")과 stage50c/d 실측("실운영 풀 답 rank 1~3, 15/18")을 종합하면 실손실 0~2건으로 추정되지만,
  **op-90 셋 기준으로는 "답 rank 21~60" 케이스가 0건이었기 때문에 실측에서 드러나지 않았을 수 있다**는
  우려가 있습니다. 이 셋 바깥에서의 위험을 어떻게 평가해야 할까요?
- (b) noans FP "개선"이 실질 이득인지 — base FP 21.3건은 "답 없는데 메모리 노출"이고, 표본 50의 하드 noans는
  실제 라이브 무답(이웃 존재형 IRREL)과 메커니즘이 다릅니다 (§3.1: IRREL 차단은 여전히 0~2/17).
  **하드 noans FP 감소가 라이브 오주입 감소로 이어질 근거가 있는지** — 아니면 하드 noans 방어만의 격리된
  이득(라이브엔 무관)으로 봐야 하는지 판단해 주십시오.
- (c) 채택한다면 **릴리스 게이트 요건** — 저희 프로토콜(같은 세션 paired 3-run + 라이브 60 교차) 외에
  추가 검증이 필요한지.

### Q2. 방법론 — 세션 분리 측정의 함정
stage54(base 1-run 79/80) vs stage55(pool20 3-run 78/79)의 "-1"이 실제로는 세션 잡음이었고,
같은 세션 paired 3-run에서 차이 0으로 정정되었습니다. **파이프라인 변경 평가는 반드시 같은 세션 paired
3-run** 이라는 교훈을 확립하려 하는데, 이 방법론에 대한 반론이나 보완(예: 쿼리 순서 효과, 하루 중 시간대
효과, JEV 모델 버전 고정 등)이 있는지 지적해 주십시오.

### Q3. 코드 반영 시 주의점
`POOL_BUDGET = 60 → 20` 한 줄 변경으로 계획 중입니다. 라이브 데몬(j1_pipeline)과 실험 러너가 같은
상수를 공유하므로, 검증 순서(스모크 → 같은 세션 회귀 → 라이브 60 → 데몬 재시작)에 놓칠 수 있는 것이
있는지 지적해 주십시오.

### Q4. 잔여 사안 우선순위
- (a) **라이브 IRREL(이웃 존재형 무답) 차단 불가** — 9종 레버 + 이번 3구조까지 소진. 남은 선택지
  (부분 채택 noul<0.5 / 판정자 교체 / 상위 1~3 [LOW_CONF] 노출) 중 어느 것도 실측상 유망치 않음.
  완전히 포기하고 "하드 noans 방어만 있는 구조"로 갈지, 다른 방향이 있는지.
- (b) **B-5 eval 세션 코퍼스 제외** — v2 요청서의 4번째 미실측 건 (평가 쿼리·실험 대화가 메모리에
  쌓여 noans 셋을 변질시키는 문제의 구조적 해결). 아직 미실측 — 우선순위가 낮은지 판단.
- (c) **dual/two_call 기각 확정** — op abstain +3~4가 결정적이었습니다. 이 판단에 이견이 있는지.

## 5. 부수 교훈 (참고용)

- **JEV 키별 한도 독립 실증**: 키1 일일 소진(47,618,188/47,619,047) 시에도 키2는 새 할당으로 동작.
  시작 전 두 키 1콜 probe → 잔여 키로 시작, 429 본문 'daily free allowance' → 해당 키를
  `rot.exhausted_until`에 넣어 정각까지 제외 (on_429는 순환만).
- 메모리 경로 LLM = JEV 전용 원칙 유지 중 (일반 LLM 간섭 없음).

## 6. raw 자료 (전부 커밋·푸시됨, `mandutt/jev-gatemem`)

| 파일 | 내용 |
|---|---|
| `experiments/operational-golden/STAGE53_MISSED3_20261006.md` | stage53 실측 정리 |
| `experiments/operational-golden/STAGE54_OP90_REGRESS_20261006.md` | stage54 회귀 정리 |
| `experiments/operational-golden/STAGE55_POOL20_3RUN_20261006.md` | stage55 3-run 정리 |
| `experiments/operational-golden/STAGE56_FULL_COMPARE_20261006.md` | stage56 풀 비교 정리 |
| `experiments/operational-golden/data/stage53_missed3.json` | 500콜 raw |
| `experiments/operational-golden/data/stage54_op90_regress.json` | 360콜 raw |
| `experiments/operational-golden/data/stage55_pool20_3run.json` | 270콜 raw |
| `experiments/operational-golden/data/stage56_full_compare.json` | 840콜 raw |
| `experiments/operational-golden/RECALL_ABSTAIN_INVESTIGATION_20261005.md` §14 | 전체 통합 기록 |
| `experiments/operational-golden/stage{53,54,55,56}_*.py` | 러너 (재현 가능) |