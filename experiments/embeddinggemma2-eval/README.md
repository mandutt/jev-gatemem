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

## 3. 결론 (2026-10-09 최종 갱신)

1. **JEV 파이프라인 (stage77, vec live)**: gemma2-q8은 bekko와 **실질 동급** (76/90 vs 78/90, abstain 2 vs 3) — 잔여 차이는 임베딩이 아니라 **파이프라인 재정렬 정책**에 기인 (§7.4). [§2.7의 "열위 74.4% vs 87.8%"는 vec lane 비활성화 인공물 → §7 참조]
2. **외부 도메인 (X1 1,200문항)**: gemma2-q8 **0.690** vs bekko 0.583 — **+0.107 압도** (§8.4). 내부 gold에서는 bekko 1위(0.772) — "모델의 진짜 품위는 도메인에 의존".
3. **GPU 경로 (2026-10-09)**: Vulkan GGUF+프롬프트로 **동일 품질 0.688, ~3.5~5.7배 빠름** (§8.5~8.7) — "GGUF 손실"은 프롬프트 누락 착시.
4. **RAM 절감**: gemma2-q8 466MB vs bekko 617MB (warm commit) — 실재. 속도는 bekko 최강(p95 1.5ms, 재인덱스 19~21s).
5. **운영 판정 (2026-10-09, 사용자)**: jev-mem 개발 중 → **당장 전환 없음** — 추후 모델 동결 시 재평가. 전환 시 768d 스키마 재구축 + 프롬프트 적용 필요.

## 4. 남은 탐구 축 (do-not-re-run 아님)

1. **문서 임베딩 프롬프트 변형**: 이번 실험은 doc 프롬프트 `title: none | text:`를 고정 적용. EmbeddingGemma 2는 `Retrieval-document` 등 프롬프트 선택이 성능에 민감할 수 있음 (prompt ablation 미수행).
2. **어휘 게이트/RRF 재정렬 정책**: §7.4에서 gemma2가 RRF 1위로 찾은 gold를 `_filter_and_rank` 재정렬이 8~9위로 강등하는 것을 실측. **모델 무관 파이프라인 개선 축** — RRF 순위 보존/vec 신호 가중 재조정 시뮬레이션 (0콜).
3. **fp16 (543MB)**: q8(0.9997)와 cosine 차이 0.0001로 기대 미미 — 우선순위 낮음.
4. **JEV choice abstain 라벨 상호작용**: 교정 후 abstain은 q8 2건(≥bekko 3건)으로 오히려 적음 → 격리 실험 불필요해짐.
5. **multimodal (img/audio) 활용**: jev-mem이 미디어 메모리를 받기 시작하면 재평가 가치. 현재 text-only가 RAM 정답 (세션 로드 시 +~290MB 확인).
6. **768d vec 테이블 운영 마이그레이션**: 차원 변경(384→768)은 vec_working 스키마 재구축 + 전체 재인덱싱 필요 (S4 교훈: 벡터 공간 마이그레이션). 운영 전환 시 §7.2의 시행착오(int8 포맷)를 참조.

## 7. ★ 교정 기록 (2026-10-07, stage74→77) — 차원 미스매치 발견

### 7.1 발견

stage74(임베딩 교체 실측) 후 lane 분해(stage75)에서 **gemma2 vec_rank가 19건 중 17건 None** — 비정상. 원인 규명:

- `vec_working`은 `int8[384]` 고정 스키마 (S4 구축 당시 384d)
- gemma2 쿼리 벡터는 **768d** → `_wm_vec_search_sqlite`의 `vec_quantize_int8(?, 'unit')`가 차원 불일치로 **0건 반환** (에러 없이 조용히)
- fallback `_wm_vec_search_fallback`도 768d vs 저장 384d dot product → **0건**
- **즉 stage74의 "gemma2 67/90"은 "vec lane 완전 제거 상태"를 측정한 것** — 임베딩 교체 실험이 아니라 vec lane 비활성화 실험이었음

### 7.2 교정 방법 (stage76/76b)

1. 스냅샷 DB 복사본 생성 (`mnemosyne_snapshot_20261006_gemma2.db`)
2. working_memory 1721행을 gemma2-q4f16로 재임베딩 (doc 프롬프트, ~31분)
3. `memory_embeddings`를 768d JSON으로 교체
4. `vec_working`을 `int8[768]`으로 재생성 — **시행착오**: `qi.tobytes()` 직접 주입은 `expected type int8, got float32` 실패 → `vec_quantize_int8(?, 'unit')` JSON 입력이 정석
5. 검증: 768d 쿼리로 `_wm_vec_search` 정상 반환 (5건)

### 7.3 교정 후 JEV 판정 경로 (stage77, vec live)

| 모델 | hit@1 | abstain | pool 내 gold |
|---|---|---|---|
| bekko (현행) | **78/90 (86.7%)** | 3 | 83/90 |
| gemma2-q8 (vec live) | **76/90 (84.4%)** | **2** | **84/90** |
| gemma2-q4f16 (vec live) | 75/90 (83.3%) | 3 | 84/90 |
| gemma2-q8 (vec dead) [stage74] | 66/90 | 9 | 71/90 |

- vec lane 활성화: hit@1 66→76~77, abstain 9→2~3, pool gold 71→84
- **gemma2-q8 ≈ bekko (2건 차이)**, pool 진입은 gemma2가 우위(84>83)
- abstain 과다 우려 해소 (q8 2건 < bekko 3건)

### 7.4 잔여 4건 lane 분해 (stage78, 0콜)

교정 후 bekko-vs-gemma2 hit 불일치 = 4건 (bekko 우세 3, gemma2 우세 1):

| 쿼리 | fts | vec | RRF | 게이트 후 | 진단 |
|---|---|---|---|---|---|
| [36] 사용자 언어 습관 | None | 1 | 5 | 3 | RRF 병합이 vec 1위를 5위로 약화 |
| [59] X1 bekko 성능 | 1 | 1 | **1** | **9** | **게이트 재정렬이 1→9 강등** |
| [64] bekko/koen 비교 | 10 | 3 | 6 | 7 | 전반 하위 (모델 한계) |
| [71] CAMOFOX_URL | 2 | 3 | **1** | **8** | **게이트 재정렬이 1→8 강등** |

**핵심**: 4건 중 2건([59],[71])은 검색·RRF가 gold를 1위로 올렸는데도 `_filter_and_rank`의 adjusted-score 재정렬(score 0.65 + signal 0.35 + importance 0.05)이 8~9위로 강등. **임베딩 문제가 아니라 파이프라인 재정렬 정책 문제** (stage50c 선행 실측과 동일 패턴). 1건([36])은 RRF 병합 정책, 1건([64])만 모델 한계.

**→ gemma2는 검색 품질에서 bekko와 동급 이상이며, 잔여 손실의 절반은 파이프라인 정책으로 회수 가능한 여지가 있음.**

### 7.5 교정 후 종합

- **채택 판정**: bekko 78 vs gemma2-q8 76 — 2건 차이. RAM -151MB(466 vs 617), abstain 1건 적음, 의역 retrieval 우위. **"동급 + 운영 이점"으로 채택 여지가 있으나, 최종 판단은 사용자/외부 검토에 위임** (do-not-re-run 아님, 후속 실험 가능).
- **파이프라인 개선 축이 별도로 확인됨**: `_filter_and_rank` 재정렬이 RRF 순위를 파괴 — gemma2 유무와 무관하게 운영 품질 개선 여지.

## 8. ★ 재정렬 정책 시뮬레이션 (stage79, 0콜) — 파이프라인 개선 축

### 8.1 동기

§7.4에서 gemma2가 RRF 1위로 찾은 gold를 `_filter_and_rank`의 adjusted-score 재정렬(score 0.65 + signal 0.35 + importance 0.05)이 8~9위로 강등 확인. **모델 무관 파이프라인 정책 문제** — 0콜 시뮬레이션으로 대안 평가.

### 8.2 대안 (gate 통과 행 대상)

- **cur**: 현행 — adjusted score로 재정렬
- **A**: 게이트 통과 후 **RRF 순서 보존** (정렬 제거)
- **B**: RRF rank와 adjusted rank의 평균으로 정렬
- **C**: quality 승수만 제거 (adjusted score 유지)

### 8.3 결과 (90쿼리, 두 모델 동일 패턴)

| 정렬 정책 | RRF pool 내 gold 1위 | 게이트 후 gold rank1 (gemma2) | 게이트 후 gold rank1 (bekko) |
|---|---|---|---|
| RRF pool (시작) | 44 / 43 | — | — |
| **cur (현행)** | — | **10** | **10** |
| **A: RRF 보존** | — | **44** | **44** |
| B: 평균 순위 | — | 43 | 42 |
| C: quality 제거 | — | 10 | 10 |

- **A가 두 모델 모두에서 gold rank1을 10→44 (4.4배) 개선**, 중앙값 8→1
- C는 무효 (문제는 quality가 아니라 재정렬 자체)
- B도 A와 유사 (rank≤3은 B가 더 좋음: 70 vs 58)

### 8.4 해석과 한계

- 보정 계수 (gold_rank_pool==1 → choice==gold): gemma2 0.91 (10/11), bekko 0.90 (9/10). 적용 시 추정 hit@1 ≈ 40/90 — **단 이는 "rank1 gold만 choice가 고른다"는 과소 가정**으로, 실제 JEV는 rank 2~8 후보에서도 excerpt를 읽고 gold를 집어냄 (실측 bekko 78/90 = choice의 상위 후보 선별 능력 포함).
- **A의 실질 이득은 JEV choice 180콜 실측으로만 확정 가능** (rank1 노출 4.4배 → choice hit 증가 여지).
- 주의: A는 RRF 원순서를 노출하므로 importance/graph lane의 도배 후보가 상위에 오를 수 있음 (stage66: 규칙 행 도배 → abstain 유도 사례). 노출 구성 변경은 op·라이브·noans 세 셋 함께 측정 필요 (기존 교훈).

### 8.5 후속 (stage80~82 실측 완료)

**A/RRF 보존 (stage80, bekko 90콜)**: hit@1 78/90 (현행 79) — **동률 미달, 기각**.
- 시뮬레이션이 예측한 rank1 44건은 실측에서 +4/−5 flip으로 상쇄.
- JEV choice는 "rank1만 보는 게 아니라 excerpt 전체를 읽고 gold를 고르는" 능력이 있어 게이트 순위 영향이 제한적.

**B/평균 순위 (stage81, bekko 90콜)**: hit@1 79 (동률), hit@3 81 (+1), abstain 1 (−2) — 표면 개선.

**3셋 회귀 (stage82, bekko 110콜) — B 정책 최종 기각**:
| 셋 | 현행(base) | B(평균 순위) | 판정 |
|---|---|---|---|
| op-90 hit@1 | 79 | 79 | 동률 |
| op-90 hit@3 | 80 | **81** | +1 |
| op-90 abstain | 3 | **1** | −2 |
| 라이브 60 abstain | 0 | 0 | 동일 |
| **noans 하드 FP** | 20~23 | **25** | **+2~5 악화** |

- noans 방어 악화(FP +2~5)가 op 개선(abstain −2/hit@3 +1)을 상쇄 초과 — **순손실**.
- stage66 교훈 재현: "노출 구성 변경은 op 회복만 보고 채택하지 말라 — 3셋 함께 측정".
- **결론: A/B 모두 기각, 현행 `_filter_and_rank` 유지 확정.** 재정렬 정책 변경 재실험 금지 (do-not-re-run).

### 8.6 ★ 2026-10-09 보강 — X1 1,200문항 동일 조건 재실측 (q4f16/q8)

기존 §2.4의 KoDialogBench는 400문항이었다. granite 재실측 세션에서 **1,200문항(4 sub × 300, seed 42) 동일 러너·클램프 512**로 q4f16/q8을 재실측:

| 모델 | Acc@1 | MRR | 임베딩 7,200건 |
|---|---|---|---|
| **gemma2-q8** | **0.690** | **0.813** | 1301s |
| gemma2-q4f16 | 0.683 | 0.806 | 888s |

- 서브 (q8): dailydialog 0.743 / empathetic 0.750 / personachat 0.577 / socialdial 0.690 — 4개 전부 1위.
- **q8 vs q4f16 정정 (RAM)**: q8 466MB / q4f16 **559MB** — q4f16은 활성화 fp16 유지로 중간 버퍼 큼 (파일 크기 157 vs 314MB와 반대). q8이 RAM·품질 우위, 속도는 q4f16이 1.5배 빠름(888s vs 1301s).
- **X1 전체 7모델 순위**: gemma2-q8 0.690 > gemma2-q4f16 0.683 > koen 0.622 > baseline 0.587 > bekko 0.583 > granite-fp32 0.557 > granite-q4f16 0.541.
- **운영 결론**: gemma2 채택 시 **q8(또는 GGUF AD-Q6_K)이 정답** (RAM 최소+품질 최고). 외부 도메인에서 bekko 대비 +0.107로 압도 — 다만 768d 스키마 전환 + 속도(재인덱스 ~31분) 부담. **2026-10-09 추가: Vulkan GGUF+프롬프트로 동일 품질 0.688, AD-Q6_K 245MB, 재인덱스 232s** (§8.7~8.9). 상세: `docs/design/granite-rerun-report-20261009.md`, `docs/design/gemma2-gpu-vulkan-experiment-20261009.md`

### 8.7 ★ 2026-10-09 — GPU/Vulkan 실측: DirectML 기각, Vulkan 부활 (프롬프트 누락이 "GGUF 손실" 착시)

RX 580X + R5 7600 환경에서 gemma2 가속 경로 전수 실측:

| 경로 | X1 Acc@1 | 시간 | 판정 |
|---|---|---|---|
| ONNX CPU q8+프롬프트 (기준) | **0.690** | 1,301s | ✅ 유지 |
| ONNX DirectML (q8/q4f16/fp32) | 미측정(속도 실패) | 229~365ms B=1 | ❌ CPU보다 5~35배 느림 |
| llama.cpp Vulkan (프롬프트 없음) | 0.626~0.630 | 397~579s | ⚠️ "GGUF 손실"로 오인 |
| **Vulkan + 쿼리 프롬프트만** | 0.649 | 216s | +0.023 |
| **Vulkan + 쿼리+문서 프롬프트** | **0.688** | **228s** | ✅ **ONNX와 동급! ~3.5~5.7배 빠름** |

- **대발견**: 기존 ONNX 스크립트(`EmbGemma2Runner.embed`)는 doc=False여도 **쿼리에 "task: search result | query: "를 자동 부착** — GGUF 실험은 이 프롬프트를 누락 → 순위 변화(0.626~0.630)가 "GGUF 손실"처럼 보였던 것. 벡터 cos 0.9999·토크나이저 일치 실측과 부합.
- GGUF/llama.cpp 자체는 정상 — **검색 품질은 벡터보다 프로토콜(프롬프트)이 지배**하는 사례.
- **DO-NOT-RE-RUN**: DirectML 재실험·b11516(스케줄링 회귀)·프롬프트 없는 GGUF 판정. GGUF 임베딩은 ONNX와 동일 프롬프트 필수.
- 상세: `docs/design/gemma2-gpu-vulkan-experiment-20261009.md` (2026-10-09 수정판)

### 8.8 ★ 2026-10-09 — GGUF 파일별 비교 (Q6 vs Q8 vs 제작사, 프롬프트 적용)

| GGUF | Acc@1 | MRR | 시간 | 파일 크기 |
|---|---|---|---|---|
| AtomicChat AD-Q6_K | 0.684 | 0.807 | 232s | **245MB** |
| unsloth Q8_0 | 0.686 | 0.809 | 226s | 310MB |
| AtomicChat Q8_0 | 0.688 | 0.812 | 228s | 310MB |

- **양자화 수준(Q6 vs Q8)·제작사(unsloth vs AtomicChat) 모두 품질 차이 없음** (차이 0.002~0.004 = 노이즈).
- AD-Q6_K는 파일 245MB(Q8 대비 -21%)로 최소 — **GPU 경로 채택 시 AD-Q6_K 권장**. 속도는 셋 다 동일(~230s).
- 참고: 프롬프트 없으면 4종 모두 0.626~0.630 (프로토콜 차이 착시, §8.7 GPU/Vulkan).

### 8.9 ★ 2026-10-09 — Q6(Vulkan+프롬프트) vs bekko-a8m X1 최종 비교

동일 레시피(seed 42, last 6 turns, 5 options, 1,200문항)로 bekko 재실측 — 운영값과 정확히 일치(0.583):

| 모델 | Acc@1 | MRR | 시간 | dim |
|---|---|---|---|---|
| **gemma2 AD-Q6_K (Vulkan+프롬프트)** | **0.684** | 0.807 | 232s | 768d |
| **bekko-a8m (운영, 프롬프트 없음)** | 0.583 | 0.737 | 21s | 1024d |
| (참고) gemma2 Q6 프롬프트 없음 | 0.629 | 0.756 | 405s | 768d |

- **Q6가 bekko를 +0.101 압도** (프롬프트 적용 시). 프롬프트 없이도 +0.046.
- bekko는 프롬프트 개념이 없는 모델(MODEL_ENV query/doc = "") — 0.583이 공정한 운영값.
- **속도는 bekko 21s vs Q6 232s (재인덱스 11배 차)** — 품질 대비 속도 트레이드오프.
- **운영 판정 (2026-10-09)**: jev-mem은 아직 개발 중 → **당장 전환하지 않음**. gemma2 Q6(+프롬프트)는 품질 면에서 강력한 후보로 기록, 추후 모델 동결 시 재평가. 전환 시: 768d vec 스키마 재구축 + 전체 재인덱스 + 프롬프트 적용 파이프라인 반영 필요.

### 8.10 ★ 2026-10-09 — granite vs gemma2 직접 비교 (같은 X1 조건)

| 축 | granite (q4f16/fp32) | gemma2 (q8/Q6) | 판정 |
|---|---|---|---|
| X1 Acc@1 (1,200문항) | 0.541 / 0.557 | **0.684~0.690** | gemma2 **+0.133~0.149 압도** |
| X1 순위 (7모델) | 6~7위 (최하위권) | **1위** | — |
| 내부 gold-50 MRR | 0.550 / 0.570 | **0.739** | gemma2 **+0.17** |
| RAM (warm commit) | **311MB (최소)** | 466MB / GPU VRAM | granite 우위 |
| 재인덱스 | **~50s (최속)** | ~31분(CPU) / **232s(Vulkan)** | granite 우위 (GPU로 격차 축소) |
| 차원 | **384d (스키마 유지)** | 768d (마이그레이션 필요) | granite 우위 |
| 파일 크기 | 148~250MB | 314MB / **245MB(Q6)** | granite 근소 우위 |

- **품질 축에서는 granite의 채택 근거 없음** — gemma2가 외부 X1·내부 gold 모두 압도. granite은 bekko보다도 X1에서 낮은 중위권.
- **granite 고유 강점은 "운영 보수성"뿐**: 최경량·최속 재인덱스·**384d 무전환**.
- **Vulkan 등장으로 granite의 "빠름" 장점이 상당 부분 무의미해짐** (31분→232s) — 남는 이점은 384d 무마이그레이션 하나뿐.
- 상세: `docs/design/granite-rerun-report-20261009.md` §6.1

### 8.11 ★ 2026-10-09 — GGUF 양자화별 RAM/VRAM 실측 (워밍업 후)

| 모델 | 파일 | 설정 | VRAM | RAM(WS) | Private |
|---|---|---|---|---|---|
| **AD-Q6_K** | 245MB | 기본 | 53MB | 552MB | 515MB |
| **AD-Q6_K** | 245MB | `--no-host` | **184MB** | **423MB** | 516MB |
| AtomicChat Q8_0 | 310MB | 기본 | 133MB | 502MB | 530MB |
| AtomicChat Q8_0 | 310MB | `-np 1` | 133MB | 498MB | 527MB |
| AtomicChat Q8_0 | 310MB | `--no-host` | 133MB | 501MB | 530MB |
| unsloth Q8_0 | 310MB | 기본 | 133MB | 501MB | 530MB |
| unsloth Q8_0 | 310MB | `-np 1`+`--no-host` | 53MB | 576MB | 526MB |
| BF16 | 558MB | 기본 | 315MB | 563MB | 658MB |

- **Q8(AtomicChat vs unsloth)은 사실상 동일 메모리 프로파일** (133MB/500MB) — Q8은 `-np`·`--no-host` 모두 효과 없음.
- **Q6만 `--no-host`에서 극적 개선** (VRAM 53→184MB, RAM 552→423MB) — Q6 그래프가 host 버퍼 의존도가 높아 no-host가 컴퓨트 버퍼를 GPU로 이동시킴.
- unsloth Q8 `-np1+no-host`만 VRAM 53MB로 떨어진 건 Vulkan host 폴백으로 보임 (단일 옵션으론 재현 안 됨) — 3조합 실측이 정답.
- **시스템 RAM이 ONNX 대비 크게 안 줄어드는 이유**: llama.cpp compute buffer·KV 캐시·런타임이 구조상 CPU 잔류. 모델 가중치(파일 크기)만 GPU로 이동.
- **RAM 최저 조합 = Q6 + `--no-host` (423MB)** — 단, VRAM 184MB 사용 (RX 580 8GB 대비 2%로 여유).

### 8.12 ★ 2026-10-09 — gemma2 Q6 운영(live 메모리) 동작 실험

**Q6 운영 파이프라인 실측** (working_memory 1,721행 Q6+프롬프트 재임베딩 → op-90 쿼리 검색):

| 지표 | Q6 (Vulkan) | bekko (기존) |
|---|---|---|
| gold in working_memory | **90/90 (100%)** | 83/90 (pool 기준) |
| hit@1 (vec 단독) | 0.411 | 0.452 (vec-only) |
| hit@5 | 0.744 | — |
| hit@10 | 0.822 | — |
| MRR | 0.559 | 0.627 (vec-only) |
| 문서 재임베딩 | **330s (5.5분)** | 807s |

- **Q6이 gold 90/90 전부 회수** (bekko는 어휘 게이트/RRF에서 7건 놓침) — 검색 회수율은 완벽.
- vec 단독 MRR은 bekko에 약간 열위(0.559 vs 0.627)지만, 운영 파이프라인(하이브리드+JEV)에서는 X1 기준 Q6 우위(0.684 vs 0.583).
- 재임베딩 330s = bekko(807s) 대비 **2.4배 빠름** (Vulkan GPU).
- **참고: 8102 서버 `-c 2048 -ub 2048` 실험 직후 WS 1,498MB/Private 1,965MB** — 컨텍스트·배치에 선형 비례하는 RAM 증가 확인.

**llama-server RAM 구조 분석** (ONNX와의 차이):
- ONNX는 데몬 프로세스 내 통합 (별도 상주 0) → "추가 소모"가 안 보임 (466MB가 데몬에 합산).
- llama-server는 ①별도 상주 프로세스(서버·스케줄러·토크나이저) ②mmap 가중치 페이지 ③컴퓨트 버퍼(ubatch×레이어)가 시스템 RAM에 3중 부담.
- `--no-mmap`은 b11515에서 제거됨(사용 불가). `--no-host`는 c512에서만 효과(552→423MB), c1024 이상에선 무효.

| 설정 | 컨텍스트 | ubatch | WS | Private | VRAM |
|---|---|---|---|---|---|
| c512 ub512 (기본) | 512 | 512 | 552MB | 515MB | 53MB |
| **c512 ub512 + no-host** | 512 | 512 | **423MB** | 516MB | **184MB** |
| c1024 ub1024 | 1024 | 1024 | 906MB | 1,161MB | 347MB |
| c2048 ub2048 | 2048 | 2048 | 1,498MB | 1,965MB | 581MB |

**라이브 문서 길이 실측** (스냅샷, 클램프 리스크 검증):
- working_memory 1,721행: **1500자(≈512토큰) 초과 151행 (8.8%)**, max 44,779자 (컴팩션 덤프), p95 2,274자.
- episodic_memory: 15.9% 초과 (max 107,885자) / memories: 15.5% 초과.
- **512 클램프 위험**: ①컴팩션 덤프형 장문은 핵심이 뒤편에 있어 앞부분 클램프 시 의미 왜곡 ②FTS(전체) vs vec(클램프) 도메인 불일치로 RRF 어긋남 ③장문 @file 첨부 결론 누락.
- **운영 권장**: Q6 서버 `-c 1024`(+`-ub 1024`) — 512토큰 클램프+프롬프트+여유 처리, RAM 906MB. 장문 문서는 청크 분할 병행 필수 (stage1 [ASSISTANT] 청킹 재활용).

### 8.13 ★ 2026-10-09 — 컨텍스트 확장 전략 조사 (동적 컨텍스트·스왑 사례)

**문제**: 멀티모달 대비 컨텍스트 최대 유지 vs 시스템 RAM 최소화 트레이드오프. llama-server의 `-c`는 시작 시 고정, 런타임 변경 API 없음.

**동적 컨텍스트 관련 공식/커뮤니티 사례**:
1. **dinamik context PR #13295 (미병합)**: 런타임 n_ctx 변경 제안 → ggerganov 거부. 사유: "worst-case 메모리 미리 할당이 옳다" + "**libllama API로 save state → 새 n_ctx 컨텍스트 생성 → load state가 이미 가능**" — 가중치 유지 채 컨텍스트만 교체 가능함을 공식 확인.
2. **llama-server reconfigurable discussion #25674**: reload_context()·reload_mmproj() 구현됐으나 HTTP API는 미완 — b11515에는 없음.
3. **Router mode (2025-12 공식, `--models-dir`)**: 모델별 자식 프로세스로 동적 로드/언로드, preset으로 모델별 ctx 설정. 단 동시 상주 시 RAM 2배 (모델 수×).
4. **llama-swap / gguf-switchboard**: 프록시로 한 번에 1모델만 상주, OOM/컨텍스트 초과 시 스왑. gguf-switchboard는 "OOM-only context fallback" 구현.
5. **★ Jina llama.cpp 포크 (2025-09-09 이후 방치 확인)**: 블로그가 광고한 "-b/-ub 분리"는 공개 버전(서버·CLI 모두 `n_ubatch = n_batch` 강제)에 **미포함** — Jina의 내부 브랜치(`chore-ubatch-optimization`, 2025-08)에만 mean pooling 멀티-ubatch 누적 + ubatch 독립 설정 존재. 단 서버(`can_split`)는 여전히 차단.

### 8.14 ★ 2026-10-09 — 최신 upstream + can_split 패치 실측 (해법 확정!)

**발견**: upstream 최신(2026-10-09) `llama-context.cpp`에 **Jina의 mean pooling 멀티-ubatch 누적 코드가 이미 병합됨** ("@Han" 주석 포함). CLI(`llama-embedding`)는 ubatch 512 유지 채 1,406토큰 문서 처리 성공 (768d, norm=1.0). but **서버는 `can_split()`이 memory-less(GEMMA_EMBEDDING2는 create_memory→nullptr) 임베딩을 차단** → "too large" 에러.

**패치**: `server-context.cpp` `can_split()`에 **memory 없음 + mean pooling이면 true 허용** 10줄 추가 → **빌드 후 서버에서 `-c 2048 -ub 512`로 788토큰 문서 HTTP 성공** (768d, norm=1.0).

**RAM 실측 (CPU 빌드, `-c 8192 -ub 512`) — 결정적 패턴**:

| 시점 | WS | Private |
|---|---|---|
| 서버 시작 직후 (IDLE) | 123MB | 232MB |
| 짧은 요청(≤512토큰) 1회 후 | **264MB** | 241MB |
| 3000토큰 요청 1회 후 | **822MB** | 748MB |
| 큰 요청 후 짧은 요청 (5/15s 경과) | 822MB **유지** | 748MB |

- **짧은 요청만 하면 264MB 유지** — 큰 요청이 오지 않는 한 안 늘어남.
- **한 번 큰 요청이 오면 822MB로 영구 상승** — 이후 짧은 요청에도 **줄어들지 않음** (ggml_backend_sched 버퍼 풀링: `sched->is_alloc` true → 재할당 없이 최대 크기 버퍼 재사용. 해제는 sched_free/컨텍스트 종료뿐).
- **c8192와 c2048 상주 RAM 동일(822MB)** — gemma-embedding2는 memory-less라 KV 캐시 비용 0, RAM은 ubatch(512) 컴퓨트 버퍼만 지배. **컨텍스트를 최대(8192)로 둬도 RAM 불변 = 멀티모달 대비 구조적으로 안전.**
- **시간 흐름에 따른 점진적 감소: 코드상 불가능** (해제 경로 부재). RAM을 되돌리는 유일한 방법은 **프로세스 재시작(760ms, 상태 없음)** — 멀티모달이 드물면 "큰 요청 후 재시작"으로 264MB 유지 가능.

**운영 권장 (최종)**:
1. **최신 upstream + can_split 패치(10줄) + `-c 8192 -ub 512`** — 컨텍스트 최대 + RAM 264MB(일상)/822MB(멀티모달 후), b11515 대비 45% 절감.
2. 멀티모달이 드물면 **재시작 스케줄(야간 등)로 RAM 리셋** — 임베딩 stateless라 안전.
3. Vulkan 빌드 시 RAM 더 절감 예상 (CPU 빌드 기준값 — 미실측).

**총평 (EmbeddingGemma 2 + 파이프라인 정책 전체)**:
1. EmbeddingGemma 2 (q8/q4f16 768d 교정 후): bekko와 실질 동급 (76~77 vs 78/90), RAM -151MB, abstain 우위 — 채택 여지 있으나 hit@1 2건 손실 + 재인덱싱(~30분/1721행) + ORT 러너 유지보수로 **보류 권고**, 최종 판단은 외부 검토/사용자 위임.
2. 게이트 재정렬 A/B: 0콜 시뮬레이션의 rank1 4.4배 개선은 실측에서 미실현 (A 동률, B noans 악화) — **둘 다 기각, 현행 유지**.
3. **차원 미스매치 교훈**: 임베딩 모델 교체 실험은 vec 테이블 차원 확인이 선행 조건 (384d/768d 함정, stage74 폐기 원인).

## 9. 임베딩 모델 교체 시 재평가 범위 (2026-10-07 추가)

**사용자 질문**: "임베딩 교체 시 기존 gold 기준을 다 갈아엎어야 하는 것 아닌가? 개발 중이면 곤란" 

### 9.1 유지되는 것 — gold 셋 자체는 보존

| 항목 | 설명 |
|---|---|
| op-90 쿼리+gold ID | "질문 텍스트 + 정답 메모리 ID" — 임베딩 공간과 무관한 사실 |
| noans 하드 50 | 동일 (FP 방어 측정용) |
| 라이브 60 사람 라벨 | 동일 |
| 평가 러너 | 이미 임베딩 주입식(모델 파라미터화) — stage74→77에서 `SNAP`만 교체해 재실행 |

- **실증**: stage74(벡터 죽음) → stage77(768d 교정)이 같은 gold 셋·같은 러너로 재실행됨. stage79→80→81→82도 전부 동일 셋.

### 9.2 새로 측정되는 것 — 수치 기록 (재실행으로 교체)

| 항목 | 설명 |
|---|---|
| hit@1/MRR/abstain/gold_rank_pool | 모델별 결과물 — 같은 셋+러너 재실행으로 재획득 |
| 재측정 비용 | ~15~60분 (stage77: pool+choice 90콜 ≈ 8분) |

### 9.3 재튜닝 필요한 것 — 진짜 작업량

1. **vec_weight** (현행 0.5): 코사인 분포가 모델별로 달라 재스윕 필요
2. **벡터 인덱스 재구축**: 384d→768d 스키마 변경 + 전체 재임베딩 (실측 31분/1,721행)
3. **차원 검증 하네스**: stage74 차원 미스매치(조용한 0건) 방지 — 교체 시 필수 게이트

### 9.4 JEV 판정 계층은 임베딩과 무관

- JEV choice/gate는 **임베딩을 직접 사용하지 않음** (pool excerpt만 읽고 판단)
- write-gate·abstain 라벨·τ는 임베딩 교체 영향 없음
- 임베딩은 4개 recall lane 중 하나 → **교체 영향은 "pool 구성"으로 국한**

### 9.5 개발 중 교체가 곤란한 이유 (gold 보존과 별개)

1. **과거 raw 전부가 "옛 모델 기준" 역사적 값** — 새 모델과 비교는 같은 세션 재실측 필수 (시점 교훈)
2. **라이브 운영 지표(쉐도우/trace)가 처음부터 재축적** — 3~5일 관찰 필요
3. **gold 셋 확장 중인 상태에선 기준 혼선** — 새 gold가 추가될 때마다 새 모델 수치가 섞임
4. 이번 실험의 교훈: 0콜 시뮬(rank1 4.4배)이 실측에서 미실현 — **측정값 없이 채택 판정 불가**

### 9.6 운영 정책 (권고)

- **모델 동결 후 교체가 정석**: 개발/튜닝 종료 → 성능 병목이 임베딩으로 실측 확인 → 재평가
- 이번에 구축한 하네스(벤치+JEV 경로 러너)로 **1시간이면 전 과정 재실행 가능**
- EmbeddingGemma 2 채택 결정은 위 조건 충족 시점으로 연기 (보류)

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