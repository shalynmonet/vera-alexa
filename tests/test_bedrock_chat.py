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
