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
}

# Familiar, easy-to-picture words for the memory game.
MEMORY_WORDS = [
    "apple", "church", "garden", "piano", "river", "biscuit", "quilt", "porch",
    "robin", "lemon", "kitten", "bridge", "candle", "basket", "peach", "fishing",
    "teacup", "sunflower", "radio", "rocking chair", "hymn", "letter", "cornbread",
    "button", "blanket", "train", "cardinal", "rose", "kettle", "picnic",
]
