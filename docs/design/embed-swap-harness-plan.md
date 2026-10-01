# 임베딩 모델 교체 실험 하네스스 구축 계획 v2 (2026-09-30)

> 상위 문서: `embedding-model-review-synthesis.md` (외부 검토 3건 종합 판정)
> **v2**: 외부 실행 명세서(`mnemosyne-embedding-benchmark-execution-spec.md`, 이하 "실행 명세") 검토 결과를 반영 — 실행 명세를 실행 표준으로 채택하고, 실행 명세에 없는 우리 고유 평가 세트(트랩 3계층·FTS-gap)를 병합.
> 이 계획은 **실험 전 사전 등록(pre-registration)**입니다 — 게이트 기준을 측정 전에 고정해 후관왜곡을 차단합니다.

---

## 0. 범위와 원칙

- **목적**: 후보 3개 + 대조군 2개를 동일 조건으로 측정해 채택 모델 1개 확정
- **실험 경로**: 라이브 core 데몬/DB **완전 무접촉** — 모든 실험은 스크래치 venv + 스냅샷 DB에서
- **원칙**: 모델 파일·런타임·입력 조건이 동일해야 비교가 성립. 산출물은 재사용 가능한 회귀 하네스스로 남김
- 산출 위치: `experiments/embed-swap/` (repo) + 모델 캐시 `%LOCALAPPDATA%/jev-mem/embed-cache/`

## 1. 실험 대상

| ID | 모델 | 역할 | 로드 방식 |
|---|---|---|---|
| baseline | paraphrase-multilingual-MiniLM-L12-v2 (현재) | 기준선 재현 | fastembed (기존 경로) |
| koen | exp-models/dragonkue-KoEn-E5-Tiny(-ONNX) | 예측 1순위 | ONNX 직접 래퍼 + `query:`/`passage:` prefix |
| granite | ibm-granite/granite-embedding-97m-multilingual-r2 | 2순위 | ONNX (fp32 390MB 우선, int8 98MB는 별도 변형) |
| bekko | hotchpotch/bekko-embedding-v1-a8m | 3순위 | ONNX (기본: vocab row-wise int8) |
| anchor | dragonkue/multilingual-e5-small-ko-v2 | 한국어 품질 앵커 (선택, 시간 여유 시) | ONNX 직접 래퍼 + prefix |

- 리비전 해시 다운로드 시점에 고정해 `model_metadata.json`에 기록
- 공통 임베더 인터페이스: `embed(texts, role) -> np.ndarray (L2 정규화)` — role은 query/passage (E5만 사용, 대칭형은 무시)

## 2. 하네스스 구성 (4개 모듈)

### 2.1 `embedder.py` — 통합 로더
- ONNX Runtime 직접 로드 래퍼 (fastembed 목록 외 모델 대응, a-AI 35라인 래퍼 참조)
- 모델별 프로필: tokenizer 경로, pooling(mean/CLS), max_length(128/512/8192→실험은 512 공통), prefix 규칙
- **Python 3.14 + onnxruntime 호환 스모크**가 최초 관문 (실패 시 여기서 중단·보고)

### 2.2 `datasets.py` — 평가 세트
- **골드 50**: 기존 게이트 회귀용 골드 재사용 (query→정답 기억 매핑)
- **한국어 트랩 3계층** (a-AI 프로토콜, 각 10쌍 = 30):
  - T1 의미-vs-어휘 함정: 어휘 일치 오답이 정답보다 높으면 FAIL (마진 ≥ 0.15)
  - T2 한↔영 교차: 한국어 쿼리→영어 기억 (코사인 ≥ 0.65)
  - T3 부정·상태 역전: 완료/장애 상태 뒤집힌 문서 distractor
- **hard-negative 유형 그룹**: 같은 키워드(예: 9router, OCV) 다른 의미 기억 — 골드 50 내에 유형 태그로 부착
- **FTS-gap 서브셋** (b-AI): FTS가 놓치고 vec만 맞힐 쿼리 15개 별도 태그 — vec 레인 차별화의 핵심 지표

### 2.3 `measure_ram_latency.py` — 실측
- 각 모델을 **단독 프로세스**로 로드 (라이브 데몬 환경 모사: 동일 venv, 동일 ORT 설정)
- 측정: 기동 후 콜드 Private Commit/WS → 워밍 60초 후 steady-state → 쿼리 50개×5회 p50/p95/p99 (한국어/혼합/긴 입력 버킷 분리)
- **ORT 세션 옵션 고정**: intra_op=2 스레드, max_length=512 — RAM이 옵션에 좌우되므로 변형 통제
- 판정: Private Commit ≤ 500MB, p95 < 1s

### 2.4 `eval_quality.py` — 회수 품질
- 각 모델로 골드+트랩 전체 재임베딩 (스냅샷 DB 텍스트 대상, 라이브 무접촉)
- 측정 (c-AI 프로토콜):
  1. vec-only: Recall@1/5/10, MRR, nDCG@10
  2. hybrid 재현 (FTS+vec+imp+graph 동일 레인 가중치): 동일 지표 + 최종 F1 (0.829 기준선 대비)
  3. int8 드리프트: fp32 top-10 vs sqlite-vec int8 top-10 일치율 (≥ 98% 게이트)
- 통계: paired bootstrap 95% CI — **골드 50 차이 0.03 이하는 "동등"으로 판정** (b-AI)

## 3. 채택 하드 게이트 (사전 등록, 모든 항목 통과 시에만 채택 후보)

| # | 게이트 | 기준 |
|---|---|---|
| G1 | RAM | 워밍 후 Private Commit ≤ 500MB |
| G2 | 지연 | 한국어 쿼리 p95 < 1s |
| G3 | 골드 F1 | hybrid F1 ≥ 0.829 (기준선) |
| G4 | 한국어 트랩 | T1 마진 ≥ 0.15, T2 ≥ 0.65, T3 판별 — 3계층 전부 |
| G5 | int8 드리프트 | top-10 일치율 ≥ 98% |
| G6 | provenance | 모델/리비전/pooling/prefix/max_length 메타 기록 가능 |

동점 처리 규칙: G1~G6 전부 통과한 후보 중 **한국어 트랩(T1~T3) 점수 → 골드 F1 → 커밋 크기** 순으로 우선.

## 8. 실행 단계 (v2 — 명세 §29 순서 채택, 승인점 유지)

```text
S0 preflight+snapshot+staging (명세 §3/§4/§7)  → 스모크 겸, 로드 불가 모델 조기 탈락
S1 baseline 재측정 (명세 §10)                  → 중간 보고 (기준선 재현 확인)
S2 candidate 4종 (명세 §29 고정 순서, 독립 프로세스) → 최종 비교표 보고
S3 사용자 승인                                  → 승인 전 DB·데몬 변경 없음
S4 마이그레이션 (별도 계획서): 섀도 테이블 + 백그라운드 재임베딩 + 아토믹 스왑
   + vec_weight/게이트 재튜닝 + F1 기준선 재수립
```

## 7. 실행 명세 반영 사항 (v2 핵심 변경)

실행 명세서를 검토한 결과 **실행 표준으로 채택**합니다. 우리 계획 대비 우수하거나 우리가 누락했던 항목:

### 7.1 채택 (실행 명세 → 우리 하네스스)

| 항목 | 내용 | v1 대비 개선 |
|---|---|---|
| **실제 recall 경로 평가** | 후보마다 격리 DB로 데몬을 띄워 실제 Mnemosyne recall API(hybrid 4레인) 통과 | v1의 "하이브리드 재현"은 모사였음 — 실측이 원칙 |
| **SQLite Online Backup 스냅샷** | 파일 복사 금지, `Connection.backup()` 사용 | WAL 상태 파일 복사 리스크 제거 |
| **후보별 독립 프로세스** | 한 프로세스에서 연속 로드 금지 (allocator/ORT 캐시 잔존 방지) | RAM 실측 오염 방지 — v1 누락 |
| **런타임 고정** | fastembed 0.8.0 등 실행 중 버전 변경 금지 | 재현성 확보 |
| **query cache 무력화 + background mutation 금지** | auto-sleep/consolidation/reindex 비활성 | v1 누락 — 결과 오염원 |
| **`mnemosyne reindex` 우선** | 설치 버전에 있으면 공식 경로, 없으면 direct-vector fallback(`remember()` 재호출 금지 — timestamp/provenance 보존) | v1이 자체 재임베딩 스크립트 가정 — 공식 경로 우선이 안전 |
| **artifact/리비전 SHA256 고정** | moving revision 금지 | v1도 리비전 고정 언급했으나 SHA256까지 확장 |
| **e5-small-ko-v2 ONNX export 검증 게이트** | PyTorch vs ONNX 코사인 ≥ 0.999 (probe 100개), 미달 시 `EXPORT_MISMATCH` 중단 | v1이 ONNX 제공 여부만 확인 — 실제로는 미제공이라 export 필요 |
| ** Granite primary artifact = quint8 AVX2 ONNX** | x86 CPU용. fp32는 QC/reference run | v1은 fp32 우선이었음 — 명세가 맞음 (production artifact 기준) |
| **에러 분류 체계** | PASS/CONDITIONAL/FAIL_LOAD/…FAIL_RAM 12종 — 원인 분리 보고 | v1은 통과/탈락 2분 |
| **policy yaml 분리** | 판정 기준을 결과 JSON에 스냅샷으로 저장, 사용자 변경 가능 | 사전 등록 원칙과 일치하며 더 견고 |
| **Resume/marker 파일** | stage별 `.ok` 마커, 실패 후 해당 candidate 재개 | 장시간 실험 필수 |
| **per-query.jsonl 원본 보존** | retrieved_ids·rank·language 등 쿼리 단위 원본 | 회귀 하네스스 재사용성 |

### 7.2 실행 명세에 없는 우리 고유 항목 (병합 유지)

1. **한국어 트랩 3계층 (T1 의미-vs-어휘 / T2 한↔영 교차 / T3 부정·상태 역전)** — 골드 50 외 추가 30쌍. 실행 명세는 하드네거티브 메타만 허용하는데, 트랩은 판별력 자체를 재는 독립 게이트(G4)로 유지
2. **FTS-gap 서브셋 15개** — FTS가 놓치고 vec만 맞히는 쿼리 별도 분리 보고 (vec 레인 존재 이유의 직접 검증)
3. **동점 처리 규칙** — 트랩 점수 → 골드 F1 → 커밋 크기 순

### 7.3 실행 명세 대비 수정·보완할 점 (우리 환경 기준)

1. **실행 명세의 환경 가정 오류 가능성**: 문서는 upstream Mnemosyne(main 브랜치) 기준 env var(`MNEMOSYNE_EMBEDDING_QUERY_PREFIX` 등)·`mnemosyne reindex`를 가정 — 로컬 설치(3.15.1)와 불일치 가능. → **preflight에서 설치된 config.py 실제 introspect로 해결** (명세 §3 자체가 이 방식을 요구하므로 일관됨. 메모리 규칙 "docs는 main 기준, 로컬 대조 필수"와 동일)
2. **우리 core 데몬 구조와의 정합**: 실행 명세는 "Mnemosyne 데몬"을 가정하나 실제 운영은 `jev-mem-core`(전용 venv, 포트 47821) 경유. → 벤치마크는 **격리 디렉터리의 순수 Mnemosyne 데몬**으로 수행 (core 데몬 무접촉, 승인 전환 시 S4에서 core 쪽 적용). 이 구분을 명시하지 않으면 core 데몬이 실험 오염될 위험
3. **게이트 통합**: 실행 명세 policy(f1_delta -0.01 non-inferiority 등)와 우리 G1~G6를 통합 — G3를 "F1 ≥ 0.829"에서 **"F1 delta ≥ -0.01 (non-inferiority) + preferred ≥ +0.02"**로 정교화 (baseline을 같은 하네스스로 재측정하는 원칙과 정합)
4. **RAM 500MB 기준 유지**: 명세와 동일. 단 "커밋 975MB의 상당 부분이 런타임/아레나"라는 점에서, baseline도 동일 조건으로 재측정해 **감소율(ram_reduction_pct)**을 주 지표로 삼음 (명세와 일치)

### 7.4 최종 게이트 (v2 — G1~G6 갱신)

| # | 게이트 | 기준 (출처) |
|---|---|---|
| G1 | RAM | 워밍 후 Private Commit ≤ 500MB (명세 policy) |
| G2 | 지연 | embedding p95 < 1.0s / recall p95 ≤ 1.5s target, ≥ 2.0s hard fail (명세) |
| G3 | 품질 | hybrid F1 delta ≥ -0.01 non-inferiority; +0.02 이상이면 preferred (명세 policy, baseline 동일 하네스스 재측정 대비) |
| G4 | 한국어 트랩 | T1 마진 ≥ 0.15 / T2 코사인 ≥ 0.65 / T3 판별 (우리 고유, a-AI 프로토콜) |
| G5 | int8 QC | fp32 vs int8 top-10 overlap ≥ 98% + rank displacement 기록 (명세 §19 확장) |
| G6 | 마이그레이션 무결성 | mixed vector rows = 0, provenance 불일치 = 0, NaN/Inf = 0 (명세 §20) |

동점 처리: G1~G6 전부 통과 후보 중 **T1~T3 → 골드 F1 → 커밋 크기** 순.

### 7.5 구현 우선순위 (명세 §32 채택)

- **P0**: preflight / snapshot / 격리 / custom registration / baseline / reindex / 실측 recall / RAM / latency / quality / 최종 보고
- **P1**: concurrency 1-2-4-8 / paired bootstrap(10,000 resamples, seed 20260930) / int8-vs-FP32 QC / 토큰 길이 버킷
- **P2**: OpenVINO 비교, a25m 확장
- 우리 고유 트랩·FTS-gap 평가는 **P0.5** (P1 품질 보고에 포함하되 골드 50 다음 우선순위)

## 5. 산출물

```
experiments/embed-swap/
  embedder.py, datasets.py, measure_ram_latency.py, eval_quality.py
  results/
    model_metadata.json        # 리비전·pooling·prefix (모델별)
    ram_latency_profile.csv    # S1 산출
    gold_metrics.json          # S2 산출 (vec-only/hybrid 분리)
    trap_results.json          # T1~T3
    int8_drift.json            # G5
    comparison_report.md       # 최종 비교표 + 채택 권고
```

## 6. 리스크와 대응

| 리스크 | 대응 |
|---|---|
| Python 3.14 + onnxruntime 호환 실패 | S0에서 조기 발각 — 실패 시 버전 대안 보고 (무리한 우회 금지) |
| granite fp32 커밋 500MB 초과 예상 | int8(AVX2) 변형을 2차 측정으로 준비, 단 G5로 품질 검증 |
| 골드 50의 통계력 부족 | paired bootstrap CI 병기, 0.03 이하는 동등 판정 — 애매하면 골드 확장(추가 50) 제안 |
| 재임베딩 시간 과다 | batch=32, throughput 실측 후 예상시간 보고 — 라이브 영향 없음 (스냅샷) |
| E5 prefix 누락 버그 | embedder 인터페이스가 role을 강제 — 대칭형 모델은 role 무시, 단위 테스트로 검증 |

## 7. 명시적 비범위 (Non-goals)

- 라이브 DB/데몬 변경 (S4 승인 전까지)
- KURE-v2 등 multi-vector 구조, API 임베딩, 차원 변경(320D 등)
- vec 레인 제거(FTS-only) 대안 — 종합 판정에서 보류 확정된 사안
