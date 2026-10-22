from server import _category_say, _join_words


def test_join_words():
    assert _join_words([]) == ""
    assert _join_words(["dog"]) == "dog"
    assert _join_words(["dog", "cat"]) == "dog and cat"
    assert _join_words(["dog", "cat", "bear"]) == "dog, cat and bear"


def test_category_say_above_goal_celebrates_the_multiple():
    say = _category_say("animals", count=8, target=4, unmatched=[])
    assert "8" in say and "4" in say
    assert "twice" in say


def test_category_say_past_goal_but_not_double():
    say = _category_say("animals", count=5, target=4, unmatched=[])
    assert "5" in say and "4" in say
    assert "twice" not in say


def test_category_say_meets_goal_exactly():
    say = _category_say("animals", count=4, target=4, unmatched=[])
    assert "Wonderful" in say
    assert "4" in say


def test_category_say_below_goal():
    say = _category_say("animals", count=2, target=4, unmatched=[])
    assert "2" in say and "4" in say
    assert "Wonderful" not in say


def test_category_say_gentle_about_one_rejected_word():
    say = _category_say("animals", count=4, target=4, unmatched=["teapot"])
    assert "teapot" in say
    assert "creativity" in say


def test_category_say_gentle_about_several_rejected_words():
    say = _category_say("animals", count=4, target=4, unmatched=["teapot", "chair"])
    assert "teapot" in say and "chair" in say
    assert "creativity" in say
