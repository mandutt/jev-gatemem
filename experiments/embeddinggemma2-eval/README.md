# EmbeddingGemma 2 평가 기록 (2026-10-07)

> **상태: 탐구 진행 중.** 채택/기각 미확정. 외부 AI 검토 요청용 문서.
> 재실험 금지(do-not-re-run) 아님 — 아래 "남은 탐구 축" 참조.

## 0. 배경

- Google이 2026-10-06 EmbeddingGemma 2 출시 (Gemma 4 기반, Apache 2.0, 740M 멀티모달 / 270M 텍스트 전용, 768d, MRL, mean pooling, 문맥 8192).
- 사용자 요청: jev-mem 임베딩 모델 또는 JEV 대용 가능성 탐색. 텍스트 전용 ONNX q4f16 실험 → q8 비교 → 하이브리드 → JEV 판정 경로 순으로 진행.
- **중요 구분 (사용자 원칙):** 본 프로젝트('jev-mem')와 학술 'Jev-Mem'(arXiv 2609.23986)은 이름만 유사한 별개 프로젝트.
- 실험 원칙: 스탠드얼론 (데몬/LLM 무관, 0콜), 동일 스냅샷 DB, incumbent(bekko-a8m) 동일 하네스 재실측.

## 1. 실행 환경

| 항목 | 값 |
|---|---|
| 벤치 디렉토리 | `%LOCALAPPDATA%/jev-mem/bench/run-20261006-embedgemma2/` (러너+raw) |
| repo 미러 | `experiments/embeddinggemma2-eval/` (본 문서 + raw JSON) |
| 모델 소스 | `onnx-community/embeddinggemma-2-ONNX` (fp32/q8/q4/q4f16 변환 제공) |
| 사용 모델 파일 | `model_q4f16.onnx`(157MB) / `model_quantized.onnx`(q8, 314MB) + tokenizer.json |
| 텍스트 전용 입력 | image/video/audio_features = `(0,512)` 빈 텐서 — 그래프에 멀티모달 입력이 있어 필수 |
| 출력 | `sentence_embedding` [B,768] (빌트인 pooling+project+normalize, norm=1.0 확인) |
| 프롬프트 | query: `task: search result | query: {t}`, doc: `title: none | text: {t}` (공식 config_sentence_transformers.json) |
| 트렁케이션 | 512 토큰 (운영 클램프 패리티) |
| 런타임 | jev-mem venv (fastembed 0.8.1 / onnxruntime 1.30 / rust tokenizers) — ORT 직접 세션 |
| incumbent | bekko-a8m (fastembed 커스텀 등록, 스냅샷 `run-20260930`) |
| 검증 DB | 스냅샷 `experiments/operational-golden/snapshots/mnemosyne_snapshot_20261006.db` (read-only) |

### fastembed 미지원 (중요)

fastembed 0.8.1에는 v2 미등록 (`google/embeddinggemma-300m` v1만 존재). 게다가 v2는:
- 그래프 입력에 `image_features/video_features/audio_features` 포함
- 유용한 출력이 `sentence_embedding`(output[1]) — fastembed는 output[0](`last_hidden_state`)을 3D로 취급

→ `TextEmbedding.add_custom_model`로 로드 시도 = NO_SUCHFILE(경로)/구조 미지원. **운영 채택 시 ORT 직접 러너 필요** (이번 실험의 `embgemma2_runner.py`).

## 2. 실측 결과 요약

### 2.1 RAM / 레이턴시 (fresh process, Win32 PSAPI, warm 10s)

| 지표 | gemma2-q4f16 | gemma2-q8 | bekko-a8m | baseline |
|---|---|---|---|---|
| 파일 크기 | 157MB | 314MB | 124MB | 471MB |
| private commit (warm) | 559MB | **466MB** | 617MB | 948MB |
| working set (warm) | 234MB | **134MB** | 286MB | 613MB |
| 로드 시간 | 4.07s | 1.0s | 1.57s | 1.35s |
| B=1 p95 | 71.3ms | — | **1.5ms** | 4.0ms |
| 추론 후 WS | 240MB | 289MB | — | — |

- **반직관**: 파일 2배(q8)인데 commit/WS 모두 q4f16보다 작음. q4f16은 활성화를 fp16 유지(중간 버퍼 큼), q8은 가중치 int8 + dequant (가중치 메모리 압축). **"파일 크기 ≠ RAM"** 재확인 (S3 교훈과 동일).
- q8은 추론 시 WS 134→289MB 점프 (활성화 버퍼) — 그러나 commit 기준 466MB로 최소.

### 2.2 멀티모달 세션 RAM (q4f16, modal_ram_probe.py)

| 단계 | text-only | +vision+audio (full) | Δ |
|---|---|---|---|
| 텍스트 세션 로드 직후 | 559/234MB | 558/234MB | — |
| **비전+오디오 세션 추가** | — | **844/547MB** | **+286 commit / +313 WS** |
| 텍스트 추론 1회 | 563/240MB | 848/553MB | +285/+313 |

- ORT는 `InferenceSession()` 시점에 가중치 전부 로드 (lazy 없음). **멀티모달 데이터를 실제로 처리하기 전, 세션을 여는 순간 +~290MB 고정 부담.**
- jev-mem은 텍스트 전용이므로 text-only 세션 유지가 RAM 정답.

### 2.3 retrieval 품질 (vec-only, gold-20 / op-90)

gold-20 (S3 레시피, 20쿼리, 스냅샷 400행, seed 20260930):

| 모델 | R@1 | R@5 | MRR |
|---|---|---|---|
| gemma2-q4f16 | 0.65 | 0.85 | 0.739 |
| bekko-a8m | **0.75** | 0.80 | **0.780** |
| baseline | 0.60 | 0.60 | 0.612 |

op-90 (운영 90쿼리, vec-only, 전체 1,030행):

| 모델 | hit@1 | hit@5 | hit@10 | MRR |
|---|---|---|---|---|
| gemma2-q4f16 | 0.429 | 0.738 | 0.821 | 0.575 |
| gemma2-q8 | 0.452 | 0.750 | 0.833 | 0.591 |
| bekko-a8m | **0.500** | 0.786 | 0.869 | **0.627** |

### 2.4 retrieval 품질 (외부 도메인 3종)

| 프로브 | gemma2-q4f16 | bekko-a8m | 비고 |
|---|---|---|---|
| kodialogbench acc@1 (400) | **0.535** | 0.443 | 대화 응답 선택 (X3 레시피) |
| 다국어 acc@1 (40, ja/zh/es/fr/de 10-way) | 0.925 | 0.900 | x2_extended |
| 기계독해 acc@1 (400 QA 10-way) | **0.850** | 0.840 | RC-10way; gemma2 593s vs bekko 15.8s |

### 2.5 하이브리드 (BM25 char-level + vec, op-90, vw 스윕)

S3 방식: 각각 min-max 정규화, `vw*vec + (1-vw)*bm25`. 라이브 vec_weight는 **0.5** (config/env 미설정 → mnemosyne 기본값, beam.py `_normalize_weights` 확인).

전체 84쿼리 MRR:

| vw | gemma2-q8 | gemma2-q4f16 | bekko |
|---|---|---|---|
| 0.3 | 0.536 | 0.535 | 0.516 |
| 0.5 | 0.638 | 0.641 | 0.646 |
| 0.7 | 0.653 | 0.663 | **0.6615→0.663 동률** |
| 1.0 (vec-only) | 0.591 | 0.575 | 0.627 |

저오버랩(의역, overlap<0.3, n=18) MRR:

| vw | gemma2-q8 | gemma2-q4f16 | bekko |
|---|---|---|---|
| 0.5 | 0.313 | 0.301 | 0.289 |
| **0.7** | 0.370 | **0.383** | 0.300 |

- **vec-only에서는 gemma2 열위, 하이브리드(vw≥0.5)에서는 동급~근소 우위, 저오버랩(의역)에서는 gemma2 우위.**
- q8 vs q4f16: 방향이 vw에 따라 뒤집힘(+0.012/−0.012) → 노이즈 수준. **하이브리드에서는 q4f16으로 충분.**

### 2.6 lexicon overlap 분해 (op90_overlap_decomp.py, 0콜)

op-90을 쿼리↔gold 문자 2-gram overlap 기준으로 분해:

| 그룹 | n | bekko hit@1 | q8 hit@1 |
|---|---|---|---|
| 고오버랩 (≥0.3) | 66 | **0.591** | 0.485 |
| 저오버랩 (<0.3) | 18 | 0.167 | **0.333** |

- bekko의 전체 우세는 **고오버랩(자가 유래, 표면 어휘 공유) 66건에서의 압승** 때문. 순수 의미 매칭(저오버랩)에서는 gemma2가 2배 우위.
- X1 교훈 재현: "internal-gold win은 domain-bound evidence".

### 2.7 ★ JEV 판정 경로 실측 (stage74, op-90, 90콜×2 = 180콜)

**가장 결정적인 실측.** Retrieval 단독 지표가 아니라 **실제 파이프라인**(4-lane → RRF → 어휘 게이트 → POOL_BUDGET 60 → JEV choice lift) 전체에서 임베딩만 교체:

| 지표 | bekko (stage54 base) | gemma2-q8 | gemma2-q4f16 |
|---|---|---|---|
| **hit@1 (choice lift 반영)** | **79/90 (87.8%)** | 67/90 (74.4%) | 67/90 (74.4%) |
| hit@3 | **80/90** | 67/90 | 67/90 |
| abstain | **3** | 9 | 10 |
| err | 0 | 0 | 0 |
| pool 내 gold | **83/90** | 71/90 | 71/90 |
| pool gold top1 | 10 | 8 | 8 |

- **bekko만 hit 14건, gemma2 단독 우위 0건.** q8+q4 동시 우위 2건 (CAMOFOX_URL, pi 프록시 목록).
- **gemma2는 pool 진입(retrieval)에서 이미 12건 손실** — 벡터 공간이 달라 gold가 어휘 게이트/RRF 60위 밖으로 밀림.
- **abstain 3→9~10건**: gemma2 pool에서 excerpt 품질이 낮아져 JEV가 "usable evidence 없음" 판정. 이전 정답 쿼리(입력 토큰 지연, TTFT, 660초 타임아웃, 코드 라벨 규칙, 웹 추출 백엔드 등) 다수 abstain.
- q8=q4f16 (67/90 동일) — JEV 경로에서 양자화 차이는 무의미.

**해석 (가설)**: JEV choice는 벡터 유사도가 아니라 **excerpt 내용을 읽고 판단**한다. 따라서 embedding이 gold를 pool 상위에 올리는가가 결정적. gemma2는 의역 쿼리 벡터 품질은 좋아도, 운영 코퍼스에서 gold pool 진입률이 bekko보다 낮아(83→71) 전체 답변 품질이 떨어진다. "retrieval 단독 우위"는 "JEV 파이프라인 우위"로 이어지지 않음.

## 3. 결론 (잠정)

1. **운영(JEV 파이프라인 전체) 기준 gemma2는 bekko에 열위** — hit@1 74.4% vs 87.8%, abstain 3배.
2. **RAM 절감(≈40~150MB)은 실재하나 답변 품질 13.4%p 손실의 대가로는 부적합.**
3. **"EmbeddingGemma 2가 성능 우월"이라는 모델 카드/일반 도메인 지표는 JEV 운영에서 재현되지 않음** — 도메인 한정 증거(X1 반전 사례와 동일 패턴).
4. 채택 여부: **현재로서는 bekko 유지가 유력하나, 아래 "남은 탐구 축"으로 검증 여지 있음.**

## 4. 남은 탐구 축 (do-not-re-run 아님)

1. **문서 임베딩 프롬프트 변형**: 이번 실험은 doc 프롬프트 `title: none | text:`를 고정 적용. EmbeddingGemma 2는 `Retrieval-document` 등 프롬프트 선택이 성능에 민감할 수 있음 (prompt ablation 미수행).
2. **어휘 게이트(lexical gate) 상호작용**: gemma2 pool 손실 12건이 "벡터 공간 변화"가 아니라 "어휘 게이트+RRF 병합 정책" 때문일 가능성 — `vec_rank` exemption이 이미 있으나, gemma2 공간에선 cosine 분포가 달라 RRF 가중치(현행 k=60) 재튜닝 여지. lane 단독 순위 분해(stage50c 방식)로 원인 규명 가능 (0콜).
3. **fp16 (543MB)**: q8(0.9997)와 cosine 차이 0.0001로 기대 미미 — 우선순위 낮음.
4. **JEV choice abstain 라벨 상호작용**: gemma2에서 abstain이 3배 는 것이 "pool excerpt 품질" 탓인지 "abstain 라벨이 gemma2 벡터 공간과 안 맞음"인지 분리 실험 (excerpt만 gemma2, 판정은 bekko pool 등 — 격리 A/B).
5. **multimodal (img/audio) 활용**: jev-mem이 미디어 메모리를 받기 시작하면 재평가 가치. 현재 text-only가 RAM 정답 (세션 로드 시 +~290MB 확인).

## 5. 재현

- 벤치 러너+raw: `experiments/embeddinggemma2-eval/` (아래 파일)
- stage74 JEV 경로 러너: `experiments/embeddinggemma2-eval/stage74_gemma2_embed.py` (실행: 데몬 venv, `EXPLABS_API_KEY` SET, 인자: model_file label)
- 스냅샷 DB: `experiments/operational-golden/snapshots/mnemosyne_snapshot_20261006.db`
- stage54 bekko 기준 raw: `experiments/operational-golden/data/stage54_op90_regress.json`

### 파일 목록

| 파일 | 내용 |
|---|---|
| `embgemma2_runner.py` | ORT 직접 러너 (프롬프트·트렁케이션·빈 멀티모달 입력) |
| `gold_eval.py` / `gold_eval_result.json` | gold-20 vec-only |
| `op90_eval.py` / `op90_result.json` | op-90 vec-only (q4f16, bekko) |
| `q8_bench.py` / `q8_bench_result.json` | q8 op-90 + 드리프트 |
| `hybrid_op90.py` / `hybrid_op90_result.json` | BM25+vec vw 스윕 (84쿼리) |
| `rc_10way.py` / `rc_10way_result.json` | 기계독해 400 QA 10-way |
| `x2_multilingual.py`, `x2_extended.py` / `*_result.json` | 다국어 10·40 |
| `probe_ram_latency.py` | RAM/레이턴시 3모델 |
| `modal_ram_probe.py` | 멀티모달 세션 RAM |
| `op90_overlap_decomp.py` | lexical overlap 분해 |
| `stage74_gemma2_embed.py` + `stage74_gemma2_{q8,q4f16}.json` | JEV 판정 경로 (180콜) |
| `analyze_stage74.py` | 쿼리별 대조 분석 |

## 6. 함정/메모

- **fastembed 0.8.1로는 v2 로드 불가** (구조·경로 모두) — ORT 직접 세션 필수. 운영 채택 시 러너 유지보수 부담.
- ORT 세션은 `protobuf` 재컴파일 없이 q4f16/q8 모두 로드 OK.
- q4f16 추론이 q8보다 commit이 큰 이유는 활성화 fp16 버퍼 — "파일 크기"로 RAM 예측 금지 (S3 교훈 일반화).
- 빈 멀티모달 입력 `(0,512)`는 shape 검증 없이 통과 (0건 배치) — onnxruntime 1.30 확인.
- rc_10way gemma2 593s vs bekko 15.8s — **37배 처리 시간 차이**. 대량 재인덱싱 시 실질 부담 (1,397행 ≈ gemma2 10~15분).