"""Word categories: name as many things as you can in a category. Scored
forgivingly (order doesn't matter, small mishearings still count), like the
memory game. Difficulty = the target number of items to aim for (3 to 8) --
naming more never hurts, it just isn't required to count as a strong round.
"""
from __future__ import annotations

import random
import re
from difflib import SequenceMatcher

MIN_TARGET, MAX_TARGET = 3, 8

CATEGORIES = {
    "fruits": ["apple", "banana", "orange", "grape", "pear", "peach", "strawberry", "watermelon", "pineapple", "mango", "cherry", "lemon", "plum", "blueberry", "raspberry", "kiwi"],
    "animals": ["dog", "cat", "horse", "cow", "pig", "sheep", "chicken", "duck", "rabbit", "bear", "lion", "tiger", "elephant", "deer", "fox", "bird"],
    "colors": ["red", "blue", "green", "yellow", "orange", "purple", "pink", "black", "white", "brown", "gray", "gold"],
    "furniture": ["chair", "table", "sofa", "couch", "bed", "desk", "dresser", "bookshelf", "lamp", "rug", "mirror", "cabinet"],
    "vegetables": ["carrot", "potato", "tomato", "onion", "broccoli", "corn", "pea", "bean", "cucumber", "pepper", "lettuce", "cabbage"],
}


def random_category(rng: random.Random | None = None) -> str:
    return (rng or random).choice(list(CATEGORIES))


def _norm(s: str) -> str:
    s = re.sub(r"[^a-z ]", "", s.lower()).strip()
    return re.sub(r"s$", "", s)


def score_answer(category: str, answer: str) -> dict:
    """Free-form list of items named, matched forgivingly against the
    category's known items."""
    items = CATEGORIES.get(category, [])
    text = _norm(answer.replace(",", " ").replace(" and ", " "))
    tokens = text.split()
    found = []
    for item in items:
        w = _norm(item)
        hit = w in text or any(SequenceMatcher(None, w, t).ratio() >= 0.8 for t in tokens)
        if hit:
            found.append(item)
    return {"found": found, "count": len(found)}


def next_difficulty(current: int, count: int, target: int) -> int:
    if count >= target:
        return min(MAX_TARGET, current + 1)
    if count * 2 < target:
        return max(MIN_TARGET, current - 1)
    return current
