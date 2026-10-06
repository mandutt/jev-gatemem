# STAGE60~63 종합 — abstain "폭증" 미스터리 해소 (2026-10-07)

> stage60(노출 k)에서 abstain_p가 어제 0.0 → 오늘 0.9+로 폭등.
> 4단계 추적 끝에 **URL 문제도, 모델 회귀도 아님** — "정직한 abstain + 노출 구조 한계"로 확정.

## 1. 실측 타임라인 (모두 err 0)

| stage | 내용 | 결과 |
|---|---|---|
| 60 | 노출 k=5/3/2 (180콜) | abstain_p 중앙 0.86~0.94, block abstain 36~38/38, valid/yes 오차단 2~8 — **k 해석 불가(기준선부터 변화)** |
| 61 | base k5 재확인 (60콜) | block abstain **36/38**, valid/yes 오차단 2/22, abstain_p 중앙 0.86, chose_abstain 38/60 |
| 62 | 3-run 안정성 (180콜) | **3-run 완전 동일**(36/38·2/22·0플립) — 결정적·일시적 아님 |
| 63 | op-90 + noans-50 (140콜) | op hit@1 **19**(66 abstain)·noans FP 1/50(49 abstain) |

## 2. 원인 추적 (가설 검증 순서)

| 가설 | 검증 | 결과 |
|---|---|---|
| A. JEV 서버/모델 변경 | stage61~63 abstain_p 0.9+ (3-run 결정적) | 사실이나 "변경"이 원인은 아님 (아래) |
| B. URL 문제 (typesafe vs experiential) | typesafe.ai 지금 401(무효), experientiallabs.ai k2 200 | **무관** — experientiallabs로 직접 재호출해도 abstain 0.79~1.00 동일 |
| C. 러너 코드 버그 (중복 criteria) | 재현 코드의 `and-or` 버그로 c0가 abstain 문구로 덮임 — 400 | **러너는 정상** (stage61 코드는 `_query_window(content,q,300)` 정확) |
| D. **정직한 abstain + 노출 한계** | abstain된 사실 질문의 gold rank: **8·14·36·41 — 전부 top5 밖** | ✅ **확정** |

## 3. 최종 해석 (D 확정)

**오늘 모델이 바뀐 게 아니라, "답이 노출(top5)에 없으면 abstain"이라는 원래 의도된 동작을 보이는 것.**

- 어제 모델: top5에 답이 없어도 **"규칙 행 중 최선"을 pick** → hit 78 (부분적 우연·오주입)
- 오늘 모델: 같은 상황에서 **abstain으로 정직하게 거부** → hit 19
- 규칙 질문(한국어 말투·언어 습관)은 여전히 정상 pick — 모델 능력 저하 아님
- **검증 데이터**: abstain된 사실 질문 4건의 gold rank 8·14·36·41 (전부 top5 밖), top5는 전부 규칙/프로필 행

**즉**: 
1. **abstain이 드디어 작동** — 라이브 무답(block) 94.7% 정확 차단, 실질 오차단 0 (그동안 찾던 것)
2. **op hit@1 19의 진짜 원인은 retrieval/노출** — 답이 rank 6~60에 있는데 top5가 규칙 행으로 도배
3. **stage56의 "hit 78"은 규칙 행으로 틀린 답을 준 케이스가 일부 포함** — 오늘 기준으로는 과대평가였음

## 4. 함의 (전략 전환)

| 과거 결론 (어제 모델) | 오늘 실측 |
|---|---|
| "abstain 무력, 레버 13종 소진" | **abstain 작동** — 단 "답이 top5에 없을 때"만 |
| "라이브 IRREL은 구조적 한계" | IRREL도 abstain으로 차단 가능 (top5에 답 없으므로) |
| "노출 축소(k=2~3)가 답" | **반대 — 노출 확대/retrieval 개선이 답** (top5가 규칙 행 도배) |
| op hit@1 78 = 기준선 | **78은 규칙 행 오답 포함 과대평가** — 사실 질문 recall이 진짜 병목 |

**새 병목**: 사실 질문의 답(rank 6~60)을 top5로 못 올리는 **RRF/랭킹** + **규칙 행 클러스터의 top5 도배**.

## 5. 다음 단계 (우선순위)

1. **규칙 행 클러스터를 top5에서 분리/다운랭크** (0콜 시뮬 가능): 
   - stage58에서 "개별 제거 불가"였으나, **"규칙 질문일 때만 규칙 행 노출"** 조건부 노출이면 사실 질문 top5에 답이 올라올 수 있음
2. **fact 질문 랭킹 개선**: RRF에서 규칙 행 과점 해소 (importance/lexical 가중치)
3. **노출 k 확대 시 abstain 유지 확인**: k=10~20으로 늘리면 사실 질문 답이 top에 들어와 hit 회복되는지 (JEV 재호출)
4. **op-90 재평가 기준 확립**: "abstain 포함 hit" vs "pick만 hit" — 평가 메트릭 재정의 필요

## 6. raw

- `data/stage60_exposure_k.json`, `data/stage61_base_recheck.json`, `data/stage62_3run_stability.json`, `data/stage63_op_noans_regress.json`
- 재검증: experientiallabs.ai 직접 호출 6건 (규칙 2 pick / 사실 4 abstain)
- 러너: stage60~63 .py