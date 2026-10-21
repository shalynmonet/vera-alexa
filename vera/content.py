"""Catalog of Vera's guided sessions.

video_url values are placeholders until the real videos are recorded.
Drop the files in web/videos/ (or upload to a host) and update the paths.
Each routine has narration steps Vera speaks while the video plays.
"""

STRETCH_ROUTINES = {
    "morning_chair_stretch": {
        "title": "Morning Chair Stretch",
        "minutes": 8,
        "video_url": "/videos/chair-stretch-morning.mp4",
        "steps": [
            {"name": "Settle in", "seconds": 30, "say": "Sit tall near the front of your chair, feet flat on the floor. Let's take two slow breaths together."},
            {"name": "Neck tilts", "seconds": 60, "say": "Gently tilt your ear toward your right shoulder. Hold. Now slowly to the left. Nice and easy."},
            {"name": "Shoulder rolls", "seconds": 60, "say": "Roll your shoulders up, back, and down. Five times. Now the other direction."},
            {"name": "Seated march", "seconds": 90, "say": "Lift one knee, then the other, like a slow march. Hold the sides of the chair if you like."},
            {"name": "Check in", "seconds": 15, "say": "We're halfway there. How are your shoulders feeling?", "check_in": True},
            {"name": "Ankle circles", "seconds": 60, "say": "Lift one foot a little and draw slow circles with your toes. Then switch feet."},
            {"name": "Seated side reach", "seconds": 60, "say": "Raise your right arm and reach gently over to the left. Breathe. Now the other side."},
            {"name": "Cool down", "seconds": 45, "say": "Rest your hands on your lap. Breathe in, and out. You did wonderful today."},
        ],
    },
}

MEDITATIONS = {
    "short_calm": {
        "title": "Three Minute Calm",
        "minutes": 3,
        "video_url": "/videos/meditation-3min.mp4",
        "intro": "Let's take three quiet minutes together. Close your eyes if that feels good.",
    },
    "long_calm": {
        "title": "Ten Minute Calm",
        "minutes": 10,
        "video_url": "/videos/meditation-10min.mp4",
        "intro": "Get comfortable. For the next ten minutes, all you need to do is breathe.",
    },
    "bedtime": {
        "title": "Bedtime Wind Down",
        "minutes": 8,
        "video_url": "/videos/meditation-bedtime.mp4",
        "intro": "The day is done. Let's let it go, one breath at a time.",
    },
}

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
