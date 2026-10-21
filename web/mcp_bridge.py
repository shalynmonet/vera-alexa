"""Thin async bridge from the web app to the Vera MCP server.

Opens a fresh Streamable HTTP MCP session per call. Vera's server runs
stateless_http=True, so there is no session affinity to preserve, and a
short-lived client keeps the web app simple (no background connection to
babysit or reconnect).
"""
from __future__ import annotations

import json
import os
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

VERA_MCP_URL = os.environ.get("VERA_MCP_URL", "http://127.0.0.1:8000/mcp")


class ToolError(RuntimeError):
    pass


def _unwrap(result: Any) -> Any:
    if getattr(result, "isError", False):
        text = result.content[0].text if result.content else "Unknown MCP error"
        raise ToolError(text)
    if not result.content:
        return None
    text = result.content[0].text
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


async def call_tool(name: str, arguments: dict[str, Any] | None = None) -> Any:
    # _unwrap can raise ToolError for an app-level tool error (including a
    # schema validation failure, like a missing required argument) -- that
    # raise happens *after* both `async with` blocks below have exited
    # cleanly, not while they're unwinding. Raising from inside them would
    # let anyio's task group re-wrap a plain ToolError as an
    # ExceptionGroup, which `except mcp_bridge.ToolError` in bedrock_chat.py
    # then fails to catch, crashing the whole chat turn instead of letting
    # Nova see the error and respond to it.
    async with streamable_http_client(VERA_MCP_URL) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments or {})
    return _unwrap(result)


async def list_tools() -> list[dict[str, Any]]:
    async with streamable_http_client(VERA_MCP_URL) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            return [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "input_schema": t.inputSchema,
                }
                for t in tools
            ]
