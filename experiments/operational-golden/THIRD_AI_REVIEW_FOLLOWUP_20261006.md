# 3차 외부 AI 검토 후속 실측 — hybrid 잔재·τ 스윕·v2/v3 재계산 (2026-10-06)

세 AI(보류3건 검토) 답변 후속. 코드 확인·0콜 재계산 전부. JEV 추가 콜 없음.

## 1. 코드 실측: 운영 jev_rerank hybrid 분기 잔재 (B AI 지적 → 확인)

- `gateway/j1_pipeline.py` L776: `if len(pool) <= HYBRID_MAX_CANDIDATES:` — **TWO_CALL 플래그와 무관하게 항상 실행**되는 1콜 hybrid(choice+noul, noul τ=0.3) 분기
- 라이브 trace 실측: `jev-hybrid` 2건 / `|jev|` 29건 — 운영에서 실제 발동 중이었음
- stage37 3회 반복에서 **기각 확정된 구조**(hit@3 77 동일, noans FP 20 vs 16 열위)가 운영에 남아 있던 잔재
- **조치**: `JEV_HYBRID_ENABLED` env 가드 추가, 기본값 "0" (비활성). 실험 재현 시 env=1.
- 참고: 실험 러너(stage45 등)는 `jev_rerank`를 호출하지 않고 자체 choice 구현 → 실험 수치는 hybrid 비영향. 단 운영 수치와 실험 수치의 경로 차이는 남음.

## 2. 노출 구조 실측 (C AI 지적 → 확인)

- `jev_mem_core/pipeline.py _render`: `rows = rows[:5]` — **운영 실노출은 최대 5개**
- 요청서 "pick 1개 노출"은 부정확 — hit@3는 reranker 진단 지표, 실노출 지표는 hit@5 병행 필요
- 요청서 §0 정정 완료

## 3. τ 스윕 (B AI 제안, 0콜 — stage45 raw abstain_p 재계산)

| τ | current hit@1/hit@3/FP | improved hit@1/hit@3/FP |
|---|---|---|
| 0.1 | 73/76/17 | 71/74/9 |
| 0.2 | 74/77/24 | 73/76/20 |
| **0.3 (현행)** | **75/78/27** | **73/76/22** |
| 0.4+ | 75/78/27 | 73/76/22 (변화 없음) |

- **문구 효과는 τ와 무관하게 일관**: 같은 τ에서 항상 improved가 FP 4~8 적음 (문구=실효과)
- 단 op hit@3도 같은 τ에서 항상 1~2 손실 (τ=0.3: 78→76)
- τ≥0.4부터 민감도 0 — abstain_p 분포가 0.3 이하에 포진. **τ=0.1은 두 문구 모두 FP 급감 대신 hit@3 폭락** (76/74) — 과도 게이트
- B의 "같은 신호 두 번" 우려: 문구·τ 모두 abstain_p 축을 쓰지만 독립적으로 작동 — τ 조정만으로 improved의 FP 이득을 재현 불가
- **결론**: improved(τ=0.3) FP 27→22·op 78→76. τ=0.2로 옮기면 current 77/24 vs improved 76/20 — op 1 손실 대가 FP 4 이득. 채택 판단은 u·h 실측(아래)에 의존.

## 4. v2/v3 스냅샷 재계산 (B AI 제안 — 분모 포함, 0콜)

stage32 raw(pick_id 있음) + 스냅샷 코퍼스 DF:

| 규칙 | FP 차단 | 대상 FP (분모) | op 오차단 | 대상 op (분모) |
|---|---|---|---|---|
| v2 (underscore/숫자 혼합) | **5** | 6 | **0** | 12 |
| v3 (IDF DF≤10) | 4 | 6 | 0 | 28 |

- **v2와 v3는 별도 휴리스틱** (v2=형태 기반 underscore/dot, v3=DF 기반): v3가 잡은 4건(browser.backend·JEV_API_URL·diag6·diag63) 중 dot형(browser.backend)은 v2 regex로도 포착, 일부 중복 — **"상위호환" 아님** (C AI 지적 수용, 2026-10-06).
- **v2의 장점** (B AI 지적): 형태 기반은 코퍼스 DF 비의존 → **시간 드리프트 없음** (v3의 DF 기반과 대비)
- 오차단 0의 한계: 대상 op 12건 기준 (0/12 → 95% 상한 ~22%) — 실트래픽 별칭 변형(표기 변형)에선 다를 수 있음
- **권장**: 사안 2는 v3(기각) → **v2(형태)로 방향 전환**. 운영 도입 전 라이브 샘플 라벨링으로 오차단 리스크 확인 필요

## 5. 후속 (미실행, 권장만)

1. **라이브 쿼리 60건 사람 라벨링** — u_true·실제 FP율·h 측정 (사안 1·3 공통 최고 가치, 0콜)
2. **평가 세션 retrieval 제외** (eval scope/세션 필터) — 자기참조 오염 원인 제거 (사안 3 보완)
3. **150자 윈도우 직접 선택 변형 (140콜)** — 정보량 동일·품질만 개선하는 미시도 레버

## 참조

- raw: `data/stage45_abstain_label_snapshot.json` (τ 스윕), `data/stage32_hybrid_pool30.json` (v2/v3)
- 코드: `gateway/j1_pipeline.py` (hybrid 가드), `jev_mem_core/pipeline.py` (rows[:5])