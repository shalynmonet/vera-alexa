import asyncio

from web import bedrock_chat
from web.bedrock_chat import _clean_reply

PROMPT = bedrock_chat.SYSTEM_PROMPT.lower()


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


# ---------- Chat screen guardrails ----------
# These can't call the real model in a test (no AWS), so they check the
# instructions the model is actually given -- the same thing a human
# reviewer would check before trusting an elder-care assistant with these
# situations. Live wording changes are fine; losing the underlying
# instruction entirely is the regression this guards against.

def test_never_gives_medical_advice():
    assert "medical advice" in PROMPT
    assert "diagnos" in PROMPT  # "a diagnosis" / "diagnose"
    assert "doctor" in PROMPT


def test_emergency_sends_to_911_not_handled_in_chat():
    assert "911" in PROMPT
    assert "emergency button" in PROMPT
    assert "chest pain" in PROMPT
    assert "trouble breathing" in PROMPT


def test_loneliness_offers_to_reach_family():
    assert "sad, lonely, or down" in PROMPT
    assert "next_cheer" in PROMPT


def test_never_asks_for_money_or_private_info_and_warns_of_scams():
    assert "a password" in PROMPT
    assert "social security" in PROMPT
    assert "bank or card number" in PROMPT
    assert "scam" in PROMPT


def test_reminiscence_asks_one_question_at_a_time_and_saves_facts():
    assert "one gentle, open-ended question at a time" in PROMPT
    assert "remember_fact" in PROMPT


def test_whats_next_uses_progress_then_falls_back_to_discovery_questions():
    assert "get_fitness_log" in PROMPT
    assert "get_planned_activities" in PROMPT
    assert "discovery questions" in PROMPT
