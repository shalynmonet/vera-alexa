"""Finish the Saying: classic proverbs, multiple choice. Difficulty = how
many sayings are in a round (3 to 6).
"""
from __future__ import annotations

import random
import re

MIN_ROUND, MAX_ROUND = 3, 6

SAYINGS = [
    {"beginning": "A penny saved is a penny", "correct": "earned", "wrong": ["spent", "lost", "borrowed"]},
    {"beginning": "Better late than", "correct": "never", "wrong": ["sorry", "early", "last"]},
    {"beginning": "The early bird catches the", "correct": "worm", "wrong": ["bus", "bread", "fish"]},
    {"beginning": "Actions speak louder than", "correct": "words", "wrong": ["money", "thoughts", "promises"]},
    {"beginning": "Don't count your chickens before they", "correct": "hatch", "wrong": ["fly", "grow", "hide"]},
    {"beginning": "When in Rome, do as the", "correct": "Romans do", "wrong": ["locals say", "tourists do", "guides suggest"]},
    {"beginning": "A stitch in time saves", "correct": "nine", "wrong": ["time", "money", "trouble"]},
    {"beginning": "Birds of a feather flock", "correct": "together", "wrong": ["apart", "south", "home"]},
    {"beginning": "You can't judge a book by its", "correct": "cover", "wrong": ["title", "author", "price"]},
    {"beginning": "Practice makes", "correct": "perfect", "wrong": ["tired", "boring", "late"]},
    {"beginning": "Where there's a will, there's a", "correct": "way", "wrong": ["family", "fight", "fortune"]},
    {"beginning": "Every cloud has a silver", "correct": "lining", "wrong": ["sky", "rain", "edge"]},
    {"beginning": "Don't cry over spilled", "correct": "milk", "wrong": ["water", "juice", "tears"]},
    {"beginning": "The grass is always greener on the other", "correct": "side", "wrong": ["hill", "fence", "street"]},
    {"beginning": "Many hands make light", "correct": "work", "wrong": ["money", "noise", "trouble"]},
]


def new_round(difficulty: int, rng: random.Random | None = None) -> list[dict]:
    r = rng or random
    n = max(MIN_ROUND, min(MAX_ROUND, int(difficulty)))
    return r.sample(SAYINGS, min(n, len(SAYINGS)))


def choices_for(item: dict, rng: random.Random | None = None) -> list[str]:
    r = rng or random
    opts = [item["correct"], *item["wrong"]]
    r.shuffle(opts)
    return opts


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def is_correct(choice: str, correct: str) -> bool:
    """Forgiving match: exact, or the correct ending appears in what was
    said/typed (handy for spoken answers like 'I think it's earned')."""
    c, a = _norm(choice), _norm(correct)
    return bool(a) and (c == a or a in c)


def next_difficulty(current: int, score: int, total: int) -> int:
    if score == total:
        return min(MAX_ROUND, current + 1)
    if score * 2 < total:
        return max(MIN_ROUND, current - 1)
    return current
