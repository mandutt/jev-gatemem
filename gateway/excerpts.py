"""Candidate header / excerpt builder — Stage 1 of the retrieval pipeline (spec §18).

Excerpt rules (spec §18): NOT naive truncation. General text ~80-100 chars;
code/config/error memories keep first line + dense tokens (error codes, package
names, API names). Target: ~120 chars per candidate.
"""
from __future__ import annotations

import re

from gateway.types import RecallHit

_MAX_GENERAL = 100
_MAX_DENSE = 160  # code/error lines may run a bit longer; measured in tokens later

# patterns that mark a memory as code/config/error-flavoured
_DENSE_PATTERNS = [
    re.compile(r"error|exception|traceback|failed|keyerror|syntaxerror|not found", re.I),
    re.compile(r"(?:pip |npm |uv |cargo |adb |git |docker |kubectl |hermes |pi )", re.I),
    re.compile(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*"),   # dotted names
    re.compile(r"--[a-z-]+|/[a-z-]+(?:=[^ ]+)?", re.I),              # flags
]

_CODE_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}|[0-9]{2,}")


def _truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _is_dense(content: str) -> bool:
    return any(p.search(content) for p in _DENSE_PATTERNS)


def _dense_excerpt(content: str) -> str:
    """Keep first line + the most information-dense tokens."""
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    if not lines:
        return ""
    first = lines[0]
    # dense tokens: code-ish words / error codes / version numbers
    tokens = _CODE_TOKEN.findall(content)
    dense = [t for t in tokens if len(t) >= 3][:12]
    excerpt = first
    if dense:
        excerpt += " | " + " ".join(dense)
    return _truncate(excerpt, _MAX_DENSE)


def build_excerpt(content: str, memory_type: str = "") -> str:
    """Type-aware excerpt (spec §18)."""
    if not content:
        return ""
    if memory_type in ("code", "config", "error", "tool", "command", "cli"):
        return _dense_excerpt(content)
    if _is_dense(content):
        return _dense_excerpt(content)
    return _truncate(content, _MAX_GENERAL)


def prepare_candidates(hits: list[RecallHit], *, backend=None) -> list:
    """Convert raw recall hits into candidate headers with excerpts.

    backend: optional MnemosyneBackend whose to_candidate() fills the DTO;
    when None, builds the MemoryCandidate directly from the hit.
    """
    from gateway.types import MemoryCandidate

    out = []
    for hit in hits:
        if backend is not None:
            cand = backend.to_candidate(hit)
        else:
            cand = MemoryCandidate(
                id=hit.id,
                created_at=hit.created_at,
                memory_type=hit.memory_type,
                scope=hit.scope,
                importance=hit.importance,
                source_agent=(hit.metadata or {}).get("source_agent", "") or hit.source,
                mnemosyne_rank=hit.rank,
                similarity_score=hit.score,
            )
        cand.short_excerpt = build_excerpt(hit.content, hit.memory_type)
        out.append(cand)
    return out