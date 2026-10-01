# Mnemosyne 임베딩 모델 교체 벤치마크 — 진행 보고서 v1 (2026-10-01)

> 목적: 독자 AI가 추가 정보 없이 현재 상황을 파악하고 검토할 수 있도록 작성.
> 상위 문서: `jev-memory-middleware/docs/design/embed-swap-harness-plan.md` (실험 전 사전 등록 v2, 게이트 G1~G6),
> `embedding-model-review-synthesis.md` (외부 AI 3건 종합 판정).
> 이 보고서는 실행 명세(`mnemosyne-embedding-benchmark-execution-spec.md`)의 S1(기준선)/S2(후보) 단계까지의 **실측 결과**만 다룬다.

---

## 1. 배경 (요약)

- 환경: Windows 11, RAM 15.6GB, CPU-only, Python 3.14 전용 venv, fastembed 0.8.0, onnxruntime 1.30.0, sqlite-vec 0.1.9 (int8 양자화 벡터 저장).
- 현재 운영 모델: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384D, 파일 471MB, 프로세스 커밋 ~975MB) — 한국어 분별력 저하(공개 벤치 한국어 평균 0.41)와 RAM 과점이 교체 동기.
- 외부 AI 3건 종합 판정의 예측 순위: 1순위 **dragonkue-KoEn-E5-Tiny**, 2순위 **granite-97m-r2**, 3순위 **bekko-a8m**.
- 실험은 라이브 DB/데몬 무접촉: 운영 DB 스냅샷(working 1,030행 + episodic 113행)을 격리 디렉터리에 복사해 후보마다 독립 프로세스로 재임베딩 수행.
- 사전 등록 게이트: G1 RAM(Private Commit ≤ 500MB) / G2 지연(p95 < 1s) / G3 품질(hybrid F1 delta ≥ -0.01) / G4 한국어 트랩 3계층 / G5 int8 드리프트(≥98%) / G6 마이그레이션 무결성.

## 2. 실험 구현 상태

| 구성요소 | 상태 | 비고 |
|---|---|---|
| S0 preflight/스냅샷/격리 | 완료 | SQLite 스냅샷 → `%LOCALAPPDATA%/jev-mem/bench/run-20260930/data/`, 후보별 `cand/<name>/` 복제 |
| 모델 캐시 스테이징 | 완료 | HF Hub 스냅샷을 로컬 `model-cache/`에 스테이징, `HF_HUB_OFFLINE=1` |
| 커스텀 모델 등록 | 완료 | fastembed `add_custom_model` 경유 (`register_custom.py`), E5 계열 `query: `/`passage:` prefix env 적용 |
| reindex 러너 | 완료 | `run_candidate2.py` — `mem.reindex_vectors()` 직접 호출, 배치 크기 인자화, 결과 JSON 산출 |
| S1 baseline 재인덱스 | 완료 | 아래 §3 |
| S2 후보 재인덱스 | 완료 (koen/bekko 성공, granite 실패) | 아래 §3~4 |
| S3 품질·RAM·지연 측정 (T1~T3 트랩, 하이브리드 recall) | **미착수** | 재인덱스 완료 후보 3종 대상 예정 |

## 3. 실측 결과 (재인덱스 단계)

| 후보 | 재인덱스 결과 | 소요 | 배치 | 비고 |
|---|---|---|---|---|
| baseline (MiniLM-L12-v2) | ✅ 성공 — working 1,030 + episodic 113 전체 | 40.6s | 64 | ~28 docs/s |
| koen-e5-tiny | ✅ 성공 — 전체 | 107.4s | 64 | prefix(query:/passage:) 적용 |
| bekko-a8m | ✅ 성공 — 전체 | 807.6s | 4 | 배치 64에서 OOM → 4로 하향, 13.5분 |
| granite-97m-r2 (정적 quint8 AVX2 원본) | ❌ 무한 hang | 6시간+ | 64 | 아래 §4 |
| granite fp32→동적 int8 변형 | ❌ OOM | 63.8s | 8 | 아래 §4 |

## 4. granite 문제 — 원인 규명 (실측)

세 가지 변형을 모두 실측했고 전부 실패했다. **재시도 없이 탈락 판정 확정(사용자 지시).**

| 변형 | 결과 | 오류 |
|---|---|---|
| ① 정적 quint8 (repo 공식 `model_quint8_avx2.onnx`) | 무한 hang | 재인덱스 프로세스가 모델 로드 후 CPU 시간 0, DB 무변화 상태로 정지. 타임아웃→재시작 루프 반복 (6시간+) |
| ② fp16 캐스트 → `quantize_dynamic` | 그래프 무효 | `DynamicQuantizeLinear`가 fp16 입력을 받으면 ORT에서 INVALID_GRAPH — fp16 위 DQL은 구조적으로 불가 |
| ③ fp32 원본 → `quantize_dynamic(QInt8)` | OOM | 단건 스모크(384D 출력)는 통과하나, 재인덱스 배치에서 attention MatMul(`​/layers.0/attn/MatMul`)이 **76.2GB 버퍼**를 요청해 BFCArena 할당 실패 (63.8초, working 1024/1030 지점) |

분석:
- 스모크 1건은 통과하지만 배치 처리에서 그래프가 비정상적으로 큰 중간 텐서를 요구하는 것으로 보아, ModernBERT 계열 그래프가 이 ORT 빌드(1.30.0, Python 3.14 wheel)에서 배치 차원/attention mask를 잘못 확장하는 것으로 추정.
- 배치 4로도 granite 재시도는 하지 않음(사용자 지시: hang 재현 시 재시도 불필요).
- 결과적으로 외부 3-AI 종합의 2순위 예측(granite)은 **이 환경에서 실행 불가**로 사전 탈락.

## 5. bekko OOM 이슈와 배치 영향

- bekko-a8m(124MiB, active 7.7M)도 배치 64에서 attention 버퍼 9.6GB 요청 OOM → 배치 4로 성공(807.6s).
- **주의**: 배치 크기가 후보마다 다르므로(64 vs 4) 재인덱스 소요 시간의 직접 비교는 무효. 품질 비교에는 영향 없음(동일 corpus 전체 재임베딩). 지연 비교는 S3에서 단건 쿼리로 측정하므로 영향 없음.
- baseline/koen(64)과 bekko(4)의 throughput 차이(28 vs ~1.4 docs/s)는 배치 크기 효과와 모델 효과가 섞여 있음 — 통제된 속도 비교가 필요하면 동일 배치로 재측정 권장.

## 6. 현재 확정 사실 (S2 종료 시점)

1. **완주 후보 3종 확정**: baseline(40.6s@배치64), koen-e5-tiny(107.4s@64), bekko-a8m(807.6s@4). 세 종 모두 격리 스냅샷에 int8 벡터로 재저장 완료.
2. **granite 탈락**: 위 §4의 세 변형 전부 실패, 사전 등록 오류 분류로는 FAIL_RAM/FAIL_HANG 계열. 이 환경에서의 채택 불가.
3. **벡터 공간 비호환 확인**: 후보마다 DB를 별도 복제해 재임베딩하므로 혼합 벡터 0건 (G6 사전 조건 충족).
4. 아직 측정 전: G1 RAM, G2 지연, G3 하이브리드 F1, G4 트랩 3계층, G5 int8 드리프트 — **S3에서 후보 3종 대상 실측 예정**.

## 7. 외부 검토 요청 사항 (이 보고서를 읽고 판정해줄 것)

1. **S3 진행 승인**: 완주 3종(baseline/koen/bekko)으로 품질·RAM·지연 측정을 진행하는 것의 타당성. granite 없이도 비교가 성립하는지.
2. **granite 탈락 처리 적정성**: (a) 탈락 확정 vs (b) PyTorch 직접 경유 등 대안 경로 1회 시도 가치. 환경 제약(CPU-only, RAM 15.6GB, Python 3.14)을 감안했을 때.
3. **bekko 배치 4 OOM 회피 방식의 리스크**: 배치 축소 외에 ORT 세션 옵션(arena 경량화, 시퀀스 길이 클램프 등)으로 해결 가능한지. 배치 크기 차이가 S3 품질 측정에 미치는 영향 평가.
4. **예측 순위 재평가 요청**: granite(예측 2순위) 탈락으로 koen(1순위) vs bekko(3순위) 2파전이 됨. 한국어 공개 근거는 koen(0.6875)만 존재 — 이 상황에서 bekko를 끝까지 비교 대상으로 유지해야 하는지, 아니면 koen 집중 측정이 효율적인지.
5. **S3 측정 설계 검토**: G4 트랩 3계층(의미-vs-어휘/한영교차/부정역전)과 FTS-gap 15개를 하이브리드 recall 실측(격리 데몬 경유)과 어떤 우선순위로 배치할지.

## 8. 참고 — 실행 환경 디테일

- 실험 디렉터리: `%LOCALAPPDATA%/jev-mem/bench/run-20260930/`
  - `data/` — 원본 스냅샷 (working 1,030 + episodic 113)
  - `cand/{baseline,koen,bekko,granite}/` — 후보별 격리 DB 복제본
  - `cand/*_result.json`, `cand/*_err.log` — 러너 산출물 (raw 보존)
  - `register_custom.py` — fastembed 커스텀 등록 + prefix env 매핑
  - `run_candidate2.py` — reindex 러너 (배치 크기 인자)
  - `convert_granite_fp32_dynq.py` — granite ③ 변환 스크립트
- 라이브 영향: 없음 (운영 DB·데몬 무접촉, 후보별 독립 프로세스)
- 모델 리비전: granite snapshot `835ad14087e140460703cf0fae09f97d469d65c2`; koen/bekko는 스테이징 당시 revision (model-cache에 고정)
