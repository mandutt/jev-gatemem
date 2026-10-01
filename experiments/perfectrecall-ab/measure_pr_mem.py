"""PR venv 파이썬의 메모리 풋프린트 측정 (격리 — 프로세스 자체)
"""
import os, sys, json, subprocess, time

def get_peak_mb(pid):
    """Windows: GetProcessMemoryInfo PeakWorkingSetSize"""
    import ctypes
    from ctypes import wintypes
    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    h = ctypes.windll.kernel32.OpenProcess(0x0400 | 0x0010, False, pid)  # QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        c = PROCESS_MEMORY_COUNTERS()
        c.cb = ctypes.sizeof(c)
        if ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb):
            return c.PeakWorkingSetSize / 1e6
        return None
    finally:
        ctypes.windll.kernel32.CloseHandle(h)

def main():
    # 자식 파이썬을 띄워 PR 리콜 로드(코퍼스 + 클라이언트)만 수행 → 피크 메모리
    code = r'''
import sys
sys.path.insert(0, r'C:/Users/mandu/AppData/Local/hermes/cache/scratch/perfectrecall')
from mnemosyne.core import jev, jev_recall
from mnemosyne.core.beam import BeamMemory
beam = BeamMemory(session_id='scratch-eval', db_path=r'C:/Users/mandu/AppData/Local/hermes/cache/scratch/scratch_eval.db')
rows = list(jev_recall.visible_memories(beam, jev_recall._filters()))
print(f'corpus={len(rows)}', flush=True)
import time
time.sleep(8)  # 피크 유지
'''
    p = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding='utf-8', errors='replace')
    peak, got = 0, False
    t0 = time.monotonic()
    while time.monotonic() - t0 < 25:
        mb = get_peak_mb(p.pid)
        if mb:
            peak = max(peak, mb)
            got = True
        try:
            line = p.stdout.readline()
            if line:
                print(line.rstrip(), flush=True)
        except Exception:
            pass
        if p.poll() is not None:
            break
        time.sleep(0.5)
    if p.poll() is None:
        p.kill()
    print(f'PR 프로세스 피크 메모리: {peak:.0f} MB' if got else '측정 실패')

if __name__ == '__main__':
    main()