# Run P/Q — 잔여 미스 원인 진단 + GLiNER2.5-multi-Decide 쓰기 게이트 오프라인 평가 (2026-10-02, JEV 0회)

> 외부 AI 3종 검토 종합의 검증 실험. SoT: 이 파일 + `run_p_miss_diagnosis.py` + `run_p2_gate_reasons.py` + `run_q_gliner_gate.py`.

## Run P — Pool 탈락 9건 원인 진단 (게이트 문제 vs 임베딩 품질 문제 분리)

Run M(2026-10-01)의 9건 탈락을 게이트-이전 vec raw rank(k=100)까지 추적해 재분류.

| 분류 | 건수 | 세부 |
|---|---|---|
| 레인 풀에는 있으나 게이트 탈락 | 8 | overlap<2 6건 / coverage<0.30 2건 |
| 레인 풀 자체 부재 (vec top-100 밖) | 1 | paraphrase "전환 전 어떤 문제 있었지?" |

- **vec raw top-100 내부에 gold 없음 (0/9)** — b-ai 가설 "gold가 vec top-N 안에 있으면 게이트 예외로 해결" 기각.
- 탈락 8건 전부 **게이트 요건(overlap≥1)을 못 넘는 의역 쿼리**. 예외 확장 시뮬: vec≤5 +overlap≥1 → 1/8, vec≤10 → 2/8, vec≤22 → 5/8 (토큰 비용 대비 미미, Run M 결론 재확인).
- **결론 확정: 잔여 10% 미스는 임베딩 모델 품질(의역 수용력) 문제** — 게이트 튜닝으로 회복 불가.
- 원본: `run_p_miss_diagnosis.json`, `run_p2_gate_reasons.json` (scratch/perfectrecall).

## Run Q — GLiNER2.5-multi-Decide 쓰기 게이트 오프라인 평가 (gold50_as, n=50)

- 모델: `fastino/GLiNER2.5-multi-Decide` (287M, mDeBERTa-v3, CPU torch)
- 프롬프트 설계: store 2라벨 choice(설명 부착) + memory_type 14라벨 choice → G-AS 규칙(store==STORE && type≠context → KEEP) 적용
- JEV verdict는 gold가 아닌 참고용 — 비교 기준은 인간 gold(STORE 31 / NO_STORE 19)
- 참고: JEV G-AS 공인 수치(ASSISTANT_GATE_REPORT.md §3.2): P 0.744 / R 0.935 / F1 0.829, commitment-fp-filter 후 P 0.806 / F1 0.866

| 판정기 | TP | FP | FN | TN | Precision | Recall | F1 | Accuracy |
|---|---|---|---|---|---|---|---|---|
| **GLiNER2.5-multi (CPU, 이번 실측)** | 14 | 10 | 17 | 9 | 0.583 | 0.452 | 0.509 | 0.460 |
| JEV G-AS (보고서 공인) | — | — | — | — | 0.744 | 0.935 | 0.829 | — |

- 지연: store 콜 p50 150ms + type 콜 p50 242ms = **발화당 p50 391ms** (CPU, Ryzen 7600 근처)
- 오류 패턴: FN 17건 중 13건이 store=NO_STORE 오판(진짜 결과물을 버림 — **가장 비싼 오류**), FP 14건 중 9건이 gold NO_STORE를 STORE로 오판
- 한국어 캘리브레이션 의문이 실측으로 확정: 영어 벤치 56.7% 모델이 한국어 발화에서는 gold와 46% 일치

## 판정

1. **GLiNER2.5-multi-Decide 쓰기 게이트 대체 — 기각.** F1 0.509 vs JEV 0.829, 특히 recall 0.452는 진짜 결과물의 55%를 유실. 프롬프트 개선 여지는 있으나 store 이원 판정 자체의 캘리브레이션이 무너져 있어 소폭 개선으로 격차(0.32 F1) 해소는 비현실적.
2. **단일 모델 수렴 — 외부 AI 3종 + 사전 분석 합의대로 종결.** 잔여 미스가 임베딩 품질 문제로 확정(Run P)된 이상, 판정 모델 교체·통합은 recall 문제와 무관.
3. 남는 유효 경로: 임베딩 교체 파일럿(a25m 등, 별도 승인 필요) 또는 Mica 4B류 판정 모델(단 RAM 실측 전제). 둘 다 이번 결론과 무관하게 JEV 유지가 현재 최적.

## 재현

```
gliner-env(스크래치 venv): pip install gliner2 torch transformers peft numpy
python run_p_miss_diagnosis.py   # Run P (jev-mem venv)
python run_q_gliner_gate.py      # Run Q (gliner-env)
```
