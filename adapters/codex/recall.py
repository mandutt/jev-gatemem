#!/usr/bin/env python3
"""Codex UserPromptSubmit hook: inject Mnemosyne context via JEV core (P4).

Replaces the embedded-mnemosyne recall path with the JevMemClient (core
HTTP). Reads the Codex hook JSON payload (prompt) from stdin, calls
core /v1/prefetch, and writes a <mnemosyne-context> block to stdout that
Codex appends to the prompt. Fails silently (exit 0, no output) on any
error — prefetch is a degrade path, never a blocker (D7).
"""

import json
import os
import re
import sys

REPO = os.environ.get(
    "JEV_MEM_REPO",
    r"C:\Users\mandu\hermes-made\jev-memory-middleware",
)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from jev_mem_core.client import JevMemClient  # noqa: E402

# Blocks Codex injects around the real user message; strip them from the query
SCAFFOLD_TAGS = [
    "collaboration_mode",
    "apps_instructions",
    "plugins_instructions",
    "skills_instructions",
    "recommended_plugins",
    "permissions instructions",
    "environment_context",
    "supermemory-context",
    "mnemosyne-context",
    "system-reminder",
]
TOP_K = 6
MAX_CHARS = 400


def clean_query(text: str) -> str:
    out = text
    for tag in SCAFFOLD_TAGS:
        out = re.sub(r"<%s>.*?</%s>" % (tag, tag), "", out, flags=re.S)
    return out.strip()


def main() -> int:
    raw = sys.stdin.buffer.read().decode("utf-8", "replace").strip()
    if not raw:
        return 0
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return 0
    query = clean_query(payload.get("prompt") or payload.get("input") or "")
    if not query or len(query) < 3:
        return 0

    try:
        session_id = str(payload.get("session_id") or "")
        ctx = JevMemClient("codex").prefetch(
            query,
            session_id=session_id,
            max_chars=MAX_CHARS * TOP_K,
            timeout_ms=1500,
        )
    except Exception:
        return 0
    if not ctx:
        return 0

    sys.stdout.write(ctx.strip() + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())