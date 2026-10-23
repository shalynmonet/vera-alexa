"""Pure unit tests for the cheer locked/unlocked/played transition rules
-- server._initial_cheer_status, server._unlock_cheers,
server._fire_occasion_cheer, and server._migrate_legacy_cheer_occasions --
independent of the live MCP server, so these stay fast and never touch the
network."""
from server import (
    MAX_CHEERS_PER_DAY,
    _fire_occasion_cheer,
    _initial_cheer_status,
    _migrate_legacy_cheer_occasions,
    _unlock_cheers,
)
from datetime import date


def _user(milestones=(), activities=(), cheers=(), family=()):
    return {
        "milestones": [{"id": m} for m in milestones],
        "activities": list(activities),
        "cheers": [dict(c) for c in cheers],
        "family": [dict(m) for m in family],
    }


def _cheer(cheer_type, target=None, status="locked", recorded_on="2026-01-01", **extra):
    return {
        "cheer_type": cheer_type, "target": target, "status": status,
        "recorded_on": recorded_on, "played_on": None, "family_id": "fam1", "family_name": "Larry",
        **extra,
    }


# ---------- _initial_cheer_status: nothing but a milestone can start
# unlocked, and only because it was already earned ----------

def test_milestone_cheer_starts_unlocked_if_already_earned():
    u = _user(milestones=["streak_7"])
    assert _initial_cheer_status(u, "milestone", "streak_7") == "unlocked"
    assert _initial_cheer_status(u, "milestone", "streak_3") == "locked"


def test_before_session_cheer_always_starts_locked_even_with_matching_history():
    """The actual bug: a demo profile with weeks of meditation history
    used to make a freshly-recorded "Enjoy your meditation" cheer start
    unlocked (as cheer_type "activity"), so it played on the very next app
    open instead of waiting for an actual meditation to start."""
    u = _user(activities=[{"type": "meditation"}, {"type": "meditation"}])
    assert _initial_cheer_status(u, "before_session", "meditation") == "locked"


def test_before_activity_cheer_always_starts_locked_even_with_matching_history():
    u = _user(activities=[{"type": "walk"}, {"type": "walk"}])
    assert _initial_cheer_status(u, "before_activity", "walk") == "locked"


def test_after_game_cheer_always_starts_locked():
    u = _user(activities=[{"type": "memory_game"}])
    assert _initial_cheer_status(u, "after_game", None) == "locked"


def test_anytime_cheer_always_starts_locked():
    u = _user(activities=[{"type": "walk"}])
    assert _initial_cheer_status(u, "anytime", None) == "locked"


# ---------- _unlock_cheers: only milestone and anytime unlock through the
# generic per-activity-log sweep ----------

def test_unlock_milestone_cheer_on_newly_earned_milestone():
    u = _user(cheers=[_cheer("milestone", "streak_7")])
    _unlock_cheers(u, {"streak_7"}, "walk")
    assert u["cheers"][0]["status"] == "unlocked"


def test_unlock_cheers_never_touches_before_session_before_activity_or_after_game():
    u = _user(cheers=[
        _cheer("before_session", "meditation"),
        _cheer("before_activity", "walk"),
        _cheer("after_game"),
    ])
    _unlock_cheers(u, set(), "meditation")
    _unlock_cheers(u, set(), "walk")
    assert all(c["status"] == "locked" for c in u["cheers"])


def test_unlock_anytime_cheer_on_next_activity_after_recording():
    u = _user(activities=[{"type": "walk"}], cheers=[_cheer("anytime", None, activities_at_recording=1)])
    _unlock_cheers(u, set(), "walk")  # still only 1 activity logged (the one already counted) -- no new one yet
    assert u["cheers"][0]["status"] == "locked"
    u["activities"].append({"type": "stretch"})
    _unlock_cheers(u, set(), "stretch")
    assert u["cheers"][0]["status"] == "unlocked"


def test_already_unlocked_or_played_cheers_are_left_alone():
    u = _user(cheers=[
        _cheer("milestone", "streak_7", status="unlocked"),
        _cheer("milestone", "streak_7", status="played"),
    ])
    _unlock_cheers(u, {"streak_7"}, "walk")
    assert u["cheers"][0]["status"] == "unlocked"
    assert u["cheers"][1]["status"] == "played"


# ---------- _fire_occasion_cheer: the atomic locked -> played transition
# for before_session / before_activity / after_game ----------

def test_fire_occasion_cheer_unlocks_and_plays_a_matching_cheer():
    u = _user(cheers=[_cheer("before_session", "meditation")])
    cheer = _fire_occasion_cheer(u, date(2026, 1, 5), "before_session", "meditation")
    assert cheer is not None
    assert cheer["status"] == "played"
    assert cheer["played_on"] == "2026-01-05"


def test_fire_occasion_cheer_ignores_a_different_target():
    u = _user(cheers=[_cheer("before_session", "stretch")])
    assert _fire_occasion_cheer(u, date(2026, 1, 5), "before_session", "meditation") is None
    assert u["cheers"][0]["status"] == "locked"


def test_fire_occasion_cheer_matches_a_wildcard_target_cheer():
    """A "record my own" cheer recorded generically for "before a walk or
    ride" (no specific target) fires for either."""
    u = _user(cheers=[_cheer("before_activity", None)])
    assert _fire_occasion_cheer(u, date(2026, 1, 5), "before_activity", "bike") is not None


def test_fire_occasion_cheer_ignores_a_different_cheer_type():
    u = _user(cheers=[_cheer("anytime", None)])
    assert _fire_occasion_cheer(u, date(2026, 1, 5), "after_game", None) is None


def test_fire_occasion_cheer_never_fires_an_already_played_or_unlocked_cheer():
    u = _user(cheers=[
        _cheer("after_game", status="unlocked"),
        _cheer("after_game", status="played", played_on="2026-01-01"),
    ])
    assert _fire_occasion_cheer(u, date(2026, 1, 5), "after_game", None) is None


def test_fire_occasion_cheer_picks_the_oldest_recorded_match():
    u = _user(cheers=[
        _cheer("after_game", recorded_on="2026-01-03", family_name="Second"),
        _cheer("after_game", recorded_on="2026-01-01", family_name="First"),
    ])
    cheer = _fire_occasion_cheer(u, date(2026, 1, 5), "after_game", None)
    assert cheer["family_name"] == "First"


def test_fire_occasion_cheer_respects_the_daily_cap_and_leaves_the_cheer_locked():
    """If the cap's already reached, the cheer must NOT leak out as
    unlocked -- it stays locked entirely and gets another chance the next
    time this occasion happens, never surfacing via a generic pickup."""
    played = [_cheer("anytime", status="played", played_on="2026-01-05") for _ in range(MAX_CHEERS_PER_DAY)]
    u = _user(cheers=[*played, _cheer("after_game")])
    assert _fire_occasion_cheer(u, date(2026, 1, 5), "after_game", None) is None
    assert u["cheers"][-1]["status"] == "locked"


# ---------- _migrate_legacy_cheer_occasions: self-heals already-recorded
# cheers from before this fix ----------

def test_migrate_reclassifies_legacy_activity_cheers_by_target():
    u = _user(cheers=[
        _cheer("activity", "meditation", status="unlocked"),
        _cheer("activity", "stretch", status="locked"),
        _cheer("activity", "walk", status="unlocked"),
    ])
    assert _migrate_legacy_cheer_occasions(u) is True
    assert u["cheers"][0]["cheer_type"] == "before_session"
    assert u["cheers"][1]["cheer_type"] == "before_session"
    assert u["cheers"][2]["cheer_type"] == "before_activity"


def test_migrate_relocks_a_legacy_cheer_that_was_wrongly_unlocked():
    u = _user(cheers=[_cheer("activity", "meditation", status="unlocked")])
    _migrate_legacy_cheer_occasions(u)
    assert u["cheers"][0]["status"] == "locked"


def test_migrate_leaves_an_already_played_legacy_cheer_played():
    u = _user(cheers=[_cheer("activity", "meditation", status="played", played_on="2026-01-01")])
    _migrate_legacy_cheer_occasions(u)
    assert u["cheers"][0]["status"] == "played"
    assert u["cheers"][0]["cheer_type"] == "before_session"


def test_migrate_fixes_a_cheer_recorded_with_the_senders_nickname_as_family_name():
    u = _user(
        family=[{"id": "fam1", "name": "Shalyn", "nickname": "Granny"}],
        cheers=[_cheer("anytime", family_id="fam1", family_name="Granny")],
    )
    assert _migrate_legacy_cheer_occasions(u) is True
    assert u["cheers"][0]["family_name"] == "Shalyn"


def test_migrate_is_a_no_op_once_everything_is_already_correct():
    u = _user(
        family=[{"id": "fam1", "name": "Shalyn", "nickname": "Granny"}],
        cheers=[_cheer("anytime", family_id="fam1", family_name="Shalyn")],
    )
    assert _migrate_legacy_cheer_occasions(u) is False
