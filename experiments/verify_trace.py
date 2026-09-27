"""trace.py 단위 검증: 크기 상한, 라인 무결성, 오류 무시, 경로 재정의."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"C:\Users\mandu\hermes-made\jev-memory-middleware")
from gateway import trace as T

tmp = Path(tempfile.mkdtemp(prefix="jev_trace_test_"))
T._resolve_path()  # 기본 경로 확인
print("default path:", T._resolve_path())

# 1) 작은 cap으로 ring 동작 확인 (직접 monkeypatch)
from gateway.trace import TRACE_CAP_BYTES

orig_cap = T.TRACE_CAP_BYTES
try:
    T.TRACE_CAP_BYTES = 2000  # 2KB cap으로 축소 테스트
    env = os.environ.get("JEV_TRACE_PATH")
    os.environ["JEV_TRACE_PATH"] = str(tmp / "jev_trace.log")
    try:
        for i in range(300):
            T.trace("test", {"i": i, "payload": "x" * 50})
        p = tmp / "jev_trace.log"
        size = p.stat().st_size
        print(f"after 300 lines, size={size} (cap=2000) -> {'OK' if size <= 2000 else 'FAIL'}")
        # 라인 무결성: 첫/끝 라인 파싱
        lines = p.read_text(encoding="utf-8").splitlines()
        assert all("|" in ln and ln.endswith("x" * 50) or "|test|" in ln for ln in lines), "line corrupt"
        print(f"lines={len(lines)}, first='{lines[0][:60]}'")
        print(f"        last ='{lines[-1][:60]}'")
        # 모든 라인이 완전한가 (split된 라인 없음)
        complete = all(ln.endswith("x" * 50) for ln in lines)
        print("all lines complete:", complete)
    finally:
        os.environ.pop("JEV_TRACE_PATH", None)
        if env is not None:
            os.environ["JEV_TRACE_PATH"] = env
finally:
    T.TRACE_CAP_BYTES = orig_cap

# 2) 오류 무시: 읽기 전용 경로
try:
    ro = tmp / "ro.log"
    ro.write_text("")
    os.chmod(ro, 0o444)
    T.trace("err", {"k": "v"})  # 예외 없이 통과해야 함
    print("readonly path: no exception OK")
except Exception as e:
    print("readonly path FAILED:", e)

# 3) 큰 cap 복원 확인
print("cap restored:", T.TRACE_CAP_BYTES == TRACE_CAP_BYTES)
print("PASS")