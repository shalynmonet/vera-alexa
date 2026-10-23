"""Polly playback (web/static/js/polly.js's speakPolly/stopPolly) is browser
JS with no server side to it, so this runs the real module under Node with
fakes for fetch/Audio/AudioContext rather than reimplementing its logic in
Python -- see polly_stop_check.mjs for the actual assertions. The bug this
guards: stopPolly() used to just .pause() the <audio> element, which never
fires onended, so the in-flight speakPolly() promise (and everything
awaiting it, e.g. say()'s cleanup that resets veraSpeaking) hung forever the
moment anything stopped her mid-sentence -- which a mic tap now does."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_polly_stop_resolves_in_flight_promise():
    if not shutil.which("node"):
        pytest.skip("Node.js isn't available in this environment")
    script = Path(__file__).parent / "polly_stop_check.mjs"
    result = subprocess.run(
        ["node", str(script)], cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "all checks passed" in result.stdout
