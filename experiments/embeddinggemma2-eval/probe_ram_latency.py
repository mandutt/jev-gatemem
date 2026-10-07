"""EmbeddingGemma 2 q4f16 — RAM + latency probe (fresh process per model).
Mirrors s3_p2_ram_latency.py but supports ORT-direct runner (gemma2) and
fastembed incumbents. Usage: python probe_ram_latency.py <gemma2|bekko|baseline> <out.json>
"""
import os, sys, json, time
import numpy as np

B = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20261006-embedgemma2")
B93 = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20260930")
which, out_path = sys.argv[1], sys.argv[2]

QUERIES = [
    "게이트웨이 텔레그램 수신 문제 해결", "임베딩 모델 교체 실험 설계", "Hermes 프로필 백업 및 복구 절차",
    "SQLite WAL 모드 동시 쓰기 직렬화", "벤치마크 사전 등록 게이트 기준", "비밀번호 볼트 origin 바인딩 검증",
    "윈도우 프로세스 커밋 메모리 실측", "세션 로그 아카이브 정리 방법", "플러그인 자체 완결성 원칙",
    "재임베딩 배치 크기 OOM 분석",
] * 3


def mem_mb(pid):
    import ctypes, ctypes.wintypes as wt
    class PMC(ctypes.Structure):
        _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    pmc = PMC(); pmc.cb = ctypes.sizeof(PMC)
    psapi = ctypes.WinDLL("Psapi.dll")
    h = ctypes.WinDLL("kernel32.dll").OpenProcess(0x0400 | 0x0010, False, pid)
    psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb)
    return pmc.PagefileUsage // (1024*1024), pmc.WorkingSetSize // (1024*1024)


pid = os.getpid()
mb0, ws0 = mem_mb(pid)
t0 = time.time()

if which == "gemma2":
    sys.path.insert(0, B)
    from embgemma2_runner import EmbGemma2Runner
    m = EmbGemma2Runner(os.path.join(B, "model-src"))
    def emb1(t):
        return list(m.embed([t]))[0]
    def embd(t):
        return list(m.embed([t], doc=True))[0]
elif which in ("bekko", "baseline"):
    os.environ["HF_HOME"] = os.path.join(B93, "model-cache")
    os.environ["HF_HUB_OFFLINE"] = "1"
    sys.path.insert(0, B93)
    from fastembed import TextEmbedding
    alias = "bench/bekko-a8m" if which == "bekko" else "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    if which == "bekko":
        from register_custom import register
        register(alias)
    m = TextEmbedding(model_name=alias, cache_dir=os.path.join(B93, "fe-cache"))
    _obj = getattr(m, "model", m)
    tok = getattr(_obj, "tokenizer", None)
    if tok is not None and hasattr(tok, "enable_truncation"):
        tok.enable_truncation(max_length=512)
    def emb1(t):
        return next(m.embed([t]))
    def embd(t):
        return next(m.embed([t]))
else:
    raise SystemExit("unknown model " + which)

load_s = time.time() - t0
mb_cold, ws_cold = mem_mb(pid)

# warm
for q in QUERIES[:5]:
    emb1(q)
time.sleep(10)
mb_warm, ws_warm = mem_mb(pid)

lat = []
for rep in range(5):
    for q in QUERIES:
        t = time.time(); emb1(q); lat.append(time.time() - t)
lat = np.array(lat) * 1000

res = {
    "model": which, "load_s": round(load_s, 2),
    "private_commit_mb": {"cold": mb_cold, "warm": mb_warm},
    "working_set_mb": {"cold": ws_cold, "warm": ws_warm},
    "latency_ms": {"n": len(lat), "p50": float(np.percentile(lat, 50)),
                   "p95": float(np.percentile(lat, 95)), "p99": float(np.percentile(lat, 99)),
                   "max": float(lat.max())},
}
with open(out_path, "w") as f:
    json.dump(res, f, indent=2)
print(json.dumps(res))
print("P2 DONE", which)