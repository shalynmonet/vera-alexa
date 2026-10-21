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


def test_upcoming_streak_one_day_away():
    user = {"activities": acts(0, 1), "milestones": [], "weekly_goal_days": 4}
    ids = {u["id"] for u in progress.upcoming(user, T)}
    assert "streak_3" in ids


def test_upcoming_excludes_already_earned():
    user = {
        "activities": acts(0, 1, 2),
        "milestones": [{"id": "streak_3", "title": "3 Day Streak", "earned_on": T.isoformat()}],
        "weekly_goal_days": 4,
    }
    ids = {u["id"] for u in progress.upcoming(user, T)}
    assert "streak_3" not in ids


def test_upcoming_stretch_sessions_one_away():
    user = {"activities": acts(*range(9), kind="stretch"), "milestones": [], "weekly_goal_days": 4}
    ids = {u["id"] for u in progress.upcoming(user, T)}
    assert "stretch_10" in ids


def test_upcoming_tried_every_game_missing_one():
    activities = [
        {"type": t, "date": T.isoformat(), "minutes": 2, "details": {}}
        for t in ["memory_game", "matching_game", "saying_game"]
    ]
    user = {"activities": activities, "milestones": [], "weekly_goal_days": 4}
    items = {u["id"]: u for u in progress.upcoming(user, T)}
    assert "tried_every_game" in items
    assert "category" in items["tried_every_game"]["distance_label"]


def test_upcoming_nothing_when_far_off():
    user = {"activities": [], "milestones": [], "weekly_goal_days": 4}
    assert progress.upcoming(user, T) == []


def test_weekly_milestones_are_reearnable_next_week():
    activities = [{"type": "walk", "date": T.isoformat(), "minutes": 70, "details": {}}]
    user = {"activities": activities, "milestones": [], "weekly_goal_days": 4}
    progress.check_milestones(user, T)
    assert any(m["id"] == "active_60_week" for m in user["milestones"])

    next_week = T + timedelta(days=7)
    user["activities"].append({"type": "walk", "date": next_week.isoformat(), "minutes": 70, "details": {}})
    new = progress.check_milestones(user, next_week)
    assert any(m["id"] == "active_60_week" for m in new)


def test_calendar_weeks_returns_five_sunday_to_saturday_rows():
    rows = progress.calendar_weeks([], T, weeks=5)
    assert len(rows) == 5
    assert all(len(row) == 7 for row in rows)
    # T is Friday 2026-10-09; its week runs Sunday 2026-10-04 to Saturday 2026-10-10.
    last_row = rows[-1]
    assert last_row[0]["date"] == "2026-10-04"
    assert last_row[-1]["date"] == "2026-10-10"


def test_calendar_weeks_marks_today_active_days_and_future():
    acts = [{"type": "stretch", "date": T.isoformat(), "minutes": 8, "details": {}}]
    rows = progress.calendar_weeks(acts, T, weeks=5)
    today_cell = next(c for row in rows for c in row if c["date"] == T.isoformat())
    assert today_cell["is_today"] is True
    assert today_cell["active"] is True
    tomorrow_cell = next(c for row in rows for c in row if c["date"] == (T + timedelta(days=1)).isoformat())
    assert tomorrow_cell["is_future"] is True
    assert tomorrow_cell["active"] is False


def test_badge_summary_dedupes_repeatable_badges_with_count():
    milestones = [
        {"id": "weekly_goal", "title": "Weekly Goal Met", "earned_on": "2026-09-20"},
        {"id": "weekly_goal", "title": "Weekly Goal Met", "earned_on": "2026-09-27"},
        {"id": "weekly_goal", "title": "Weekly Goal Met", "earned_on": "2026-10-04"},
        {"id": "first_session", "title": "First Session", "earned_on": "2026-09-01"},
    ]
    summary = progress.badge_summary(milestones)
    by_id = {b["id"]: b for b in summary}
    assert len(summary) == 2
    assert by_id["weekly_goal"]["count"] == 3
    assert by_id["first_session"]["count"] == 1


def test_day_detail_collects_activities_cheers_and_badges():
    user = {
        "activities": [
            {"type": "walk", "date": T.isoformat(), "minutes": 20, "details": {"feeling": "happy"}},
            {"type": "memory_game", "date": T.isoformat(), "minutes": 2, "details": {"score": 4, "total": 4}},
            {"type": "walk", "date": (T - timedelta(days=1)).isoformat(), "minutes": 15, "details": {}},
        ],
        "milestones": [{"id": "first_walk", "title": "First Walk", "earned_on": T.isoformat()}],
        "cheers": [
            {"id": "c1", "family_name": "Jake", "played_on": T.isoformat()},
            {"id": "c2", "family_name": "Jake", "played_on": (T - timedelta(days=2)).isoformat()},
        ],
    }
    detail = progress.day_detail(user, T)
    assert detail["date"] == T.isoformat()
    assert {a["type"] for a in detail["activities"]} == {"walk", "memory_game"}
    assert [c["id"] for c in detail["cheers_played"]] == ["c1"]
    assert [b["id"] for b in detail["badges"]] == ["first_walk"]


def test_day_detail_empty_day_returns_empty_lists():
    user = {"activities": [], "milestones": [], "cheers": []}
    detail = progress.day_detail(user, T)
    assert detail == {"date": T.isoformat(), "activities": [], "cheers_played": [], "badges": []}
