"""deploy/reset_demo.py -- the nightly reset for both no-code demo
profiles (Judge Demo and Rose). Runs it as a real subprocess (matching how
the systemd timer invokes it) against a scratch data file and a scratch
baseline directory, then reads the result back through vera.storage.Store
the way the MCP tools would."""
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from vera.storage import Store

ROOT = Path(__file__).resolve().parent.parent


def _run(data_path, baseline_dir, extra_env=None):
    env = {**os.environ, "VERA_DATA": str(data_path), "VERA_DEMO_BASELINE_DIR": str(baseline_dir), **(extra_env or {})}
    result = subprocess.run(
        [sys.executable, str(ROOT / "deploy" / "reset_demo.py")],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_reset_demo_creates_a_well_formed_judge_demo_profile(tmp_path):
    _run(tmp_path / "vera.json", tmp_path / "baselines")

    user = Store(tmp_path / "vera.json").get_user("judge_demo")
    assert user["name"] == "Judge Demo"
    assert len(user["activities"]) > 0
    assert len(user["family"]) == 1
    assert user["family"][0]["name"] == "Sam"
    assert user["cheers"] == []  # placeholder beep cheers were removed
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

    _run(data_path, tmp_path / "baselines")

    reset_user = Store(data_path).get_user("judge_demo")
    assert reset_user["name"] == "Judge Demo"
    assert not any(a["minutes"] == 999 for a in reset_user["activities"])


def test_reset_demo_respects_a_custom_demo_user_id(tmp_path):
    data_path = tmp_path / "vera.json"
    _run(data_path, tmp_path / "baselines", extra_env={"VERA_DEMO_USER_ID": "custom_demo_id"})
    user = Store(data_path).get_user("custom_demo_id")
    assert user["name"] == "Judge Demo"


# ---------- Rose: falls back to rose_demo_profile.json with no baseline ----------

def test_reset_demo_falls_back_to_rose_seed_with_no_baseline_saved(tmp_path):
    data_path = tmp_path / "vera.json"
    _run(data_path, tmp_path / "baselines")  # no baseline file written here

    user = Store(data_path).get_user("rose_demo")
    assert user["name"] == "Rose"
    assert len(user["family"]) == 1
    assert user["family"][0]["name"] == "Larry"  # renamed from Jake
    assert user["cheers"] == []  # placeholder beep cheers were removed
    assert len(user["memories"]) == 2

    from vera import progress
    streak = progress.streaks(user["activities"], date.today())
    assert streak["current"] == 6  # one session away from the 7 day streak


def test_reset_demo_respects_a_custom_rose_user_id(tmp_path):
    data_path = tmp_path / "vera.json"
    _run(data_path, tmp_path / "baselines", extra_env={"VERA_DEMO_ROSE_USER_ID": "custom_rose_id"})
    user = Store(data_path).get_user("custom_rose_id")
    assert user["name"] == "Rose"


# ---------- Rose: restores from a saved baseline when one exists ----------

def test_reset_demo_restores_rose_from_a_saved_baseline(tmp_path):
    data_path = tmp_path / "vera.json"
    baseline_dir = tmp_path / "baselines"
    baseline_dir.mkdir()
    snapshot = {
        "saved_at": "2026-10-20T09:00:00",
        "name": "Rose",
        "weekly_goal_days": 4,
        "activities": [
            {"type": "stretch", "days_ago": 2, "minutes": 8, "details": {}},
            {"type": "meditation", "days_ago": 1, "minutes": 3, "details": {}},
        ],
        "memories": [{"fact": "Loves jazz", "days_ago": 3, "category": "hobby"}],
        "family": [{
            "id": "fam-larry", "name": "Larry", "phone": "+15555550123", "nickname": None,
            "relationship": "Grandson", "email": None, "email_opt_in": False,
            "onboarded": True, "low_queue_notified_at": None, "token": "tok-larry",
        }],
        "cheers": [{
            "id": "cheer-1", "family_id": "fam-larry", "family_name": "Larry",
            "cheer_type": "anytime", "target": None, "media_type": "audio",
            "file": "a-real-recording.webm", "photo_file": None, "storage": "local",
            "duration_seconds": 6.5, "activities_at_recording": 10,
            "status": "unlocked", "days_ago_recorded": 4, "days_ago_played": None,
        }],
    }
    (baseline_dir / "rose.json").write_text(json.dumps(snapshot), encoding="utf-8")

    _run(data_path, baseline_dir)

    user = Store(data_path).get_user("rose_demo")
    assert user["name"] == "Rose"

    # Exact family/token preserved -- an already-shared record link keeps working.
    assert user["family"] == snapshot["family"]

    # Cheer restored with its real recording's filename untouched, and its
    # relative date re-anchored to today.
    assert len(user["cheers"]) == 1
    cheer = user["cheers"][0]
    assert cheer["file"] == "a-real-recording.webm"
    assert cheer["played_on"] is None
    assert cheer["recorded_on"] == (date.today() - timedelta(days=4)).isoformat()

    # Activity/memory dates re-anchored to today too.
    assert {a["date"] for a in user["activities"]} == {
        (date.today() - timedelta(days=2)).isoformat(),
        (date.today() - timedelta(days=1)).isoformat(),
    }
    assert user["memories"][0]["recorded_on"] == (date.today() - timedelta(days=3)).isoformat()


def test_reset_demo_baseline_restore_never_touches_cheer_media_on_disk(tmp_path):
    """The restored cheer just references a filename -- nothing about a
    reset should create, move, or delete anything under web/cheer_media/."""
    cheer_media_dir = ROOT / "web" / "cheer_media"
    before = set(cheer_media_dir.iterdir()) if cheer_media_dir.exists() else set()

    data_path = tmp_path / "vera.json"
    baseline_dir = tmp_path / "baselines"
    baseline_dir.mkdir()
    snapshot = {
        "saved_at": "now", "name": "Rose", "weekly_goal_days": 4, "activities": [], "memories": [],
        "family": [{"id": "f1", "name": "Larry", "phone": None, "nickname": None, "relationship": None,
                     "email": None, "email_opt_in": False, "onboarded": True, "low_queue_notified_at": None, "token": "t1"}],
        "cheers": [{"id": "c1", "family_id": "f1", "family_name": "Larry", "cheer_type": "anytime", "target": None,
                     "media_type": "audio", "file": "does-not-actually-exist.webm", "photo_file": None,
                     "storage": "local", "duration_seconds": 5, "activities_at_recording": 0,
                     "status": "unlocked", "days_ago_recorded": 1, "days_ago_played": None}],
    }
    (baseline_dir / "rose.json").write_text(json.dumps(snapshot), encoding="utf-8")

    _run(data_path, baseline_dir)

    after = set(cheer_media_dir.iterdir()) if cheer_media_dir.exists() else set()
    assert before == after
