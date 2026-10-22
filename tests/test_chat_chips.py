"""The Chat screen's starter-chip personalization (web/static/js/chat-chips.js)
is plain browser JS with no DOM dependency, so this runs the real module
under Node rather than reimplementing its logic in Python -- see
chat_chips_check.mjs for the actual assertions."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_chat_chip_personalization_logic():
    if not shutil.which("node"):
        pytest.skip("Node.js isn't available in this environment")
    script = Path(__file__).parent / "chat_chips_check.mjs"
    result = subprocess.run(
        ["node", str(script)], cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "all checks passed" in result.stdout
