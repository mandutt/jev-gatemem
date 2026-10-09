# gemma2 Q6 llama.cpp 운영 가이드 (2026-10-09 최종 확정)

> 상태: **운영 확정** — 사용자 결정 (2026-10-09). 추후 gemma2 채택 시 이 문서대로 운영.
> 관련: `experiments/embeddinggemma2-eval/README.md` §8.12~8.15, `docs/design/gemma2-gpu-vulkan-experiment-20261009.md`

---

## 1. 최종 선택 (확정 요약)

| 항목 | 선택 | 이유 |
|---|---|---|
| 모델 | **AtomicChat AD-Q6_K** (`atomic_q6.gguf`, 245MB) | Q6/Q8/제작사 무관 동일 품질(X1 0.684~0.688), 파일 최소 |
| 런타임 | **최신 upstream 직접 빌드 + can_split 패치** | 서버도 ubatch 분할 지원 (b11515는 대형 문서 에러) |
| 백엔드 | **Vulkan** (ReBAR 8GB 활성화 후) | 3000토큰 후 WS 581MB (ReBAR 256MB 시절 938MB 대비 -38%) |
| 옵션 | **`-c 8192 -ub 512 -ngl 99 -np 1 --no-host`** | 컨텍스트 최대 + ubatch 512 + GPU 오프로드 |
| 프롬프트 | query: `task: search result \| query: `, doc: `title: none \| text: ` | ONNX와 동일 — **누락 시 검색 품질 급락** (0.626 vs 0.688) |
| 운영 판정 | jev-mem 개발 완료 후 채택 | 당장 전환 없음, 모델 동결 시 이 문서대로 운영 |

## 2. 빌드 (Windows 11, MinGW)

### 2.1 필요 도구
- MSYS2 (ucrt64, gcc 16.1)
- pacman 패키지: `mingw-w64-ucrt-x86_64-vulkan-headers`, `-vulkan-loader`, `-glslang`, `-shaderc`, `-spirv-headers`

```bash
pacman -S --needed mingw-w64-ucrt-x86_64-vulkan-headers mingw-w64-ucrt-x86_64-vulkan-loader \
  mingw-w64-ucrt-x86_64-glslang mingw-w64-ucrt-x86_64-shaderc mingw-w64-ucrt-x86_64-spirv-headers
```

### 2.2 소스·패치
```bash
git clone --depth 1 https://github.com/ggml-org/llama.cpp.git
cd llama.cpp
# can_split 패치: tools/server/server-context.cpp
#   메모리 없음(memory-less 임베딩) + mean pooling이면 split 허용 (아래 §4)
```

### 2.3 빌드
```bash
export PATH="/c/msys64/ucrt64/bin:$PATH"
cmake -B build-vulkan -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_PREFIX_PATH="/c/msys64/ucrt64"
cmake --build build-vulkan --config Release --target llama-server -j $(nproc)
# 출력: build-vulkan/bin/llama-server.exe
```

## 3. 운영 실행

### 3.1 환경 (중요!)
```bash
# vulkan-1.dll 로딩 필수 — 없으면 조용히 CPU 폴백 (VRAM 0, 로그 흔적 없음)
export PATH="/c/msys64/ucrt64/bin:/c/Windows/System32:$PATH"
```

### 3.2 서버 기동
```bash
./llama-server.exe -m atomic_q6.gguf --embeddings \
  --port 8102 --host 127.0.0.1 \
  -c 8192 -ub 512 -ngl 99 -np 1 --no-host --no-warmup
```

### 3.3 하드웨어 사전 조건 — ReBAR 활성화 (필수!)
- **BIOS에서 Resizable BAR/Smart Access Memory 활성화 후 재부팅**
- 활성화 전: `memoryTypes[2]` = 256MB DEVICE_LOCAL+HOST_VISIBLE (ReBAR 윈도우 256MB 한계) → 대형 입력이 RAM 폴백 → 3000토큰 후 WS 938MB
- 활성화 후: VRAM 힙(8GB) 자체에 HOST_VISIBLE 조합 → 3000토큰 후 WS **581MB** (-38%)
- 확인: `vulkaninfo`에서 `MEMORY_PROPERTY_DEVICE_LOCAL_BIT + HOST_VISIBLE_BIT`가 heapIndex=1(8GB)에 존재

### 3.4 프롬프트 (필수!)
| 역할 | 프롬프트 |
|---|---|
| 쿼리 | `task: search result \| query: ` + 텍스트 |
| 문서 | `title: none \| text: ` + 텍스트 |

## 4. can_split 패치 내용

`tools/server/server-context.cpp`의 `server_slot::can_split()`:

```cpp
// if the context does not have a memory module then all embeddings have to be computed within a single ubatch
if (!llama_get_memory(ctx_tgt)) {
    // @patch(gemma-embedding2): decoder-only embedding models (gemma-embedding, gemma-embedding2)
    // have no KV memory (create_memory returns nullptr) but are CAUSAL, so the stateless
    // batch_decode path in the server can process the prompt in ubatch chunks and the
    // mean-pooling accumulator in llama-context.cpp merges the per-ubatch embeddings.
    // Allow splitting when pooling is MEAN (identical to what examples/embedding does).
    const auto pooling_no_mem = llama_pooling_type(ctx_tgt);
    if (pooling_no_mem == LLAMA_POOLING_TYPE_MEAN) {
        return true;
    }
    return false;
}
```

**근거**: upstream llama-context.cpp에 이미 Jina의 mean pooling 멀티-ubatch 누적 코드가 병합됨 ("@Han" 주석). 즉 분할 처리 시 정확한 임베딩이 보장됨. 패치는 그 분할을 서버에서 허용하는 것뿐.

## 5. 검증 실측 (2026-10-09)

### 5.1 품질
- X1 KoDialogBench 1,200문항: **AD-Q6_K 0.684** / unsloth Q8 0.686 / AtomicChat Q8 0.688 (동급)
- ONNX CPU 0.690과 동급 (차이 0.002~0.006 = 노이즈)
- 프롬프트 누락 시 0.626~0.630 → **프롬프트는 필수**
- gold 90/90 회수 (op-90, bekko 83/90), 재인덱스 330s (bekko 807s 대비 2.4배)

### 5.2 RAM/VRAM (ReBAR 활성화 후, Vulkan)

| 상태 | VRAM | WS (시스템 RAM) | 비고 |
|---|---|---|---|
| 시작 직후 | 136MB | 390MB | — |
| 짧은 요청(≤512토큰) 후 | 264MB | **171MB** | 일상 검색 상태 |
| 3000토큰 요청 후 | 295MB | **581MB** | 멀티모달/대형 문서 후 |

- **RAM은 요청 크기에 따라 단계 상승, 자동 감소 없음** — ggml_backend_sched 버퍼 풀링
- 감소 방법: 프로세스 재시작 (기동 ~760ms, 임베딩 stateless라 안전)
- ReBAR 전(256MB) 3000토큰 후 938MB → ReBAR 후 581MB

### 5.3 성능
- 3000토큰 임베딩: 2.2~3.7s (Vulkan), 3.5s (CPU 빌드) — Vulkan ~1.5x
- 서버 기동~health: ~760ms
- ubatch 분할: 1406토큰·3388토큰 문서도 ubatch 512로 정상 처리 (패치 전: "too large" 에러)

## 6. 운영 가이드 (추후 gemma2 채택 시)

1. **기동**: §3 명령 그대로 (c8192 ub512 ngl99 np1 no-host)
2. **일상 검색**: 512토큰 클램프(운영 기존 정책 유지) → WS 171MB
3. **멀티모달/대형 문서**: 클램프 없이 전송 가능 (8192 컨텍스트) → WS 581MB로 상승, **재시작 전까지 유지**
4. **RAM 회수**: 멀티모달이 드물면 프로세스 재시작 (760ms) — stateless라 무중단 스왑 가능
5. **장문 문서**: 8.8%가 1500자(≈512토큰) 초과 (max 44,779자 컴팩션 덤프). 청크 분할 병행 권장 (FTS 전체 vs vec 클램프 도메인 불일치 방지)
6. **DO-NOT**: DirectML 재실험, b11516 사용, 프롬프트 없는 임베딩, `-ub`를 2048로 (RAM 폭증)

## 7. 파일 위치

| 항목 | 경로 |
|---|---|
| GGUF | `%LOCALAPPDATA%/jev-mem/bench/gemma2-gguf/atomic_q6.gguf` |
| 소스+빌드 | `%LOCALAPPDATA%/jev-mem/bench/llama-upstream-latest/` (build-vulkan/) |
| 패치 파일 | `tools/server/server-context.cpp` (can_split, §4) |
| 실측 로그 | `%LOCALAPPDATA%/jev-mem/bench/run-20261006-embedgemma2/q6_op_experiment.log`, `/tmp/vk_*.log` |

## 8. 알려진 한계

- **host_malloc 513MB는 llama.cpp 로그상 host로 표기**되지만, ReBAR 활성화 후 실제 시스템 RAM 부담은 -38% (Windows Shared 집계)
- gemma-embedding2는 memory-less → **KV 캐시 없음** → c8192 상주 비용 = c2048과 동일 (RAM 불변)
- Vulkan 런타임·전송 버퍼 오버헤드로 **CPU 빌드보다 RAM 100~140MB 높음** (ReBAR 전 기준) — 속도 1.5x가 필요할 때만 Vulkan 유지 의미. ReBAR 후 CPU 빌드 대비 차이 재측정 필요.