"""Word-recall memory game: Vera reads a short list, the person repeats it back.

Difficulty = number of words (3 to 6). Scoring is forgiving: order doesn't
matter, partial credit counts, and small mishearings from speech-to-text
("apples" vs "apple") still match.
"""
from __future__ import annotations

import random
import re
from difflib import SequenceMatcher

from .content import MEMORY_WORDS

MIN_WORDS, MAX_WORDS = 3, 6


def new_round(difficulty: int, rng: random.Random | None = None) -> list[str]:
    n = max(MIN_WORDS, min(MAX_WORDS, int(difficulty)))
    return (rng or random).sample(MEMORY_WORDS, n)


def _norm(s: str) -> str:
    s = re.sub(r"[^a-z ]", "", s.lower()).strip()
    return re.sub(r"s$", "", s)  # apples -> apple


def score_answer(target: list[str], answer: str) -> dict:
    """Return which target words were recalled from a free-form answer."""
    text = _norm(answer.replace(",", " ").replace(" and ", " "))
    tokens = text.split()
    recalled, missed = [], []
    for word in target:
        w = _norm(word)
        hit = w in text or any(SequenceMatcher(None, w, t).ratio() >= 0.8 for t in tokens)
        (recalled if hit else missed).append(word)
    return {
        "recalled": recalled,
        "missed": missed,
        "score": len(recalled),
        "total": len(target),
        "perfect": not missed,
    }


def next_difficulty(current: int, perfect: bool, score: int, total: int) -> int:
    """Go up after a perfect round, down if they got less than half."""
    if perfect:
        return min(MAX_WORDS, current + 1)
    if score * 2 < total:
        return max(MIN_WORDS, current - 1)
    return current


def encouragement(result: dict) -> str:
    s, t = result["score"], result["total"]
    if result["perfect"]:
        return f"All {t}! Your memory is sharp today."
    if s == 0:
        return "That one was tricky. Let's try a shorter list together."
    return f"You remembered {s} of {t}. That's good work. The ones we missed were {', '.join(result['missed'])}."
