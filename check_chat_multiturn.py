"""Replays (and extends) the bug transcript from the "games must stay in
Chat" report through the real Nova Pro chat loop (AWS Bedrock, via
web/bedrock_chat.py) and prints what actually happened -- not an automated
pass/fail check (Nova's replies aren't deterministic enough for that), but
a human-readable report for confirming the fix live, the same way the bug
was first noticed. See check_activity_phrases.py for the same pattern
applied to the stated-intent guard.

What this looks for, turn by turn:
  1) "I'm down for a memory game" -> a start_memory_game tool call. Whether
     the game then stays on the Chat screen instead of navigating away is a
     client-side rendering choice (web/static/js/main.js's
     handleBedrockToolCalls), not something this server-side script can see
     -- that part is covered by live browser testing instead.
  2-4) The three follow-up lines from the original transcript -- asking
     about other games, insisting on staying in the game with Vera rather
     than switching to a board game alone, and asking about games playable
     by talking with someone else. None of these should ever throw (a
     thrown ChatError is exactly what used to fall through to the Chat
     screen's old keyword-fallback message -- now impossible by
     construction, since that fallback path was removed for Chat, but a
     thrown error here would still mean Chat's new retry-then-apologize
     path had to kick in for real, which is itself worth seeing).
  5-8) A short 20 Questions round, ending with the person confirming the
     answer and saying they're done -- looking for a log_chat_game call
     among the tool calls by the end.

Needs the Vera MCP server already running (python server.py) and AWS
credentials with bedrock:InvokeModel, since this calls Nova Pro for real.

Run:  python check_chat_multiturn.py
"""
import asyncio
import sys

from web import bedrock_chat, mcp_bridge

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

USER_ID = "chat_multiturn_check"

TRANSCRIPT = [
    "I'm down for a memory game",
    "do you know any games other than the ones that are already in the games card on this app",
    "no I still want to play the game with you, I just want a new game that isn't under the games card",
    "no so do you know of any games that you can play just by talking if I did want to play with someone else",
    "let's play 20 questions, I'm thinking of an animal",
    "yes",
    "no",
    "yes that's right, it's an elephant! that was fun, let's stop there",
]


async def main():
    try:
        await mcp_bridge.call_tool("set_profile", {"name": "Transcript Test", "user_id": USER_ID})
    except mcp_bridge.ToolError as e:
        print(f"Couldn't reach the Vera MCP server -- is it running? ({e})")
        return

    history = []
    all_tool_calls = []
    any_error = False
    for turn in TRANSCRIPT:
        print(f'R: "{turn}"')
        try:
            result = await bedrock_chat.converse(turn, history, USER_ID)
        except bedrock_chat.ChatError as e:
            any_error = True
            print(f"    ERROR from Nova: {e}")
            print('    (this is exactly what would have shown Chat\'s old "I heard ..." '
                  "fallback -- now it gets one retry, then a short apology instead)")
            print()
            continue
        history = result["history"]
        print(f"V: {result['reply']!r}")
        for tc in result["tool_calls"]:
            all_tool_calls.append(tc["name"])
            outcome = "error: " + tc["result"]["error"] if isinstance(tc["result"], dict) and tc["result"].get("error") else "ok"
            print(f"    [tool call] {tc['name']}({tc['args']}) -> {outcome}")
        print()

    print("=== Summary ===")
    print(f"Any Nova error (would have triggered the old fallback message): {any_error}")
    print(f"Tool calls made across the conversation: {all_tool_calls}")
    print(f"start_memory_game called (turn 1 should stay a game, not become a refusal): {'start_memory_game' in all_tool_calls}")
    print(f"log_chat_game called (the finished 20 Questions round should get logged): {'log_chat_game' in all_tool_calls}")


if __name__ == "__main__":
    asyncio.run(main())
