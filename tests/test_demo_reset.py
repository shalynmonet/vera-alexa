"""deploy/reset_demo.py -- the nightly reset for the no-code judge demo
profile. Runs it as a real subprocess (matching how the systemd timer
invokes it) against a scratch data file, then reads the result back
through vera.storage.Store the way the MCP tools would."""
import os
import subprocess
import sys
from pathlib import Path

from vera.storage import Store

ROOT = Path(__file__).resolve().parent.parent


def test_reset_demo_creates_a_well_formed_judge_demo_profile(tmp_path):
    data_path = tmp_path / "vera.json"
    result = subprocess.run(
        [sys.executable, str(ROOT / "deploy" / "reset_demo.py")],
        cwd=ROOT, env={**os.environ, "VERA_DATA": str(data_path)},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    store = Store(data_path)
    user = store.get_user("judge_demo")
    assert user["name"] == "Judge Demo"
    assert len(user["activities"]) > 0
    assert len(user["family"]) == 1
    assert user["family"][0]["name"] == "Sam"
    assert len(user["cheers"]) == 4
    assert all(c["family_id"] == user["family"][0]["id"] for c in user["cheers"])
    assert len(user["memories"]) == 2
    assert len(user["milestones"]) > 0  # the seeded activity history should earn at least one badge


def test_reset_demo_fully_replaces_prior_state(tmp_path):
    """A judge's session (an extra logged activity, a renamed profile --
    anything) must not survive a reset; save_user() is a full overwrite,
    and this is the one place that matters most."""
    data_path = tmp_path / "vera.json"
    store = Store(data_path)
    leftover = store.get_user("judge_demo")
    leftover["name"] = "Something a judge typed"
    leftover["activities"].append({"type": "walk", "date": "2020-01-01", "minutes": 999, "details": {}})
    store.save_user(leftover)

    result = subprocess.run(
        [sys.executable, str(ROOT / "deploy" / "reset_demo.py")],
        cwd=ROOT, env={**os.environ, "VERA_DATA": str(data_path)},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    reset_user = Store(data_path).get_user("judge_demo")
    assert reset_user["name"] == "Judge Demo"
    assert not any(a["minutes"] == 999 for a in reset_user["activities"])


def test_reset_demo_respects_a_custom_demo_user_id(tmp_path):
    data_path = tmp_path / "vera.json"
    result = subprocess.run(
        [sys.executable, str(ROOT / "deploy" / "reset_demo.py")],
        cwd=ROOT,
        env={**os.environ, "VERA_DATA": str(data_path), "VERA_DEMO_USER_ID": "custom_demo_id"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    user = Store(data_path).get_user("custom_demo_id")
    assert user["name"] == "Judge Demo"
