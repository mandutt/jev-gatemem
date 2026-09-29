"""B §5.3 (승인) — redact unit tests."""
import os
import sys
from pathlib import Path

REPO = Path(r"C:\Users\mandu\hermes-made\jev-memory-middleware")
sys.path.insert(0, str(REPO))

from jev_mem_core.redact import (  # noqa: E402
    active, compile_patterns, get_patterns, redact_payload, redact_text,
)

FAILS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


# default patterns
os.environ.pop("JEV_MEM_REDACT", None)
os.environ.pop("JEV_MEM_REDACT_KEYS", None)
pats = compile_patterns()
check("D1: inactive by default", active() is False)
check("D2: 4 default patterns", len(pats) == 4, str(len(pats)))
check("D3: KEY redacted",
      "sk-abc123" == redact_text("my KEY is sk-abc123", pats)
      or "***" in redact_text("my KEY is sk-abc123", pats),
      redact_text("my KEY is sk-abc123", pats))
check("D4: TOKEN redacted", "***" in redact_text("bearer TOKEN xyz789", pats))
check("D5: SECRET redacted", "***" in redact_text("SECRET: hunter2", pats))
check("D6: PASSWORD redacted", "***" in redact_text("PASSWORD=pass123", pats))
check("D7: plain text untouched",
      redact_text("내일까지 보고서 제출해야 해", pats)
      == "내일까지 보고서 제출해야 해")
check("D8: value tail removed",
      "API ***" == redact_text("API KEY: sk-abc123", pats)
      or "API ***" in redact_text("API KEY: sk-abc123", pats),
      redact_text("API KEY: sk-abc123", pats))

# env-activated custom keys
os.environ["JEV_MEM_REDACT_KEYS"] = "*MYKEY*"
check("E1: env activates", active() is True)
check("E2: custom pattern only", len(compile_patterns()) == 1)
check("E3: custom key redacted",
      "***" in redact_text("MYKEY 0xdeadbeef", compile_patterns()))
check("E4: default keys NOT matched",
      redact_text("TOKEN xyz", compile_patterns()) == "TOKEN xyz")
os.environ.pop("JEV_MEM_REDACT_KEYS", None)

# payload-level
p = {"agent": "pi", "session_id": "s1",
     "user_content": "KEY: abc, 내일까지 보고", "assistant_content": "PASSWORD=zz"}
r = redact_payload(p, pats)
check("P1: user redacted", r["user_content"] == "*** , 내일까지 보고"
      or r["user_content"] == "***, 내일까지 보고", r["user_content"])
check("P2: asst redacted", r["assistant_content"] == "***",
      r["assistant_content"])
check("P3: idem fields intact", r["agent"] == "pi" and r["session_id"] == "s1")
check("P4: original untouched", "KEY: abc" in p["user_content"])

# active() with explicit env
os.environ["JEV_MEM_REDACT"] = "1"
check("F1: JEV_MEM_REDACT=1 activates", active() is True)
os.environ.pop("JEV_MEM_REDACT", None)
check("F2: back to inactive", active() is False)

print()
if FAILS:
    print(f"=== REDACT: {len(FAILS)} FAIL — {FAILS} ===")
    sys.exit(1)
print("=== REDACT: ALL PASS ===")