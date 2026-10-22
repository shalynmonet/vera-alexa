"""Word categories: name as many things as you can in a category. Scored
forgivingly (order doesn't matter, small mishearings and plurals still
count), like the memory game. Difficulty = the GOAL number of items to aim
for (3 to 8) -- naming more is celebrated, never capped: the goal is a
target to reach, not a ceiling on how many answers count.
"""
from __future__ import annotations

import random
import re
from difflib import SequenceMatcher
from typing import Callable

MIN_TARGET, MAX_TARGET = 3, 8
FUZZY_THRESHOLD = 0.8

CATEGORIES = {
    "fruits": ["apple", "banana", "orange", "grape", "pear", "peach", "strawberry", "watermelon", "pineapple", "mango", "cherry", "lemon", "plum", "blueberry", "raspberry", "kiwi"],
    "animals": ["dog", "cat", "horse", "cow", "pig", "sheep", "chicken", "duck", "rabbit", "bear", "lion", "tiger", "elephant", "deer", "fox", "bird"],
    "colors": ["red", "blue", "green", "yellow", "orange", "purple", "pink", "black", "white", "brown", "gray", "gold"],
    "furniture": ["chair", "table", "sofa", "couch", "bed", "desk", "dresser", "bookshelf", "lamp", "rug", "mirror", "cabinet"],
    "vegetables": ["carrot", "potato", "tomato", "onion", "broccoli", "corn", "pea", "bean", "cucumber", "pepper", "lettuce", "cabbage"],
}

# A caller may supply verify_unknown(word, category) -> bool to judge a word
# the built-in list doesn't recognize (e.g. "platypus" for animals), instead
# of it being silently dropped. See server.py's submit_category_answer,
# which wires this to Vera's own judgment via Bedrock.
VerifyFn = Callable[[str, str], bool]


def random_category(rng: random.Random | None = None) -> str:
    return (rng or random).choice(list(CATEGORIES))


def _clean(token: str) -> str:
    return re.sub(r"[^a-z]", "", token.lower())


def _stem(token: str) -> str:
    """Collapse a simple trailing-s plural so 'dogs' matches 'dog'."""
    return re.sub(r"s$", "", token)


# Common filler words never need a Nova check or a place in `unmatched` --
# they're just how people talk, not an attempted answer.
_STOPWORDS = {"a", "an", "the", "is", "its", "it", "um", "uh", "like", "think", "maybe", "also", "too", "that"}


def _tokenize(answer: str) -> list[str]:
    text = answer.lower().replace(",", " ").replace(" and ", " ").replace("&", " ")
    tokens = (_clean(t) for t in text.split())
    return [t for t in tokens if t and t not in _STOPWORDS]


def score_answer(category: str, answer: str, verify_unknown: VerifyFn | None = None) -> dict:
    """Free-form list of items named, matched forgivingly (plurals, small
    mishearings) against the category's known words, returned in the order
    the person said them. Every valid match counts -- there is no cap at
    any target/goal, so naming more than asked for just means a longer
    `found` list.

    A token that isn't a known word and isn't a close mishearing of one is
    a candidate for `verify_unknown(word, category)`: if it returns True
    the word counts too (a real but uncommon answer like "platypus"); with
    no verifier, or when it returns False, the word is left out of `found`
    and reported in `unmatched` instead of just being silently dropped.
    """
    catalog = CATEGORIES.get(category, [])
    stems = {_stem(_clean(item)): item for item in catalog}

    found: list[str] = []
    claimed: set[str] = set()  # stems already counted (catalog match or confirmed extra)
    unmatched: list[str] = []
    checked: set[str] = set()  # raw tokens already resolved, so a repeat never re-asks

    for raw in _tokenize(answer):
        stem = _stem(raw)
        if stem in claimed or raw in checked:
            continue

        canonical = stems.get(stem)
        if canonical is None:
            best, best_ratio = None, 0.0
            for item_stem, original in stems.items():
                ratio = SequenceMatcher(None, item_stem, stem).ratio()
                if ratio > best_ratio:
                    best, best_ratio = original, ratio
            if best is not None and best_ratio >= FUZZY_THRESHOLD:
                canonical = best

        if canonical is not None:
            claimed.add(_stem(_clean(canonical)))
            found.append(canonical)
            continue

        checked.add(raw)
        if verify_unknown is not None and verify_unknown(raw, category):
            claimed.add(stem)
            found.append(raw)
        else:
            unmatched.append(raw)

    return {"found": found, "count": len(found), "unmatched": unmatched}


def next_difficulty(current: int, count: int, target: int) -> int:
    """Raise the goal by one after meeting/beating it, or by two when it
    was beaten comfortably (double the goal or more) -- and only ease off
    when the round fell well short."""
    if target and count >= target * 2:
        return min(MAX_TARGET, current + 2)
    if count >= target:
        return min(MAX_TARGET, current + 1)
    if count * 2 < target:
        return max(MIN_TARGET, current - 1)
    return current
