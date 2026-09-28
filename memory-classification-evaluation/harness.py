"""Shared harness: import the LIVE Mnemosyne classifier and return its pieces.

Read-only evaluation.  Never patches, never writes to Mnemosyne.
The classifier is loaded directly from the Hermes runtime venv (the same
file that production uses), so results reflect the real baseline exactly.
"""
import importlib.util
import sys
from pathlib import Path

# Hermes runtime venv — the patched, production-active typed_memory.py
VENV_TYPED_MEMORY = Path(
    r"C:\Users\mandu\AppData\Local\hermes\installs\315db7b763fb0d0a"
    r"\environments\746564964b1042b79add42260378503b"
    r"\venv\Lib\site-packages\mnemosyne\core\typed_memory.py"
)


def load_classifier():
    """Import the live module; returns (classify_memory, MemoryType, TYPE_PATTERNS)."""
    spec = importlib.util.spec_from_file_location(
        "typed_memory_live", VENV_TYPED_MEMORY
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["typed_memory_live"] = mod
    spec.loader.exec_module(mod)
    return mod.classify_memory, mod.MemoryType, mod.TYPE_PATTERNS


def classify_text(func, text: str):
    """Call classifier and return a plain-dict result (JSONL-safe)."""
    r = func(text)
    return {
        "memory_type": r.memory_type.value,
        "confidence": round(r.confidence, 3),
        "matched_pattern": r.matched_pattern,
        "priority": r.priority,
    }


if __name__ == "__main__":
    classify, MT, PATTERNS = load_classifier()
    print("types:", [t.value for t in MT])
    print("num_patterns:", len(PATTERNS))
    for s in ["좋아 진행해줘.", "오류가 발생했어.", "앞으로 표로 정리해줘.", "나는 Rust를 선호해."]:
        print(f"{s!r:30} -> {classify_text(classify, s)}")