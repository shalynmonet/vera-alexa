"""The server-side guard that stops stated intent ("I'll walk later") from
being logged as a completed activity -- server._completion_guard_error.
Pure function, no server needed; the exact phrases here are the ones from
the bug report."""
from server import _completion_guard_error

SHOULD_NOT_LOG = [
    "yes I will walk today, that sounds good",
    "I'm going to ride my bike later",
    "maybe I'll do a meditation tonight",
    "that sounds nice",
]

SHOULD_LOG = [
    "I walked for 20 minutes",
    "just got back from a 15 minute walk",
    "I did my bike ride this morning, about 30 minutes",
]


def test_rejects_future_and_intent_phrases():
    for phrase in SHOULD_NOT_LOG:
        error = _completion_guard_error(completed=True, user_statement=phrase)
        assert error is not None, f"expected a rejection for: {phrase!r}"


def test_accepts_clear_past_tense_completions():
    for phrase in SHOULD_LOG:
        error = _completion_guard_error(completed=True, user_statement=phrase)
        assert error is None, f"expected no rejection for: {phrase!r} (got {error!r})"


def test_rejects_when_completed_is_explicitly_false():
    error = _completion_guard_error(completed=False, user_statement="I walked for 20 minutes")
    assert error is not None


def test_rejects_a_made_up_zero_minutes_instead_of_asking():
    # "I went for a walk" is clearly past tense, but with no duration given
    # Nova shouldn't be allowed to log a fabricated 0 -- it should ask.
    error = _completion_guard_error(completed=True, user_statement="I went for a walk", minutes=0)
    assert error is not None
    error_with_real_minutes = _completion_guard_error(completed=True, user_statement="I went for a walk", minutes=20)
    assert error_with_real_minutes is None


def test_skips_the_check_entirely_for_ui_driven_calls():
    # No user_statement at all (the UI's own default) -- never engages the
    # guard, regardless of `completed`.
    assert _completion_guard_error(completed=True, user_statement=None) is None
    assert _completion_guard_error(completed=False, user_statement=None) is None


def test_ui_fixed_statements_never_trip_the_guard():
    for phrase in [
        "Completed via the app's own routine player.",
        "Completed via the app's own meditation player.",
        "Logged via the app's Log an Activity screen.",
        "Logged via the app's own timer -- \"I'm Done\" was tapped.",
    ]:
        assert _completion_guard_error(completed=True, user_statement=phrase) is None
