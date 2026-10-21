from vera import word_categories


def test_score_answer_forgiving():
    r = word_categories.score_answer("fruits", "apples, bananas and a peech")
    assert "apple" in r["found"] and "banana" in r["found"] and "peach" in r["found"]
    assert r["count"] == 3


def test_score_answer_ignores_non_category_words():
    r = word_categories.score_answer("fruits", "apple and a bicycle")
    assert r["found"] == ["apple"]


def test_next_difficulty_up_when_target_met():
    assert word_categories.next_difficulty(4, count=5, target=4) == 5


def test_next_difficulty_down_when_far_short():
    assert word_categories.next_difficulty(4, count=1, target=4) == 3
