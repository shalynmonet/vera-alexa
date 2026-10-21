"""AWS Bedrock conversation layer for Vera.

Lets the person talk to Vera naturally instead of only tapping tiles or
saying exact keywords. Amazon Nova Lite, through the Bedrock Converse API,
decides which Vera MCP tool (if any) to call; we execute it for real against
the running MCP server and feed the result back until Nova Lite has a short,
spoken-style reply.
"""
from __future__ import annotations

import os
import re

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from . import mcp_bridge

# Nova Lite doesn't always keep its reasoning in a separate channel -- it
# sometimes leaves a literal <thinking>...</thinking> preamble inside the
# final reply text, and sometimes wraps the actual reply in <response>
# tags. Strip/unwrap both so Vera never speaks her own reasoning or stray
# markup aloud.
_THINKING_RE = re.compile(r"<thinking>.*?</thinking>\s*", re.IGNORECASE | re.DOTALL)
_RESPONSE_WRAP_RE = re.compile(r"^\s*<response>(.*?)</response>\s*$", re.IGNORECASE | re.DOTALL)


def _clean_reply(text: str) -> str:
    text = _THINKING_RE.sub("", text).strip()
    wrapped = _RESPONSE_WRAP_RE.match(text)
    if wrapped:
        text = wrapped.group(1).strip()
    return text

REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
MODEL_ID = os.environ.get("VERA_BEDROCK_MODEL_ID", "us.amazon.nova-lite-v1:0")
DEFAULT_USER_ID = "demo"
MAX_TOOL_ROUNDS = 6

SYSTEM_PROMPT = (
    "You are Vera, a warm wellness companion for older adults, speaking through a "
    "voice assistant. Speak slowly, kindly, and in short, simple sentences -- one "
    "or two sentences per reply, since it will be read aloud and shown as a caption. "
    "Never shame missed days or make someone feel bad about their progress. "
    "Vera is shared by a household: each person has their own profile, already "
    "chosen on screen before you start chatting, so just use the person you're "
    "given -- don't ask who they are. "
    "Call list_sessions to see what's currently available: games (word recall "
    "memory game, matching pairs -- a visual flip-card game you can set up but "
    "can't see the board, so just describe it and let them play -- finish the "
    "saying, and word categories), exercise routines (chair stretch, seated "
    "strength, balance, gentle walking -- some may not have their video "
    "recorded yet, that's fine, the narration still works), and meditations. "
    "Always use your tools to actually do these things rather than just "
    "describing them -- for example, call start_memory_game instead of "
    "listing words yourself. When the person says they finished a guided "
    "stretch or meditation, call log_completion. For anything else they did "
    "on their own -- a walk, a bike or stationary bike ride, gardening, "
    "dancing, swimming, or any other activity, like 'I walked for 20 "
    "minutes' or 'I did half an hour of gardening' -- call log_activity "
    "instead, with your best guess at the minutes if they didn't say a "
    "number. If a tool result includes new_milestones, warmly celebrate "
    "each one by name."
)

_client = None


def _bedrock():
    global _client
    if _client is None:
        _client = boto3.client("bedrock-runtime", region_name=REGION)
    return _client


class ChatError(RuntimeError):
    pass


def _tool_spec(tool: dict) -> dict:
    schema = tool.get("input_schema") or {"type": "object", "properties": {}}
    return {
        "toolSpec": {
            "name": tool["name"],
            "description": tool.get("description") or tool["name"],
            "inputSchema": {"json": schema},
        }
    }


async def _tool_config() -> dict:
    tools = await mcp_bridge.list_tools()
    return {"tools": [_tool_spec(t) for t in tools]}


def _as_json_content(result) -> dict:
    return result if isinstance(result, dict) else {"value": result}


async def converse(message: str, history: list[dict], user_id: str = DEFAULT_USER_ID) -> dict:
    messages = list(history) + [{"role": "user", "content": [{"text": message}]}]
    tool_config = await _tool_config()
    tool_calls: list[dict] = []

    for _ in range(MAX_TOOL_ROUNDS):
        try:
            resp = _bedrock().converse(
                modelId=MODEL_ID,
                system=[{"text": SYSTEM_PROMPT}],
                messages=messages,
                toolConfig=tool_config,
                inferenceConfig={"maxTokens": 400, "temperature": 0.4},
            )
        except (ClientError, BotoCoreError) as e:
            raise ChatError(str(e)) from e

        output_message = resp["output"]["message"]
        messages.append(output_message)

        if resp.get("stopReason") != "tool_use":
            reply = "".join(b.get("text", "") for b in output_message["content"])
            reply = _clean_reply(reply)
            return {"reply": reply, "history": messages, "tool_calls": tool_calls}

        tool_results = []
        for block in output_message["content"]:
            use = block.get("toolUse")
            if not use:
                continue
            args = {**use.get("input", {}), "user_id": user_id}
            try:
                result = await mcp_bridge.call_tool(use["name"], args)
            except mcp_bridge.ToolError as e:
                result = {"error": str(e)}
            tool_calls.append({"name": use["name"], "args": args, "result": result})
            tool_results.append({
                "toolResult": {
                    "toolUseId": use["toolUseId"],
                    "content": [{"json": _as_json_content(result)}],
                }
            })
        messages.append({"role": "user", "content": tool_results})

    return {
        "reply": "Sorry, I got a little confused there. Could you say that again?",
        "history": messages,
        "tool_calls": tool_calls,
    }
