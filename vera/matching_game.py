"""Matching pairs: flip cards with large, clear pictures (emoji) to find
the matches. Difficulty = number of pairs (3 to 6, meaning 6 to 12 cards).
The board is dealt server-side so difficulty stays centralized; the actual
flipping happens entirely in the browser, which reports back how many tries
it took.
"""
from __future__ import annotations

import random

MIN_PAIRS, MAX_PAIRS = 3, 6

# Big, simple, easy-to-name pictures.
SYMBOLS = [
    "🍎", "🌻", "🐱", "🚗", "🏠", "🎈", "🐶", "🌙",
    "⭐", "🎵", "🍊", "🦋", "🌈", "🐦", "🍓", "🔑",
]


def deal(difficulty: int, rng: random.Random | None = None) -> list[str]:
    """A shuffled list of cards: `difficulty` pairs, two of each symbol."""
    r = rng or random
    n = max(MIN_PAIRS, min(MAX_PAIRS, int(difficulty)))
    symbols = r.sample(SYMBOLS, n)
    cards = symbols * 2
    r.shuffle(cards)
    return cards


def next_difficulty(current: int, attempts: int, pairs: int) -> int:
    """Go up after a clean round (no wasted flips), down after a rough one."""
    if attempts <= pairs:
        return min(MAX_PAIRS, current + 1)
    if attempts > pairs * 2:
        return max(MIN_PAIRS, current - 1)
    return current
