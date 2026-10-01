# 임베딩 모델 교체 — 외부 검토 3건 종합 판정 (2026-09-30)

> 입력: `embedding-model-replacement-brief.md`에 대한 외부 AI 검토 3건
> (a-AI: 종합기술검토서 / b-AI: 종합기술검토서 / c-AI: 소형 로컬 임베딩 모델 교체 검토서)

## 1. 세 검토서의 합의점 (신뢰도 높음 — 그대로 채택)

1. **1차 실험군이 사실상 동일**: KoEn-E5-Tiny / Granite-97M-R2 / Bekko-a8m (+ 대조군 mE5-small)
2. **384D 동일 차원 ≠ 벡터 공간 호환**: 전량 재임베딩 필수, old/new 혼합 절대 금지
3. **모델 파일 크기 ≠ 프로세스 RAM**: MTEB Memory·파일 크기로 판정 금지, 반드시 우리 환경에서 Private Commit 직접 실측
4. **마이그레이션 방식**: 섀도/이중 벡터 테이블 + 백그라운드 재임베딩 + 아토믹 스왑 (3개 AI 모두 동일 제안)
5. **E5 계열 prefix 필수**: `query: `/`passage: ` 누락 시 품질 15~20% 폭락 — 데몬에서 명시 처리
6. **전환 후 재튜닝**: vec 코사인 분포가 바뀌므로 `vec_weight`·게이트 임계값·F1 기준선(0.829) 재수립
7. **행 단위 provenance**: `embedding_model_id`(모델·리비전·pooling·prefix·max_length) 기록 — B·C 공통
8. **리비전 고정**: 특히 Bekko(단일 저자, 2026-07 신생)는 revision hash 고정

## 2. 분기점 (세 AI가 서로 다르게 본 것)

| 쟁점 | a-AI | b-AI | c-AI |
|---|---|---|---|
| Granite R2 | **1순위** (품질 최고 60.3) | 도전자 — 이전 세대 R1이 한국어에서 mE5-small보다 낮았음(0.60 vs 0.67), int8 ONNX 품질 하락 사례 인용 | 1차 실험군 — MIRACL-ko 55.21이 R1(60.70)보다 낮아 한국어 역전 가능성 명시 |
| Bekko a25m/a8m | a8m 3순위 | **a25m 1순위**, a8m 2순위 — 단 신생 모델 리스크 경고 | a8m만 1차군, a25m은 2차 — 한국어 단독 근거 없음 지적 |
| KoEn-E5-Tiny | 2순위 (한·영 최적) | 주목 후보 (experimental 확인 필요) | **RAM+한국어에 가장 직접적인 해법** (0.6875 공개 근거) |
| CPU 속도 | bekko 최속(저자 주장) | ModernBERT가 CPU에서 반드시 유리한 것 아님 — mE5-small 226 vs bekko-a25m 134 docs/s 실측 인용 | — (단건 예산 여유로 판정 변수 아님) |

## 3. 교차 검증으로 확정된 판단 재료

1. **한국어 공개 근거**: KoEn-E5-Tiny 0.6875 > mE5-small 0.6709 ≫ 현재 MiniLM 0.4098. Granite R2는 한국어 벤치에서 R1 대비 역전 사례(MIRACL-ko)가 있어 "확정 근거 없음". Bekko는 근거 자체가 없음.
2. **RAM 잠재력**: "총 파라미터"가 작은 유일한 후보는 KoEn-E5-Tiny(37.5M) — active params만 작은 bekko(총 106M, vocab int8 압축)·granite(fp32 390MB / int8 98MB)와 구조가 다름. a-AI의 granite 커밋 ~320MB 추정은 fp32 파일 크기(390MB)와 모순되어 낙관적.
3. **512-token 우려는 실제로는 개선**: 현재 MiniLM max_seq_length=**128** → KoEn 512 / granite·bekko 8K는 모두 업그레이드. 긴 기억 truncation 이슈는 완화.
4. **latency는 판정 변수 아님**: 현재 p95 453ms, 예산 1s — 세 후보 모두 통과 전망. 단건 호출이므로 throughput보다 p95가 중요 (c-AI와 동일).
5. **fastembed 미등록**: 세 후보 모두 fastembed 0.8.0 내장 목록 외 → 데몬에 ONNX 직접 로드 래퍼 또는 custom model 등록 필요 (a-AI의 35라인 래퍼안 참조). Python 3.14+onnxruntime 스모크 테스트 선행.

## 4. 종합 최종 판정

### 예측 순위 (실험 전 사전 등록 — 실측으로 확정)

| 순위 | 모델 | 근거 | 조건/리스크 |
|---|---|---|---|
| **1순위 (예측)** | **exp-models/dragonkue-KoEn-E5-Tiny** | 목적1(RAM)+목적2(한국어)를 공개 근거로 동시 충족하는 유일 후보. 384D, Apache 2.0, ONNX 제공(150MB/74.9MB optimized) | `query:`/`passage:` prefix 데몬 지원 필요(단일 지점 수정), 512-token, experimental 성격 → 리비전 고정 |
| 2순위 | ibm-granite/granite-embedding-97m-multilingual-r2 | 다국어 품질 최강(60.3), 52개 언어 enhanced에 한국어 포함, 코드 retrieval 학습 포함 | fp32(390MB) 기준 커밋 실측이 500MB 예산 내인지 확인 필수. int8(98MB)은 품질 하락 사례 있어 검증 후. prefix 불필요(대칭형) |
| 3순위 | hotchpotch/bekko-embedding-v1-a8m | RAM/속도 챔피언(active 7.7M, 124MiB, CPU 최속), MIT, 8K context | 한국어 공개 근거 없음 → 로컬 골드 통과가 채택 조건. 단일 저자 신생 모델 |
| 참조 앵커 | dragonkue/multilingual-e5-small-ko-v2 | 한국어 품질 상한 참조(0.6925) | RAM 절감 목적 부적합(449MB) — 측정은 선택 |
| 대조군 | 현재 MiniLM + mE5-small | 기준선 재현 검증용 | — |

### 채택 하드 게이트 (모든 후보 공통, c-AI 프로토콜 + a-AI 한국어 트랩 테스트 통합)

- [ ] 실측 Private Commit ≤ 500MB (워밍 30~60초 후)
- [ ] 한국어 쿼리 임베딩 p95 < 1s (3회 반복)
- [ ] 골드 50 F1 ≥ 0.829 기준선 (vec-only / hybrid 분리 측정 + hard-negative 유형별)
- [ ] a-AI 한국어 트랩 3계층: 의미-vs-어휘 함정(마진 ≥ 0.15) / 한↔영 교차(코사인 ≥ 0.65) / 부정·상태 역전
- [ ] sqlite-vec int8 저장 후 top-10 랭킹 일치율 ≥ 98%
- [ ] 통계 주의(b-AI): 쿼리 50개 차이 0.03 이하는 결정 근거 불가 — paired bootstrap
- [ ] provenance 메타데이터 + 섀도 테이블 아토믹 스왑 마이그레이션 (B·C 합의안)

## 5. 다음 단계

1. 실험 하네스스 구축: 동일 골드 + RAM/지연 실측 + 한국어 트랩 세트 (모델별 `gold_metrics.json` 등 산출물 남김 — c-AI §11)
2. 3모델 측정 → 결과 보고 → 사용자 승인 → 섀도 마이그레이션 → 전환 후 vec_weight/게이트 재튜닝 + F1 기준선 재수립
