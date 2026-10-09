# EmbeddingGemma 2 GPU/Vulkan 실측 + GGUF 품질 손실 규명 보고서 (2026-10-09)

> 상위: `docs/design/granite-rerun-report-20261009.md` (같은 세션, granite 재실측 + X1 전체 비교)
> 이 보고서는 **gemma2의 GPU 경로(DirectML/Vulkan) 탐구**와 **GGUF 검색 품질 손실의 원인 규명**을 다룬다.

---

## 1. 배경

- 2026-10-09 세션에서 gemma2-q8이 X1 외부 데이터셋에서 1위(0.690, ONNX CPU)로 확인됨.
- 그러나 속도(1,301s)가 걸려 **GPU 가속** 검토 시작 — 하드웨어: AMD RX 580X 8GB (Vulkan 1.3), R5 7600.
- 사용자 확인 사항: GPU는 있으면 활용. DirectML 대신 Vulkan 같은 양자화 친화 경로 제안됨.

## 2. DirectML 경로 — 실측 결과 (모두 ONNX CPU보다 느림 → 기각)

| 변형 | DML B=1 | DML B=4 | CPU B=1 (기준) |
|---|---|---|---|
| q8 (314MB) | 365.6ms | 532.7ms | 71.3ms |
| q4f16 (157MB) | 283.3ms | 442.2ms | 15.5ms |
| fp32 (1,084MB) | 229.6ms | 254.1ms | 6.6ms |

- **양자화가 아니라 그래프 자체 문제**: fp32마저 229ms로 CPU(6.6ms)보다 34.8배 느림 (q8 5.1배, q4f16 18.3배).
- 원인: gemma2 ONNX의 멀티모달 입력(image/video/audio features) 그래프 + RX 580(Polaris)의 빈약한 DML 지원 + CPU 폴백·전송 오버헤드.
- int8 양자화 노드(MatMulInteger 등)는 DML에서 CPU 폴백된다는 문서화된 제한도 확인 (무시 불가).

## 3. Vulkan/llama.cpp 경로 — 구축

- llama.cpp b11515 (Vulkan 빌드) + unsloth/ggml-org/AtomicChat GGUF 4종.
- `llama-server --embeddings`로 `/v1/embeddings` 서빙. 벡터 768d L2-normalized 확인.
- **Q8_0 GGUF 단건 벡터 cos vs ONNX = 0.9999** — 단순 문장 비교는 동일.

## 4. X1 재실측 — GGUF 품질 손실 확정

| GGUF | X1 Acc@1 | 시간 | 비고 |
|---|---|---|---|
| unsloth Q8_0 | 0.626 | 397s | dense head 없음 |
| AtomicChat Q8_0 | 0.626 | 397s | 해시 상이, 동일 결과 |
| **AtomicChat AD-Q6_K** | **0.629** | 405s | head BF16 보존 주장 |
| unsloth BF16 | 0.627 | 579s | 양자화 없음 |
| ONNX CPU raw (=기준) | **0.672** | 790s | — |
| ONNX CPU +프롬프트 | **0.690** | 1,301s | 최고 |

- **4개 파일 전부 0.626~0.629로 수렴** — 파일/양자화/head와 무관하게 **llama.cpp gemma-embedding2 그래프 자체가 ONNX 대비 -0.042~-0.046 손실**.
- BF16(양자화 없음)도 동일 → **양자화 손실이 아니라 GGUF 변환/그래프 구현의 한계**.
- 각 서브코퍼스 일관 패턴 (Vulkan-Q8 vs ONNX-raw): dailydialog 0.673~0.680 vs 0.737, empathetic 0.697~0.700 vs 0.730, personachat 0.540~0.543 vs 0.570, socialdial 0.587~0.603 vs 0.650 — 4개 전부 ONNX가 +0.030~0.063 우위.
- 원인 미규명 (추정: 토크나이저 차이 또는 그래프 구현 미세 차이가 코퍼스 전체에서 누적).

## 5. 알려진 사례와의 대조 (문서화된 유사 사례)

- **llama.cpp 공식 권고**: "임베딩에서 양자화 품질은 cos이 아니라 Recall/MRR로 검증하라" — cos 0.99여도 검색 드리프트 가능 (공식 문서).
- **bekko-a8m 제작자**: Q8_0 cos 0.9997이지만 검색 delta는 따로 측정 — 저비트(IQ4_XS)에서 cos 0.986인데 NDCG -0.0195.
- **gemma 임베딩 #19040/#18677**: unsloth/ggml-org GGUF는 dense head(2_Dense/3_Dense) 누락 — 포함하면 cos 1.0. 단 우리 모델(v2)은 head 미포함이어도 cos 0.9999였고 X1 손실은 head와 무관.
- **llama-server 캐시 오염 #26282**: -np 1로 재실측했으나 동일 → 해당 없음 확인.
- **AtomicChat "Q8_0 98.7% same top"**: 우리 X1 도메인(한국어 대화 응답 선택)에서는 재현 안 됨 — 그들의 30개 언어 검색 벤치와 도메인 차이.

## 6. 결론

1. **DirectML 경로 기각** (전 변형 CPU보다 5~35배 느림, 양자화 폴백).
2. **Vulkan/llama.cpp 경로 기각** (어떤 GGUF도 ONNX-raw 대비 -0.043~-0.046 검색 손실).
3. **GPU 가속(양자화 포함) 시도는 이 하드웨어(RX 580)와 gemma2 조합에서 전부 실익 없음.**
4. **최적 경로는 종전대로 ONNX CPU q8 + 프롬프트(0.690)** 유지.
5. "cos 0.99 = 검색 동일"이라는 추론의 위험성이 이번에도 재확인 — 항상 검색 메트릭(X1)으로 최종 검증할 것.

## 7. 실행 산출물

- 스크립트: `bench/run-20261006-embedgemma2/dml_smoke.py`, `x1_gemma2_vulkan.py`, `x1_gemma2_q8_raw.py`, `x1_raw_single.py`
- GGUF: `bench/gemma2-gguf/{embeddinggemma-2-Q8_0,embeddinggemma-2-BF16,atomic_q8,atomic_q6}.gguf`
- llama.cpp: `bench/llama-vulkan/` (b11515 vulkan-x64)
- 결과 JSON: `run-20260930/cand/x1_gemma2_vulkan_q8.json`, `x1_gemma2_q8_raw.json`, `x1_bf16_vulkan.log`, `x1_raw_single.log`
- GPU: RX 580X (Polaris) — 이 카드의 DML/Vulkan 특성상 대형 멀티모달 그래프 가속엔 부적합 확인.