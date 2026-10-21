import asyncio

from web import bedrock_chat
from web.bedrock_chat import _clean_reply


def test_strips_leading_thinking_block():
    text = "<thinking>I should log this.</thinking>\nNice work, Rose!"
    assert _clean_reply(text) == "Nice work, Rose!"


def test_unwraps_response_tag():
    text = "<response>Nice work, Rose!</response>"
    assert _clean_reply(text) == "Nice work, Rose!"


def test_strips_thinking_then_unwraps_response():
    text = "<thinking>Reasoning here.</thinking>\n<response>Nice work, Rose!</response>"
    assert _clean_reply(text) == "Nice work, Rose!"


def test_plain_reply_unchanged():
    assert _clean_reply("Nice work, Rose!") == "Nice work, Rose!"


def test_greet_sends_kickoff_message_with_empty_history(monkeypatch):
    captured = {}

    async def fake_converse(message, history, user_id):
        captured["message"] = message
        captured["history"] = history
        captured["user_id"] = user_id
        return {"reply": "Good morning!", "history": [], "tool_calls": []}

    monkeypatch.setattr(bedrock_chat, "converse", fake_converse)
    result = asyncio.run(bedrock_chat.greet("rose"))

    assert captured["message"] == bedrock_chat.GREETING_KICKOFF
    assert captured["history"] == []
    assert captured["user_id"] == "rose"
    assert result["reply"] == "Good morning!"
