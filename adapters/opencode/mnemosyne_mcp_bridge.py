"""Mnemosyne MCP bridge for OpenCode (mcp SDK 1.x) — JEV core backend (P4).

Serves MCP tools backed by the JEV memory core daemon (JevMemClient, HTTP +
spool) instead of the embedded mnemosyne path. Core failure degrades to
error responses; the client spools writes for later replay.

Keep the same tool names as the official bridge (mnemosyne_recall,
mnemosyne_remember) so existing opencode sessions keep working.
"""

import asyncio
import json
import os
import sys
from typing import Any

REPO = os.environ.get(
    "JEV_MEM_REPO",
    r"C:\Users\mandu\hermes-made\jev-memory-middleware",
)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolRequestParams, TextContent, Tool

from jev_mem_core.client import JevMemClient  # noqa: E402

TOOLS = [
    Tool(
        name="mnemosyne_recall",
        description=(
            "Search JEV memory (Mnemosyne) for context relevant to the user's "
            "question. Use this when the user asks about past work, decisions, "
            "preferences, or anything that may have been discussed before. "
            "Argument: query (string, required)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="mnemosyne_remember",
        description=(
            "Save a durable fact or preference to JEV memory (Mnemosyne). "
            "Use this for stable facts about the user or the project that "
            "should persist across sessions. Arguments: content (string, "
            "required), session_id (string, optional)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Memory content"},
                "session_id": {"type": "string", "description": "Session id"},
            },
            "required": ["content"],
        },
    ),
]

async def _call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
    args = arguments or {}
    try:
        client = JevMemClient("opencode")
        if name == "mnemosyne_recall":
            result = client.prefetch(
                str(args.get("query") or ""),
                session_id=str(args.get("session_id") or "opencode-mcp"),
                max_chars=4000,
                timeout_ms=2500,
            )
            text = result or json.dumps(
                {"status": "ok", "matches": []}, ensure_ascii=False
            )
        elif name == "mnemosyne_remember":
            content = str(args.get("content") or "")
            session_id = str(args.get("session_id") or "opencode-mcp")
            res = client.turn(
                {
                    "session_id": session_id,
                    "user_content": content[:200],
                    "assistant_content": content,
                    "metadata": {"source_agent": "opencode", "mcp": True},
                }
            )
            text = json.dumps(res, default=str, ensure_ascii=False)
        else:
            text = json.dumps(
                {"status": "error", "message": f"unknown tool: {name}"},
                ensure_ascii=False,
            )
    except Exception as exc:
        text = json.dumps(
            {"status": "error", "message": str(exc)}, ensure_ascii=False
        )
    return [TextContent(type="text", text=text)]

async def _main() -> None:
    from mcp.types import CallToolResult, ListToolsResult

    async def _on_list(ctx, params):
        return ListToolsResult(tools=TOOLS)

    async def _on_call(ctx, params: CallToolRequestParams) -> CallToolResult:
        content = await _call_tool(params.name, params.arguments or {})
        return CallToolResult(content=content)

    server = Server(
        "mnemosyne",
        version="0.2.0",
        on_list_tools=_on_list,
        on_call_tool=_on_call,
    )
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(_main())
