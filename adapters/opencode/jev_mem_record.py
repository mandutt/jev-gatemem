"""Write a turn to JEV core (P4, replaces mnemosyne_record.py).

One-shot helper spawned by the opencode auto-record plugin
(plugin/mnemosyne-session-memory.ts). Uses the JevMemClient (core HTTP +
spool) instead of the embedded-mnemosyne write path, so records land via
the core's 4-way gate and single-writer.
"""

import argparse
import json
import os
import sys

REPO = os.environ.get(
    "JEV_MEM_REPO",
    r"C:\Users\mandu\hermes-made\jev-memory-middleware",
)
if REPO not in sys.path:
    sys.path.insert(0, REPO)


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a turn to JEV core.")
    parser.add_argument("--content", required=True, help="Memory content")
    parser.add_argument("--scope", default="session", choices=["session", "global"])
    parser.add_argument("--importance", type=float, default=0.6)
    parser.add_argument("--source", default="opencode")
    parser.add_argument("--metadata", default="{}", help="JSON object string")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--turn-seq", type=int, default=None)
    args = parser.parse_args()

    try:
        metadata = json.loads(args.metadata)
        if not isinstance(metadata, dict):
            raise ValueError("--metadata must be a JSON object")
    except Exception as exc:
        print(json.dumps({"ok": False, "status": "error",
                          "message": f"bad metadata: {exc}"}))
        return 1

    from jev_mem_core.client import JevMemClient

    sid = args.session_id or "opencode-unknown"
    payload = {
        "session_id": sid,
        "user_content": args.content[:200],
        "assistant_content": args.content,
        "metadata": dict(metadata, source_agent="opencode"),
    }
    if args.turn_seq is not None:
        payload["turn_seq"] = args.turn_seq
    try:
        result = JevMemClient("opencode").turn(payload)
    except Exception as exc:
        print(json.dumps({"ok": False, "status": "error", "message": str(exc)}))
        return 1

    print(json.dumps(result, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())