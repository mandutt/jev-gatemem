"""EmbeddingGemma 2 모달리티별 RAM 비교 — 세션 로드 3단계 실측.

상황: jev-mem은 텍스트 전용. 만약 멀티모달(비전/오디오 인코더 포함) 세션을 열면
RAM이 실제로 늘어나는지, 아니면 추론 전까지 차이가 없는지 측정.

방법: fresh 프로세스 2개
  A) text-only: model_q4f16.onnx 만 세션 생성
  B) full:      model_q4f16.onnx + vision_encoder_q4f16.onnx + audio_encoder_q4f16.onnx 세션 생성
각각 로드 직후 / 10초 after / 텍스트 추론 후 WS+commit 측정.
"""
import os, sys, ctypes, ctypes.wintypes as wt, time, json

def mem_mb(pid):
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
    return pmc.PagefileUsage // (1024 * 1024), pmc.WorkingSetSize // (1024 * 1024)

which = sys.argv[1]  # text | full
SRC = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20261006-embedgemma2\model-src")
import onnxruntime as ort
from tokenizers import Tokenizer
import numpy as np

so = ort.SessionOptions()
so.intra_op_num_threads = 2

pid = os.getpid()
t0 = time.time()

tok = Tokenizer.from_file(os.path.join(SRC, "tokenizer.json"))
tok.enable_truncation(max_length=512)

sess_text = ort.InferenceSession(os.path.join(SRC, "model_q4f16.onnx"), sess_options=so, providers=["CPUExecutionProvider"])
mb_baseline, ws_baseline = mem_mb(pid)
print(f"[{which}] text session loaded: commit={mb_baseline}MB WS={ws_baseline}MB", flush=True)

if which == "full":
    sess_vis = ort.InferenceSession(os.path.join(SRC, "vision_encoder_q4f16.onnx"), sess_options=so, providers=["CPUExecutionProvider"])
    sess_aud = ort.InferenceSession(os.path.join(SRC, "audio_encoder_q4f16.onnx"), sess_options=so, providers=["CPUExecutionProvider"])
    mb_full, ws_full = mem_mb(pid)
    print(f"[{which}] +vision+audio sessions: commit={mb_full}MB WS={ws_full}MB (Δcommit={mb_full-mb_baseline}MB ΔWS={ws_full-ws_baseline}MB)", flush=True)
    time.sleep(5)
    mb_warm, ws_warm = mem_mb(pid)
    print(f"[{which}] after 5s: commit={mb_warm}MB WS={ws_warm}MB", flush=True)
    result = {"mode": which, "text_commit_mb": mb_baseline, "text_ws_mb": ws_baseline,
              "full_commit_mb": mb_full, "full_ws_mb": ws_full, "warm_commit_mb": mb_warm, "warm_ws_mb": ws_warm}
else:
    time.sleep(5)
    mb_warm, ws_warm = mem_mb(pid)
    print(f"[{which}] after 5s: commit={mb_warm}MB WS={ws_warm}MB", flush=True)
    result = {"mode": which, "text_commit_mb": mb_baseline, "text_ws_mb": ws_baseline,
              "warm_commit_mb": mb_warm, "warm_ws_mb": ws_warm}

# 텍스트 추론 1회 (실제 작업 경로 확인)
enc = tok.encode("테스트 문장입니다.")
ids = np.array([enc.ids], dtype=np.int64)
mask = np.array([enc.attention_mask], dtype=np.int64)
out = sess_text.run(["sentence_embedding"], {
    "input_ids": ids, "attention_mask": mask,
    "image_features": np.zeros((0, 512), dtype=np.float32),
    "video_features": np.zeros((0, 512), dtype=np.float32),
    "audio_features": np.zeros((0, 512), dtype=np.float32),
})
mb_after, ws_after = mem_mb(pid)
print(f"[{which}] after text infer: commit={mb_after}MB WS={ws_after}MB", flush=True)
result["after_infer_commit_mb"] = mb_after
result["after_infer_ws_mb"] = ws_after
print("RESULT", json.dumps(result))