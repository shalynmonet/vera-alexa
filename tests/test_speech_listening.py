"""Robust speech capture (web/static/js/speech.js's startListening) is
browser JS with no server side to it, so this runs the real module under
Node with a fake SpeechRecognition rather than reimplementing its logic in
Python -- see speech_listening_check.mjs for the actual assertions, which
cover accumulating across a forced browser restart, the silence-based
"she's done talking" timer resetting on each new word, and stop()/cancel()."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_speech_listening_logic():
    if not shutil.which("node"):
        pytest.skip("Node.js isn't available in this environment")
    script = Path(__file__).parent / "speech_listening_check.mjs"
    result = subprocess.run(
        ["node", str(script)], cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "all checks passed" in result.stdout
