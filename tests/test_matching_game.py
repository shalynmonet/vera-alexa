import random

from vera import matching_game


def test_deal_produces_pairs():
    from collections import Counter

    cards = matching_game.deal(4, rng=random.Random(1))
    assert len(cards) == 8
    counts = Counter(cards)
    assert all(c == 2 for c in counts.values())
    assert len(counts) == 4


def test_deal_clamps_difficulty():
    assert len(matching_game.deal(1)) == matching_game.MIN_PAIRS * 2
    assert len(matching_game.deal(99)) == matching_game.MAX_PAIRS * 2


def test_next_difficulty_up_on_clean_round():
    assert matching_game.next_difficulty(4, attempts=4, pairs=4) == 5


def test_next_difficulty_down_on_rough_round():
    assert matching_game.next_difficulty(4, attempts=9, pairs=4) == 3


def test_next_difficulty_steady_otherwise():
    assert matching_game.next_difficulty(4, attempts=6, pairs=4) == 4
