#!/usr/bin/env python3
"""Codex Stop hook: auto-save a compact Codex session summary via JEV core (P4).

Replaces the embedded-mnemosyne record path with the JevMemClient (core
HTTP). Reads the Codex hook JSON payload (session_id, transcript_path, cwd),
parses the session JSONL transcript, sends one /v1/turns ingestion per turn.
A 30s debounce plus a content fingerprint prevent duplicate writes for
unchanged turns. Fails silently — the client spools on core failure (D6).
"""

import hashlib
import json
import os
import re
import sys
import time

REPO = os.environ.get(
    "JEV_MEM_REPO",
    r"C:\Users\mandu\hermes-made\jev-memory-middleware",
)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from jev_mem_core.client import JevMemClient  # noqa: E402

STATE_DIR = os.path.join(os.path.expanduser("~"), ".codex", "mnemosyne", "state")
MIN_WRITE_INTERVAL_MS = 30_000

TASK_MAX = 220
OUTCOME_MAX = 500
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


def clean(text: str) -> str:
    out = text
    for tag in SCAFFOLD_TAGS:
        out = re.sub(r"<%s>.*?</%s>" % (tag, tag), "", out, flags=re.S)
    return re.sub(r"\s+", " ", out).strip()


def part_text(part) -> str:
    if isinstance(part, str):
        return part
    if isinstance(part, dict):
        if part.get("type") in ("input_text", "output_text", "text") and isinstance(
            part.get("text"), str
        ):
            return part["text"]
    return ""


def message_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p for p in (part_text(x) for x in content) if p)
    return ""


def parse_transcript(path: str) -> tuple[list[str], list[str]]:
    users: list[str] = []
    assistants: list[str] = []
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(ev, dict) or ev.get("type") != "response_item":
                    continue
                payload = ev.get("payload") or {}
                if not isinstance(payload, dict) or payload.get("type") != "message":
                    continue
                role = payload.get("role")
                text = clean(message_text(payload.get("content") or ""))
                if not text:
                    continue
                if role == "user":
                    users.append(text)
                elif role == "assistant":
                    assistants.append(text)
    except OSError:
        pass
    return users, assistants


def main() -> int:
    raw = sys.stdin.buffer.read().decode("utf-8", "replace").strip()
    try:
        payload = json.loads(raw) if raw else {}
    except ValueError:
        payload = {}

    session_id = payload.get("session_id") or "unknown"
    cwd = payload.get("cwd") or os.getcwd()
    transcript_path = payload.get("transcript_path") or ""
    if not transcript_path or not os.path.isfile(transcript_path):
        return 0

    users, assistants = parse_transcript(transcript_path)
    if not users:
        return 0

    task = users[0][:TASK_MAX]
    outcome = assistants[-1][:OUTCOME_MAX] if assistants else ""
    fingerprint = hashlib.sha1((task + "|" + outcome).encode("utf-8")).hexdigest()

    state_file = os.path.join(STATE_DIR, session_id + ".json")
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(state_file, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        state = {}

    now_ms = int(time.time() * 1000)
    if (
        state.get("fingerprint") == fingerprint
        and now_ms - int(state.get("last_write_ms") or 0) < MIN_WRITE_INTERVAL_MS
    ):
        return 0

    lines = ["[codex session] task: " + (task or "(no task captured)")]
    lines.append("project: " + cwd)
    lines.append("turns: " + str(len(users)))
    if outcome:
        lines.append("outcome: " + outcome)
    content = "\n".join(lines)

    try:
        client = JevMemClient("codex")
        res = client.turn(
            {
                "session_id": "codex_" + session_id,
                "user_content": task,
                "assistant_content": content,
                "idempotency_key": "codex:" + session_id + ":"
                + fingerprint[:12],
                "metadata": {
                    "project_dir": cwd,
                    "source_agent": "codex",
                },
            }
        )
    except Exception:
        return 0
    if not (isinstance(res, dict) and res.get("ok")):
        return 0  # spooled client-side on failure

    state["fingerprint"] = fingerprint
    state["last_write_ms"] = now_ms
    try:
        with open(state_file, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
