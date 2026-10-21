from datetime import date, timedelta

from vera import memory_game, progress


def acts(*days_ago, today=date(2026, 10, 9), kind="stretch"):
    return [{"type": kind, "date": (today - timedelta(days=d)).isoformat(), "minutes": 5, "details": {}} for d in days_ago]


T = date(2026, 10, 9)


def test_streak_consecutive():
    assert progress.streaks(acts(0, 1, 2), T) == {"current": 3, "longest": 3, "active_today": True}


def test_streak_grace_day_keeps_streak():
    # missed 2 days ago only -> still one run of 3 active days
    assert progress.streaks(acts(0, 1, 3), T)["current"] == 3


def test_two_missed_days_break_streak():
    s = progress.streaks(acts(0, 3, 4, 5), T)
    assert s["current"] == 1 and s["longest"] == 3


def test_streak_alive_if_active_yesterday():
    s = progress.streaks(acts(1, 2), T)
    assert s["current"] == 2 and not s["active_today"]


def test_streak_reset_after_long_gap():
    assert progress.streaks(acts(5, 6, 7), T)["current"] == 0


def test_milestones_awarded_once():
    user = {"activities": acts(0, 1, 2), "milestones": [], "weekly_goal_days": 4}
    new = progress.check_milestones(user, T)
    ids = {m["id"] for m in new}
    assert {"first_session", "streak_3"} <= ids
    assert progress.check_milestones(user, T) == []


def test_weekly_goal():
    # 2026-10-09 is a Friday; Mon..Thu active = 4 days
    user = {"activities": acts(1, 2, 3, 4), "milestones": [], "weekly_goal_days": 4}
    assert "weekly_goal" in {m["id"] for m in progress.check_milestones(user, T)}


def test_memory_scoring_forgiving():
    r = memory_game.score_answer(["apple", "church", "piano"], "Apples, piano and uh... chirch")
    assert r["perfect"] and r["score"] == 3


def test_memory_partial():
    r = memory_game.score_answer(["apple", "church", "piano", "river"], "apple and river")
    assert r["score"] == 2 and set(r["missed"]) == {"church", "piano"}


def test_difficulty_adapts():
    assert memory_game.next_difficulty(3, True, 3, 3) == 4
    assert memory_game.next_difficulty(6, True, 6, 6) == 6
    assert memory_game.next_difficulty(5, False, 1, 5) == 4
    assert memory_game.next_difficulty(4, False, 3, 4) == 4


def test_calendar_length():
    cal = progress.calendar(acts(0, 3), T, 28)
    assert len(cal) == 28 and cal[-1]["active"] and cal[-1]["date"] == T.isoformat()


def test_week_summary_active_minutes():
    w = progress.week_summary(acts(0, 1, kind="walk"), T, 4)
    assert w["active_minutes"] == 10


def test_first_walk_milestone():
    user = {"activities": acts(0, kind="walk"), "milestones": [], "weekly_goal_days": 4}
    ids = {m["id"] for m in progress.check_milestones(user, T)}
    assert "first_walk" in ids


def test_first_ride_milestone_counts_bike_and_stationary_bike():
    user = {"activities": acts(0, kind="stationary_bike"), "milestones": [], "weekly_goal_days": 4}
    ids = {m["id"] for m in progress.check_milestones(user, T)}
    assert "first_ride" in ids


def test_active_60_minutes_this_week_milestone():
    activities = [{"type": "walk", "date": T.isoformat(), "minutes": 70, "details": {}}]
    user = {"activities": activities, "milestones": [], "weekly_goal_days": 4}
    ids = {m["id"] for m in progress.check_milestones(user, T)}
    assert "active_60_week" in ids


def test_active_100_lifetime_minutes_milestone():
    activities = [{"type": "walk", "date": (T - timedelta(days=i)).isoformat(), "minutes": 50, "details": {}} for i in range(3)]
    user = {"activities": activities, "milestones": [], "weekly_goal_days": 4}
    ids = {m["id"] for m in progress.check_milestones(user, T)}
    assert "active_100_lifetime" in ids


def test_tried_every_game_milestone():
    activities = [
        {"type": t, "date": T.isoformat(), "minutes": 2, "details": {}}
        for t in ["memory_game", "matching_game", "saying_game", "category_game"]
    ]
    user = {"activities": activities, "milestones": [], "weekly_goal_days": 4}
    ids = {m["id"] for m in progress.check_milestones(user, T)}
    assert "tried_every_game" in ids


def test_tried_every_game_not_awarded_until_all_four():
    activities = [
        {"type": t, "date": T.isoformat(), "minutes": 2, "details": {}}
        for t in ["memory_game", "matching_game", "saying_game"]
    ]
    user = {"activities": activities, "milestones": [], "weekly_goal_days": 4}
    ids = {m["id"] for m in progress.check_milestones(user, T)}
    assert "tried_every_game" not in ids


def test_weekly_milestones_are_reearnable_next_week():
    activities = [{"type": "walk", "date": T.isoformat(), "minutes": 70, "details": {}}]
    user = {"activities": activities, "milestones": [], "weekly_goal_days": 4}
    progress.check_milestones(user, T)
    assert any(m["id"] == "active_60_week" for m in user["milestones"])

    next_week = T + timedelta(days=7)
    user["activities"].append({"type": "walk", "date": next_week.isoformat(), "minutes": 70, "details": {}})
    new = progress.check_milestones(user, next_week)
    assert any(m["id"] == "active_60_week" for m in new)
