from datetime import date, timedelta

from vera import engagement

TODAY = date(2026, 10, 21)


def _act(game, days_ago, details):
    return {"type": game, "date": (TODAY - timedelta(days=days_ago)).isoformat(), "minutes": 2, "details": details}


def test_no_trend_when_not_played_this_period():
    acts = [_act("memory_game", 40, {"score": 3, "total": 4})]  # only in the previous period
    assert engagement.game_trends(acts, TODAY) == []


def test_steady_when_accuracy_barely_changes():
    acts = [
        _act("memory_game", 5, {"score": 3, "total": 4}),   # this period: 0.75
        _act("memory_game", 35, {"score": 3, "total": 4}),  # previous period: 0.75
    ]
    trends = engagement.game_trends(acts, TODAY)
    assert len(trends) == 1
    assert "steady" in trends[0]["label"]


def test_improving_label_when_accuracy_rises():
    acts = [
        _act("memory_game", 5, {"score": 4, "total": 4}),   # this period: 1.0
        _act("memory_game", 35, {"score": 1, "total": 4}),  # previous period: 0.25
    ]
    trends = engagement.game_trends(acts, TODAY)
    assert "higher" in trends[0]["label"]


def test_gentle_label_when_accuracy_drops_never_alarming():
    acts = [
        _act("memory_game", 5, {"score": 1, "total": 4}),   # this period: 0.25
        _act("memory_game", 35, {"score": 4, "total": 4}),  # previous period: 1.0
    ]
    trends = engagement.game_trends(acts, TODAY)
    label = trends[0]["label"].lower()
    assert "off days" in label
    for word in ("alert", "concern", "warning", "diagnosis", "decline", "worse"):
        assert word not in label


def test_just_started_when_no_previous_period_data():
    acts = [_act("matching_game", 3, {"pairs": 4, "attempts": 5})]
    trends = engagement.game_trends(acts, TODAY)
    assert "just getting started" in trends[0]["label"]


def test_response_note_only_when_meaningfully_different():
    steady = [
        _act("category_game", 5, {"found": [], "count": 3, "target": 4, "response_seconds": 20}),
        _act("category_game", 35, {"found": [], "count": 3, "target": 4, "response_seconds": 21}),
    ]
    assert engagement.game_trends(steady, TODAY)[0]["response_note"] is None

    slower = [
        _act("category_game", 5, {"found": [], "count": 3, "target": 4, "response_seconds": 40}),
        _act("category_game", 35, {"found": [], "count": 3, "target": 4, "response_seconds": 20}),
    ]
    note = engagement.game_trends(slower, TODAY)[0]["response_note"]
    assert note is not None
    assert "no rush" in note.lower()


def test_multiple_games_sorted_by_most_recently_played():
    acts = [
        _act("memory_game", 10, {"score": 3, "total": 4}),
        _act("category_game", 2, {"found": [], "count": 3, "target": 4}),
    ]
    trends = engagement.game_trends(acts, TODAY)
    assert [t["game"] for t in trends] == ["category_game", "memory_game"]


def test_matching_game_accuracy_from_pairs_and_attempts():
    acts = [_act("matching_game", 2, {"pairs": 4, "attempts": 4})]
    trends = engagement.game_trends(acts, TODAY)
    assert "just getting started" in trends[0]["label"]
