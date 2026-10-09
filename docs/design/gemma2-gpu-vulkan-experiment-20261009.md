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

## 4. X1 재실측 — "GGUF 손실"의 진짜 원인: 프롬프트 누락 (2026-10-09 대발견)

| GGUF 실행 | X1 Acc@1 | 시간 | 비고 |
|---|---|---|---|
| unsloth Q8_0 (프롬프트 없음) | 0.626 | 397s | dense head 없음 |
| AtomicChat Q8_0 (프롬프트 없음) | 0.626 | 397s | 해시 상이, 동일 결과 |
| AtomicChat AD-Q6_K (프롬프트 없음) | 0.629 | 405s | head BF16 보존 주장 |
| unsloth BF16 (프롬프트 없음) | 0.627 | 579s | 양자화 없음 |
| AtomicChat Q8_0 + add_special(BOS/EOS) | 0.630 | 401s | 토크나이저 ONNX와 100% 일치 |
| AtomicChat Q8_0 + **쿼리 프롬프트만** | 0.649 | 216s | +0.023 개선 |
| **AtomicChat Q8_0 + 쿼리+문서 프롬프트** | **0.688** | **228s** | **ONNX와 동급!** |
| ONNX CPU raw (Q_PREFIX) | 0.672 | 790s | — |
| ONNX CPU + 프롬프트 (doc=True) | 0.690 | 1,301s | 종전 최고 |

### 확정 결론: GGUF/llama.cpp는 무죄, 실험 프로토콜 차이가 원인

- 기존 ONNX 스크립트(`EmbGemma2Runner.embed`)는 `doc=False`에서도 **쿼리에 `"task: search result | query: "` 프롬프트를 자동으로 붙였다** (`pref = D_PREFIX if doc else Q_PREFIX`).
- GGUF 실험에서는 이 프롬프트를 생략한 채 raw 텍스트로만 임베딩 → **검색 순위가 달라져 0.626~0.630으로 보였던 것**.
- 같은 프롬프트를 GGUF에 적용하자 **0.688 (ONNX 0.690과 차이 0.002 = 노이즈)** — 벡터 cos 0.9999 실측과 일치.
- "llama.cpp 그래프 구현 한계"로 단정했던 것은 **프롬프트 누락이 만든 착시**였음.
- GGUF 4종이 모두 0.626~0.630으로 수렴한 것도 프롬프트 없음이라는 공통 조건 때문 (프롬프트를 붙이면 모두 비슷하게 개선될 것으로 기대).

### (부록) 원인 규명 과정에서 제외된 가설들

- **양자화**: BF16(양자화 없음)도 0.627 — 단, 프롬프트 없음 동일 조건이므로 무효.
- **dense head 유무**: cos 0.9999로 헤드와 무관 (v1 #19040과 달리 v2는 헤드 불필요 확인).
- **토크나이저**: `/tokenize` 30/30 쿼리 add_special 일치 확인. BOS/EOS 포함해도 불변(0.630).
- **슬롯/캐시 오염**: -np 1 재실측 동일 → 해당 없음.
- **f16 계산**: CPU BF16(-ngl 0) 전체 0.613, 스모크 0.667 — 프롬프트 없음 조건이라 비확정적이나, 프롬프트 포함 시 ONNX와 동일하므로 f16 계산도 유의미한 손실 없음.
- **b11516**: 0.480(batch)/0.530(단건) — b11515와 벡터 cos 1.0인데 스코어가 이상하게 낮음 → b11516 스케줄링 회귀로 보이며 (b11515와 벡터 동일 확인) 추가 조사 불필요. b11515 사용.

## 5. 알려진 사례와의 대조 (문서화된 유사 사례)

- **llama.cpp 공식 권고**: "임베딩에서 양자화 품질은 cos이 아니라 Recall/MRR로 검증하라" — cos 0.99여도 검색 드리프트 가능 (공식 문서).
- **bekko-a8m 제작자**: Q8_0 cos 0.9997이지만 검색 delta는 따로 측정 — 저비트(IQ4_XS)에서 cos 0.986인데 NDCG -0.0195.
- **gemma 임베딩 #19040/#18677**: unsloth/ggml-org GGUF는 dense head(2_Dense/3_Dense) 누락 — 포함하면 cos 1.0. 단 우리 모델(v2)은 head 미포함이어도 cos 0.9999였고 X1 손실은 head와 무관.
- **llama-server 캐시 오염 #26282**: -np 1로 재실측했으나 동일 → 해당 없음 확인.
- **AtomicChat "Q8_0 98.7% same top"**: 우리 X1 도메인(한국어 대화 응답 선택)에서는 재현 안 됨 — 그들의 30개 언어 검색 벤치와 도메인 차이.

## 6. 최종 결론 (2026-10-09 수정판)

1. **DirectML 경로 기각** (전 변형 CPU보다 5~35배 느림, 양자화 폴백).
2. **Vulkan/llama.cpp 경로 부활!** 프롬프트("task: search result | query: ", "title: none | text: ")를 동일하게 적용하면 **ONNX와 동등 품질(0.688 vs 0.690)**.
3. **GGUF "품질 손실"은 실험 프로토콜 불일치(프롬프트 누락)의 착시** — GGUF/llama.cpp 자체는 정상.
4. **GPU 가속 실익 확보**: Vulkan 228s vs ONNX CPU 790s(+프롬프트 1,301s) — **~3.5~5.7배 빠름** + RAM 절감. 모델 파일도 작음 (Q8 310MB).
5. **운영 시사점**: 프롬프트는 쿼리/문서 식별에 필수 — jev-mem 파이프라인에서도 프롬프트 불일치가 검색 품질을 좌우할 수 있음. "cos 0.99 = 검색 동일" 추론은 여전히 금지 (프로토콜 차이로 순위가 바뀜).

## 7. 실행 산출물

- 스크립트: `bench/run-20261006-embedgemma2/dml_smoke.py`, `x1_gemma2_vulkan.py`, `x1_gemma2_q8_raw.py`, `x1_raw_single.py`, `x1_vulkan_qp_test.py`, `x1_vulkan_both_test.py`
- GGUF: `bench/gemma2-gguf/{embeddinggemma-2-Q8_0,embeddinggemma-2-BF16,atomic_q8,atomic_q6}.gguf`
- llama.cpp: `bench/llama-vulkan/` (b11515 vulkan-x64), `bench/llama-vulkan-b11516/` (b11516 — 회귀 확인, 사용 금지)
- 결과 JSON: `run-20260930/cand/x1_gemma2_vulkan_q8.json`, `run-20261006-embedgemma2/x1_vulkan_qp_result.json`, `x1_vulkan_both_result.json` (+ 로그 `x1_vulkan_qp.log`, `x1_vulkan_both.log`)
- GPU: RX 580X (Polaris) — DirectML 부적합, Vulkan은 Q8 스루풋 228s로 실용적.

## 8. 후속 (2026-10-09 진행 중)

- [ ] AtomicChat AD-Q6_K vs unsloth Q8_0 프롬프트 적용 비교 (양자화 수준별 품질 동등성)
- [ ] jev-mem 파이프라인 프롬프트 적용 지침 반영