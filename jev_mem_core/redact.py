"""ACL & redaction for spool/ledger plaintext (B §5.3 — 승인 2026-09-29).

- ACL: %LOCALAPPDATA%/jev-mem user-only icacls (app.apply_data_dir_acl,
  best-effort, 기본 data_dir일 때만).
- redaction: `*KEY*`-style patterns replace matched tokens with `***`.
  - 활성: env `JEV_MEM_REDACT=1` (config [redact] enabled=true 가 app이 주입)
    또는 env `JEV_MEM_REDACT_KEYS` 존재 (어댑터는 env로만).
  - 패턴: env `JEV_MEM_REDACT_KEYS`(쉼표) > config keys > 기본
    `*KEY*,*TOKEN*,*SECRET*,*PASSWORD*`.
  - 적용 범위: 스풀 JSONL + ledger payload_json 의 content 필드만.
    **mnemosyne DB 저장분은 치환 안 함** (의도된 기억 보존, 승인 조건).
- 매칭: 공백 없는 토큰 + 선택적 `:값`/`=값` 뭉치 (case-insensitive).
  예: "API KEY: sk-abc123" -> "API ***"
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

DEFAULT_KEYS = "*KEY*,*TOKEN*,*SECRET*,*PASSWORD*"
ENV_ACTIVE = "JEV_MEM_REDACT"
ENV_KEYS = "JEV_MEM_REDACT_KEYS"

_CONTENT_FIELDS = ("user_content", "assistant_content")


def active() -> bool:
    """Redaction enabled? (env-based — adapters and core both read this.)"""
    if os.environ.get(ENV_ACTIVE) in ("1", "true", "True"):
        return True
    return os.environ.get(ENV_KEYS) is not None


def get_patterns() -> List[str]:
    raw = os.environ.get(ENV_KEYS) or DEFAULT_KEYS
    return [p.strip() for p in raw.split(",") if p.strip()]


def _pattern_to_regex(pat: str) -> re.Pattern:
    """fnmatch-ish: * -> [^\\s]*, ? -> [^\\s], + optional `: value`/`= value` tail.

    The pattern matches a single non-space token CONTAINING the keyword
    (word-boundary prefix/suffix), plus an optional value tail consumed as
    one unit: "API KEY: sk-abc123" -> "API ***"; "PASSWORD=zz" -> "***".
    """
    parts = []
    for ch in pat:
        if ch == "*":
            parts.append(r"[^\s:=]*")
        elif ch == "?":
            parts.append(r"[^\s:=]")
        else:
            parts.append(re.escape(ch))
    return re.compile(
        r"\S*?" + "".join(parts) + r"\S*?(?::[ ]*[^\s,;]+|=[^\s,;]+)?",
        re.IGNORECASE,
    )


def compile_patterns(patterns: Optional[List[str]] = None) -> List[re.Pattern]:
    return [_pattern_to_regex(p) for p in (patterns or get_patterns())]


_REDACTED = "***"


def redact_text(text: str, patterns: Optional[List[re.Pattern]] = None) -> str:
    """Replace matched tokens with '***'. Returns original if no match."""
    if not text:
        return text
    pats = patterns if patterns is not None else compile_patterns()
    if not pats:
        return text
    out = text
    for p in pats:
        out = p.sub(_REDACTED, out)
    return out


def redact_payload(payload: Dict, patterns: Optional[List[re.Pattern]] = None) -> Dict:
    """Redact content fields of a turn payload (copy; other fields untouched)."""
    pats = patterns if patterns is not None else compile_patterns()
    if not pats:
        return payload
    out = dict(payload)
    for f in _CONTENT_FIELDS:
        v = out.get(f)
        if isinstance(v, str):
            out[f] = redact_text(v, pats)
    return out