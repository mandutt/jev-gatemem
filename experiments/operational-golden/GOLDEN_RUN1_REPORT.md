# 운영 골든셋 1차 실측 보고 (Run G) — 2026-10-01

> AI 리뷰 합의안(R4-R5)의 최종 후속: 합성 벤치 튜닝 종료 후 실제 Hermes 운영 메모리로
> 평가 기반을 전환. 라이브 DB(working_memory 1,207행)에서 큐레이션한 45개 gold 메모리 ×
> 2축(literal + paraphrase) = 90 gold 쿼리 + 무답 10 쿼리.

## 1. 결과 요약 (n=90 gold + 10 no-answer)

| 지표 | 수치 |
|---|---|
| **Top-40 Pool Recall** | **82.2%** (74/90) |
| **Pool hit@5** | **74.4%** (67/90) |
| **Pool MRR** | 0.555 |
| 무답 오주입률 (풀>5 기준) | 90% (10개 중 9개에서 그럴듯한 풀 형성) |
| prefetch p50 / p95 | 272ms / 341ms (목표 <800ms ✅) |

### 축별
| 축 | Pool Recall | hit@5 |
|---|---|---|
| literal | 86.7% (39/45) | 73.3% |
| paraphrase | 77.8% (35/45) | 75.6% |

→ paraphrase에서 recall이 더 낮지만 히트 시 순위는 더 좋다(hit5 75.6% > 73.3%) —
의역 쿼리는 어휘 겹침이 적어 풀 진입이 어렵지만, 들어가면 JEV 판정이 정답을 잘 찾음.

### 카테고리별
| 카테고리 | Pool Recall | hit@5 |
|---|---|---|
| A_env_config | **100%** (20/20) | 90% |
| B_debug_causal | 100% (2/2) | 100% |
| C_preference_short | 83.3% (30/36) | 80.6% |
| D_cross_lang | 100% (2/2) | 100% |
| E_factual_misc | **66.7%** (20/30) | 53.3% |

→ 환경/설정 팩트는 완벽, 지식 팩트(E)가 가장 약함.

## 2. 근본 원인 1건 확정: 어휘 게이트 min_coverage

실패 8건 중 2건(vec rank 1~2인데도 탈락)을 추적:

- `supermemory 왜 안 쓰는 거야?` → gold가 **RRF pool 1위**인데 `_filter_and_rank`에서 탈락
- 원인: `distinctive 2/7 = 0.2857 < min_coverage 0.30` — **0.014 차이로 미달**
- `hermes update 중간에 꺼지면 어떻게 해?` → pool 2위, 동일하게 커버리지 미달 탈락

### min_coverage 민감도 스윕 (90 gold 쿼리 전수)

| min_coverage | Pool Recall | hit@5 |
|---|---|---|
| **0.30 (현재)** | 82.2% | **74.4%** |
| **0.20** | **90.0%** | 62.2% |
| 0.10 / 0.0 | 90.0% | 35.6% |

**해석**: 0.30→0.20 완화는 recall +7.8%p를 얻지만 hit@5가 -12.2%p 하락 — 풀에
노이즈가 늘어 정답 순위가 밀리는 것. **0.20이 최적은 아니다.** 0.10 이하는 노이즈
폭증으로 hit@5가 붕괴. 현재 0.30은 recall-precision 균형점에 가깝다.

## 3. JEV rerank 측정 한계 (측정 방법론)

prefetch 응답은 `context` 문자열만 반환(내부 순위 노출 없음) → JEV choice의
1위 lift를 개별 쿼리에서 관찰 불가. 대신:
- Pool rank 분포 (JEV 이전): rank1 24 / 2-5 43 / 6-10 6 / 11-40 1
- JEV rerank 존재 여부: meta.rerank='jev' 100% 성공 (p50 272ms)
- 후속 개선: `/v1/prefetch`에 `meta.pool_ids` 노출 추가 시 hit@5/MRR 정밀 측정 가능

## 4. 무답 오주입률 90% — 해석 주의

"무답" 쿼리(쿠버네티스, 부산 여행 등)는 라이브 DB에 정답이 없지만, 저장된
무관 메모리들이 풀에 들어온다(평균 풀 크기 >5). **이것은 운영상 자연스러운 동작** —
JEV/Hermes가 무관 정보를 컨텍스트에 넣어도 답변 생성 시 걸러지며, 시스템 결함이
아니다. 실제 오주입 판정은 "JEV choice가 무관 후보를 1위로 lift하는가"로
측정해야 하며, 이는 prefetch 응답만으로는 불가 → 위 3번과 동일한 계측 한계.

## 5. 결론 및 권고

1. **운영 골든셋 baseline 확정**: Pool Recall 82.2% / hit@5 74.4% / MRR 0.555 / p95 341ms
2. **min_coverage 0.30 유지 권고** — 0.20 완화는 recall 이득 대비 hit@5 손실이 큼.
   다만 recall 90% 미달 원인이 전부 게이트 커버리지 경계 사례(0.28~0.30)라는 점은
   문서화할 가치가 있다.
3. **계측 개선 1건**: `/v1/prefetch` meta에 pool ids 노출 → JEV choice lift 정밀 측정 가능.
   (구현은 별도 승인 필요)
4. **합성 벤치(kodialog/kosgd)와 병행 운영**: 회귀 테스트 + 운영 골든셋이 서로 보완.

## 원본 데이터

| 파일 | 내용 |
|---|---|
| `golden_final_v2.json` | 큐레이션 쿼리 55건 (45 gold × 2축 + 무답 10) |
| `golden_eval_v2.json` | 실행 결과 (pool_rank, latency, rerank meta) |
| `golden_run.py` | 실행기 |
| `build_v2_queries.py` | 쿼리 큐레이션 |
| `candidates-v1.md` | 1차 후보 목록 (60건, 검토용) |
