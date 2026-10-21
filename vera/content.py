"""Catalog of Vera's games and the memory game's word list.

Chair stretch routines and meditations are data-driven from their media
manifests instead (see vera/media.py and web/static/media/*/manifest.json).
"""

# Catalog of Vera's games, for the Games section on the home screen.
GAMES = {
    "memory_game": {
        "title": "Memory Game",
        "description": "Listen to a short list of words, then say back as many as you can remember.",
    },
    "matching_game": {
        "title": "Matching Pairs",
        "description": "Flip cards to find the matching pictures.",
    },
    "saying_game": {
        "title": "Finish the Saying",
        "description": "Classic sayings, multiple choice.",
    },
    "category_game": {
        "title": "Word Categories",
        "description": "Name as many things as you can in a category.",
    },
}

# Familiar, easy-to-picture words for the memory game.
MEMORY_WORDS = [
    "apple", "church", "garden", "piano", "river", "biscuit", "quilt", "porch",
    "robin", "lemon", "kitten", "bridge", "candle", "basket", "peach", "fishing",
    "teacup", "sunflower", "radio", "rocking chair", "hymn", "letter", "cornbread",
    "button", "blanket", "train", "cardinal", "rose", "kettle", "picnic",
]
