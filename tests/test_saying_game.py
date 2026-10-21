import random

from vera import saying_game


def test_new_round_clamps_and_has_choices():
    round_items = saying_game.new_round(2, rng=random.Random(1))
    assert len(round_items) == saying_game.MIN_ROUND
    item = round_items[0]
    choices = saying_game.choices_for(item, rng=random.Random(1))
    assert item["correct"] in choices
    assert len(choices) == 1 + len(item["wrong"])


def test_is_correct_exact_and_forgiving():
    assert saying_game.is_correct("earned", "earned")
    assert saying_game.is_correct("Earned!", "earned")
    assert saying_game.is_correct("I think it's earned", "earned")
    assert not saying_game.is_correct("spent", "earned")


def test_next_difficulty_up_on_perfect():
    assert saying_game.next_difficulty(3, score=3, total=3) == 4


def test_next_difficulty_down_on_poor_score():
    assert saying_game.next_difficulty(4, score=1, total=4) == 3
