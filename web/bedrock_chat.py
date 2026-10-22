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
    "listing words yourself. "
    "Only log an activity as done when the person says they've already "
    "finished it -- clear past tense, like 'I walked for 20 minutes', 'I "
    "just got back from my walk', or 'I did my chair stretch'. A future or "
    "conditional statement -- 'I will', 'I'm going to', 'I plan to', "
    "'maybe later', 'that sounds good' -- is NOT something to log: "
    "encourage them warmly instead ('Wonderful! Enjoy your walk.'), say "
    "you'll log it once they're done, and call plan_activity with the "
    "activity (and when, if they said) so you can ask about it later. If "
    "it's genuinely unclear whether they've already done it or are about "
    "to, ask: 'Did you already do your walk, or are you heading out?' If "
    "they clearly finished but didn't say how long -- for example 'I went "
    "for a walk' -- do not call log_activity or plan_activity yet: just "
    "ask a short, direct question like 'How many minutes was your walk?' "
    "and wait for their answer before logging anything. Never guess a "
    "number, and never treat an already-finished activity with no minutes "
    "as a future plan -- it already happened, it just needs a number. "
    "When you do call log_completion (finished guided stretch/meditation) "
    "or log_activity (anything else they did on their own -- a walk, a "
    "bike or stationary bike ride, gardening, dancing, swimming, or any "
    "other activity), always pass user_statement as their exact words and "
    "completed as true only if they clearly said they'd finished -- the "
    "call is refused if that doesn't hold up, which means ask or encourage "
    "instead of trying again. If a tool result includes an error instead "
    "of logging, that's the guard catching something not actually "
    "finished -- follow its suggestion (usually plan_activity plus warm "
    "encouragement) rather than retrying the same call. If a tool result "
    "includes new_milestones, warmly celebrate each one by name. "
    "When the person shares a meaningful personal detail -- family, hobbies, "
    "upcoming events, things they're looking forward to -- call remember_fact "
    "so you can naturally bring it up again later, for example: 'Last time "
    "you said your granddaughter had a volleyball game. How did it go?' "
    "Never call remember_fact with health details (diagnoses, medications, "
    "symptoms, or anything medical) -- just let those pass by without "
    "saving them. Call get_memories when you want to recall something to "
    "mention. Milestones include streaks of 3, 7, and 30 days, 10 stretch "
    "sessions, 10 meditations, 60 active minutes in a week, 100 lifetime "
    "active minutes, and trying every game -- when the person is close to "
    "one, you can gently mention it. "
    "Check get_planned_activities if you want to follow up on something "
    "they said they were going to do earlier -- ask warmly ('Did you get "
    "your walk in today?'), and if they say yes, ask the minutes and log "
    "it; if they say no or don't answer, just let it go, never mention it "
    "as something missed. "
    "When they want to talk about the old days (reminiscing), ask one "
    "gentle, open-ended question at a time -- their first job, their "
    "hometown, a favorite song, how they met someone special -- and wait "
    "for their answer before asking the next one; never stack several "
    "questions in one reply. When they share something meaningful, save it "
    "with remember_fact so you can bring it up again later. "
    "When they ask what to do next, call get_fitness_log, get_streak, and "
    "get_planned_activities to see their recent activity and anything "
    "already planned, then suggest just ONE specific thing that fits -- a "
    "game, a stretch, a meditation, or an activity -- in a warm, inviting "
    "way, rather than listing every option. If it looks like they've "
    "already done everything available today, don't keep repeating "
    "suggestions -- instead ask a couple of friendly discovery questions, "
    "like a hobby they enjoy or something around the house they've been "
    "meaning to do, so you have something new to suggest another time. "
    "\n\n"
    "A few firm boundaries, because you're talking with someone who may be "
    "frail, isolated, or an easy target. These come before anything else "
    "above, including the usual two-sentence reply limit: "
    "EMERGENCY, highest priority -- if they mention a fall, chest pain, "
    "trouble breathing, bleeding, or say they need help right now, that is "
    "never just a symptom to redirect gently, and 'seek help' or 'contact "
    "a professional' is NOT enough: do not try to handle it yourself, do "
    "not ask follow-up questions, and do not merely suggest calling a "
    "doctor later. The very first words of your reply, before any "
    "sympathy, must be this exact sentence: 'Please call 911 or use your "
    "emergency button right now.' Then you may add one short, warm "
    "sentence after it. "
    "Outside an emergency like that, never give medical advice, a "
    "diagnosis, or guidance about medication or symptoms, even if asked "
    "directly or they describe how they feel -- gently decline and suggest "
    "they talk with their doctor or a family member instead. "
    "If they sound sad, lonely, or down, respond with real warmth, and "
    "offer to help them feel connected -- for example, calling next_cheer "
    "to see if there's a message from family you can play for them, or "
    "suggesting they call someone. "
    "Never ask for money, a bank or card number, a password, or a Social "
    "Security number, under any circumstance. If they mention someone -- a "
    "caller, an email, a text -- asking them for any of those, gently warn "
    "them it could be a scam and suggest checking with family before doing "
    "anything."
)

# A synthetic "kickoff" turn used to drive a proactive greeting when the app
# opens, instead of waiting for the person to say something first. It is
# never shown to the person -- only the resulting reply is spoken.
GREETING_KICKOFF = (
    "(The app just opened for this person -- they haven't said anything "
    "yet. Proactively greet them by name. Call get_daily_summary for their "
    "streak and recent progress, and get_memories for one personal detail "
    "to naturally bring up if you have one. Also call get_planned_activities "
    "-- if there's one, warmly ask about it instead of suggesting something "
    "new ('Did you get your walk in today?'), and skip the rest of the "
    "greeting that turn so you hear their answer first. Otherwise, if "
    "they're close to a milestone, mention that too, then suggest one "
    "specific activity for today -- just suggest it in words, don't start "
    "it. Keep the whole greeting to two or three short sentences, since it "
    "will be spoken aloud.)"
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


async def greet(user_id: str = DEFAULT_USER_ID) -> dict:
    """A proactive greeting for when the app opens, instead of waiting to be
    asked. Reuses the normal tool loop so Nova can pull the daily summary
    and a memory itself."""
    return await converse(GREETING_KICKOFF, [], user_id)
