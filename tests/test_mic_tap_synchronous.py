"""Regression guard for the "mic bounces but never actually records"
iOS Safari bug: SpeechRecognition.start() only actually engages the
microphone when it runs synchronously inside the tap's own event handler.
captureSpeech() used to `await veraSpeakingDone` (waiting for Vera to
finish talking) before calling startListening() -- that await drops
.start() out of the gesture, so on iOS the mic UI still shows "listening"
(its CSS animation has no idea anything's wrong) but no audio is ever
actually captured. Reading the real source rather than re-implementing
main.js's heavy DOM/module wiring in a test harness, which captureSpeech()
is tightly coupled to."""
import re
from pathlib import Path

MAIN_JS = Path(__file__).resolve().parent.parent / "web" / "static" / "js" / "main.js"


def _strip_line_comments(js: str) -> str:
    """Good enough for this one function body: drops '// ...' comments so
    a stray mention of the word "await" in prose (like this file's own
    commentary) can't produce a false positive."""
    return re.sub(r"//.*", "", js)


def test_capture_speech_calls_start_listening_with_no_await_in_between():
    src = MAIN_JS.read_text(encoding="utf-8")
    start = src.index("async function captureSpeech()")
    call_at = src.index("startListening(", start)
    body = _strip_line_comments(src[start:call_at])

    # The one await that's fine: speechRecognitionSupported() being false
    # awaits say() and then returns -- a different code path entirely,
    # not an await sitting in front of the listening UI/startListening().
    not_supported_branch = re.search(r"if \(!speechRecognitionSupported\(\)\) \{.*?\n  \}\n", body, re.DOTALL)
    assert not_supported_branch, "expected to find the speechRecognitionSupported() early-return branch"
    body_on_the_path_to_start_listening = body[:not_supported_branch.start()] + body[not_supported_branch.end():]

    assert "await" not in body_on_the_path_to_start_listening, (
        "captureSpeech() must not await anything between the mic tap and "
        "calling startListening() -- doing so (e.g. awaiting Vera "
        "finishing her sentence first) breaks iOS Safari's requirement "
        "that SpeechRecognition.start() run synchronously inside the "
        "user gesture, so the mic silently stops capturing any audio "
        "even though its 'listening' UI still shows normally"
    )
