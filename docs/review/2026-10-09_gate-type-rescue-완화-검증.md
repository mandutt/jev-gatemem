# stage106 — 게이트 규칙 수정 검증: type-rescue 완화 (2026-10-09)

- 목적: `[IMPORTANT: Background]` 자동 발화가 type-rescue로 저장되는 것 방지 후보 검증
- 방식: 라이브 JEV 콜(9샘플 + 유용 23건 + 8회귀) + 0콜 trace 재계산(279건)
- 판정: **기각 (코드 변경 없음) — '저장은 관대·리콜은 정밀' 구조가 정보 보존에 우월**

## 배경

[IMPORTANT:] 자동 발화 121건이 저장됨 → '저장 게이트가 잡지 못한다' 우려 → 게이트 규칙 완화 후보 검증.
그러나 추가 실측으로 (a) 저장돼도 무해(리콜에서 노이즈 없음) (b) 유용한 자동 발화가 있음이 확인되어, **수정 자체가 손실**로 판정.

## 수정안 (검증 대상이었던 규칙)

```
NO_STORE && store_conf >= 0.6:
    type in (NO_STORE, event, context, observation)  -> SKIP   [후보]
    그 외                                      -> KEEP (type-rescue 유지)
```

## ① 라이브 JEV 콜 — 9샘플

| 샘플 | 기존 | 후보 규칙 | 비고 |
|---|---|---|---|
| plain 완료 no-Output x2 | KEEP | SKIP (NO_STORE/event .63/.67) | 노이즈 — 걸러짐 ✓ |
| plain 완료 Output x2 | KEEP | SKIP (NO_STORE/event .81/.69) | 노이즈 — 걸러짐 ✓ |
| fail exit≠0 x2 | KEEP (STORE/error) | KEEP (STORE/error .54/.92) | 정보 — 유지 ✓ |
| watch 매칭 x2 | KEEP/SKIP | SKIP x2 | |
| batch 요약 x1 | SKIP | KEEP (low-conf .59) | △ |

## ② 유용한 자동 발화(recall>0) 23건 재판정 — **핵심 기각 근거**

| 결과 | 건수 | 내용 |
|---|---|---|
| **KEEP** | **10** | verifier 재평가(STORE)·camelai 벤치·statem PASS/FAIL·실패(exit≠0, error) |
| **SKIP** | **13** | recall 32(statem 실험 로그)·13(phase_b)·12·11·10(벤치 결과)·7×2·2·1×3 — **전부 JEV가 NO_STORE로 판정** |

→ **실제로 recall되는 정보의 절반 이상(13/23)이 후보 규칙에서 걸러짐** — '나중에 recall되는 정보' 보존 실패.
특히 recall 32(가장 많이 재조회된 행)가 NO_STORE 판정으로 SKIP = 결정적 손실.

## ③ 일반 발화 회귀 8종

commitment/error/instruction/artifact → KEEP ✓ / filler 4종 → SKIP ✓ (8/8 — 후보 규칙의 일반 발화 오탐 없음)

## ④ 0콜 trace 재계산 279건

KEEP→SKIP flip 5건: 4건 `[IMPORTANT:]` + **1건 사용자 발화**("일단 지금은 텔레그램으로 전송해", event conf .82) — event 통째 SKIP은 사용자 event 발화도 희생.

## 판정 — 기각 (코드 변경 없음)

1. **저장 게이트는 '미래 유용성 예측' 문제** — 자동 발화를 문맥 없이 보고 "저장 가치"를 판정하면 recall 32 로그도 NO_STORE로 오판. 예측은 구조적으로 불완전.
2. **리콜 층은 '쿼리-행 관련성' 문제** — 쿼리가 주어지면 같은 행을 "이 질문의 답"으로 정확히 판정 (334 JEV pick 중 IMPORTANT 0건 — 저장돼도 노이즈가 되지 않음, FTS 상위 진입도 벤치 결과 쿼리에서만).
3. 따라서 **저장은 관대하게(현행 유지), 리콜 층이 걸러내는** 구조가 정보 보존에 우월 — 후보 규칙은 유용 13건을 SKIP해 손실.
4. 저장된 121건 정리도 불필요 (무해 실측).

## 산출물

- `experiments/operational-golden/stage106_rule_probe.py` — 9+23+8 JEV 콜 재현
- `experiments/operational-golden/data/stage106_rule_raw.json` — raw
- `experiments/operational-golden/stage105_imp_ab_probe.py` + `data/stage105_imp_ab_raw.json` — 지시문 보강 A/B(효과 없음, flip 0)
- trace 재계산: 본 문서 §4 (0콜)

## 연계 결론 (이 세션 확정)

| 실측 | 결론 |
|---|---|
| [IMPORTANT:] 저장 경로 | type-rescue가 NO_STORE/event를 KEEP (trace: KEEP 5건 전부 reason=type-rescue) — **그대로 둠** |
| 저장 시 못 거르는 이유 | G-qual은 '미래 유용성' 예측 문제 — 자동 발화는 문맥 없이 보면 완료 보고일 뿐 |
| 리콜 시 거를 수 있는 이유 | FTS 키워드+임베딩+JEV choice가 '쿼리-행 관련성' 비교 문제를 풂 — 훨씬 쉬움 |
| 유용 자동 발화 | JEV가 STORE로 인식 시 KEEP (10/23) — recall 32 로그는 NO_STORE로 보존 안 됨 (구조적 한계, 수용) |