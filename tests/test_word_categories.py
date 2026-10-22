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


def test_next_difficulty_jumps_when_beaten_comfortably():
    assert word_categories.next_difficulty(4, count=8, target=4) == 6


def test_score_answer_counts_every_valid_answer_past_the_goal():
    # The goal is a target to aim for, not a cap on what counts -- naming
    # twice as many as asked should score every one of them.
    r = word_categories.score_answer("animals", "dog cat horse cow pig sheep chicken duck")
    assert r["count"] == 8
    assert r["found"] == ["dog", "cat", "horse", "cow", "pig", "sheep", "chicken", "duck"]


def test_score_answer_preserves_the_order_they_were_said():
    r = word_categories.score_answer("animals", "bear cat dog")
    assert r["found"] == ["bear", "cat", "dog"]


def test_score_answer_dedupes_duplicates_and_plurals():
    r = word_categories.score_answer("animals", "dog dogs cat cat dog")
    assert r["found"] == ["dog", "cat"]
    assert r["count"] == 2


def test_score_answer_checks_unknown_word_before_rejecting():
    asked = []

    def verify(word, category):
        asked.append((word, category))
        return word == "platypus"

    r = word_categories.score_answer("animals", "dog platypus teapot", verify_unknown=verify)
    assert r["found"] == ["dog", "platypus"]
    assert r["count"] == 2
    assert r["unmatched"] == ["teapot"]
    assert ("platypus", "animals") in asked
    assert ("teapot", "animals") in asked


def test_score_answer_without_a_verifier_reports_unmatched_instead_of_guessing():
    r = word_categories.score_answer("fruits", "apple and a bicycle")
    assert r["found"] == ["apple"]
    assert r["unmatched"] == ["bicycle"]
