"""Pure unit tests for the cheer locked/unlocked transition rules --
server._initial_cheer_status and server._unlock_cheers -- independent of
the live MCP server, so these stay fast and never touch the network."""
from server import _initial_cheer_status, _unlock_cheers


def _user(milestones=(), activities=(), cheers=()):
    return {
        "milestones": [{"id": m} for m in milestones],
        "activities": list(activities),
        "cheers": list(cheers),
    }


def test_milestone_cheer_starts_unlocked_if_already_earned():
    u = _user(milestones=["streak_7"])
    assert _initial_cheer_status(u, "milestone", "streak_7") == "unlocked"
    assert _initial_cheer_status(u, "milestone", "streak_3") == "locked"


def test_activity_cheer_starts_unlocked_if_already_logged():
    u = _user(activities=[{"type": "walk"}])
    assert _initial_cheer_status(u, "activity", "walk") == "unlocked"
    assert _initial_cheer_status(u, "activity", "bike") == "locked"


def test_anytime_cheer_always_starts_locked():
    u = _user(activities=[{"type": "walk"}])
    assert _initial_cheer_status(u, "anytime", None) == "locked"


def test_unlock_milestone_cheer_on_newly_earned_milestone():
    u = _user(cheers=[{"cheer_type": "milestone", "target": "streak_7", "status": "locked"}])
    _unlock_cheers(u, {"streak_7"}, "walk")
    assert u["cheers"][0]["status"] == "unlocked"


def test_unlock_activity_cheer_on_matching_logged_type():
    u = _user(cheers=[{"cheer_type": "activity", "target": "bike", "status": "locked"}])
    _unlock_cheers(u, set(), "walk")
    assert u["cheers"][0]["status"] == "locked"  # wrong activity type -- stays locked
    _unlock_cheers(u, set(), "bike")
    assert u["cheers"][0]["status"] == "unlocked"


def test_unlock_anytime_cheer_on_next_activity_after_recording():
    u = _user(activities=[{"type": "walk"}], cheers=[{"cheer_type": "anytime", "target": None, "status": "locked", "activities_at_recording": 1}])
    _unlock_cheers(u, set(), "walk")  # still only 1 activity logged (the one already counted) -- no new one yet
    assert u["cheers"][0]["status"] == "locked"
    u["activities"].append({"type": "stretch"})
    _unlock_cheers(u, set(), "stretch")
    assert u["cheers"][0]["status"] == "unlocked"


def test_already_unlocked_or_played_cheers_are_left_alone():
    u = _user(cheers=[
        {"cheer_type": "milestone", "target": "streak_7", "status": "unlocked"},
        {"cheer_type": "milestone", "target": "streak_7", "status": "played"},
    ])
    _unlock_cheers(u, {"streak_7"}, "walk")
    assert u["cheers"][0]["status"] == "unlocked"
    assert u["cheers"][1]["status"] == "played"
