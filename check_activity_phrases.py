"""Sends the exact phrases from the "stated intent got logged as done" bug
report through the real Nova chat loop (AWS Bedrock, via web/bedrock_chat.py)
and reports what actually happened -- not an automated pass/fail check (Nova's
replies aren't deterministic enough for that), but a human-readable report
for confirming the fix live, the same way the bug was first noticed.

Needs the Vera MCP server already running (python server.py) and AWS
credentials with bedrock:InvokeModel, since this calls Nova Pro for real.

Run:  python check_activity_phrases.py
"""
import asyncio
import sys

from web import bedrock_chat, mcp_bridge

# Windows consoles default to a legacy codepage that can't encode emoji Nova
# sometimes includes in a reply -- reconfigure stdout to UTF-8 so a reply
# never crashes the report.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

USER_ID = "phrase_check"

PHRASES = {
    "Should NOT log (stated intent)": [
        "yes I will walk today, that sounds good",
        "I'm going to ride my bike later",
        "maybe I'll do a meditation tonight",
        "that sounds nice",
    ],
    "Should log (clearly already done)": [
        "I walked for 20 minutes",
        "just got back from a 15 minute walk",
        "I did my bike ride this morning, about 30 minutes",
    ],
    "Should ask for minutes (done, but no number given)": [
        "I went for a walk",
    ],
}

LOGGING_TOOLS = {"log_activity", "log_completion"}


async def check_phrase(phrase: str) -> None:
    try:
        result = await bedrock_chat.converse(phrase, [], USER_ID)
    except bedrock_chat.ChatError as e:
        print(f"    ERROR calling Bedrock: {e}")
        return

    logging_calls = [tc for tc in result["tool_calls"] if tc["name"] in LOGGING_TOOLS]
    plan_calls = [tc for tc in result["tool_calls"] if tc["name"] == "plan_activity"]

    if not logging_calls and not plan_calls:
        verdict = "did not log or plan anything -- likely asked a question or just replied"
    else:
        parts = []
        for tc in logging_calls:
            outcome = "REFUSED by the guard" if "error" in tc["result"] else "LOGGED"
            minutes = tc["args"].get("minutes")
            statement = tc["args"].get("user_statement")
            parts.append(f"{tc['name']}(minutes={minutes!r}, user_statement={statement!r}) -> {outcome}")
        for tc in plan_calls:
            parts.append(f"plan_activity(activity={tc['args'].get('activity')!r}, when={tc['args'].get('when')!r})")
        verdict = "; ".join(parts)

    print(f'  "{phrase}"')
    print(f"    tools: {verdict}")
    print(f"    reply: {result['reply']!r}")
    print()


async def main():
    try:
        await mcp_bridge.call_tool("set_profile", {"name": "Phrase Test", "user_id": USER_ID})
    except mcp_bridge.ToolError as e:
        print(f"Couldn't reach the Vera MCP server -- is it running? ({e})")
        return

    for group, phrases in PHRASES.items():
        print(f"=== {group} ===")
        for phrase in phrases:
            await check_phrase(phrase)


if __name__ == "__main__":
    asyncio.run(main())
