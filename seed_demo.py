"""Fill the demo user with ~4 weeks of history so the fitness log, streaks,
and badges look alive on camera. Leaves today empty so a milestone can be
earned live during the demo video.

Also seeds one family member (a grandson, "Jake") with a cheer already
recorded and attached to the 7 Day Streak badge -- so the demo can show the
whole Family Cheers loop: finish today's session live, watch the streak
badge land, and have Vera immediately play Jake's cheer for it.

Run:  python seed_demo.py            (name defaults to "Rose")
      python seed_demo.py --name Evelyn
"""
import argparse
import math
import struct
import wave
from datetime import date, timedelta
from pathlib import Path

from vera import family, progress
from vera.storage import Store

CHEER_MEDIA_DIR = Path(__file__).resolve().parent / "web" / "cheer_media"


def _make_placeholder_cheer_audio(path: Path) -> None:
    """A short, gentle two-note chime standing in for a real family
    recording, so the seeded demo has something to actually play."""
    path.parent.mkdir(parents=True, exist_ok=True)
    framerate = 22050
    seconds = 1.6
    amplitude = 6000
    notes = [523.25, 659.25]  # a friendly little C-E chime
    n_frames = int(framerate * seconds)
    frames = bytearray()
    for i in range(n_frames):
        t = i / framerate
        freq = notes[0] if t < seconds / 2 else notes[1]
        # fade in/out a touch so it doesn't click at the edges
        fade = min(1.0, (seconds / 2 - abs(t - seconds / 4)) * 8) if t < seconds / 2 else \
            min(1.0, (seconds / 2 - abs(t - (seconds / 4 + seconds / 2))) * 8)
        sample = int(amplitude * max(0.0, min(1.0, fade)) * math.sin(2 * math.pi * freq * t))
        frames += struct.pack("<h", sample)
    with wave.open(str(path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(framerate)
        f.writeframes(bytes(frames))


parser = argparse.ArgumentParser()
parser.add_argument("--name", default="Rose")
parser.add_argument("--user", default="demo")
args = parser.parse_args()

store = Store()
today = date.today()
user = {"user_id": args.user, "name": args.name, "weekly_goal_days": 4, "activities": [], "milestones": [], "game": None}

# Days ago with activity. Ends with a 6 day streak through yesterday,
# so finishing one session today earns the 7 Day Streak badge on camera.
pattern = {
    27: ["stretch"], 26: ["meditation"], 24: ["stretch", "memory_game"], 23: ["meditation"],
    20: ["stretch"], 19: ["memory_game"], 17: ["stretch", "meditation"], 16: ["stretch"],
    13: ["meditation"], 12: ["stretch"], 10: ["memory_game"], 9: ["stretch"],
    6: ["stretch", "meditation"], 5: ["memory_game"], 4: ["stretch"], 3: ["meditation"],
    2: ["stretch", "memory_game"], 1: ["meditation"],
}
minutes = {"stretch": 8, "meditation": 3, "memory_game": 2}
for ago in sorted(pattern, reverse=True):
    d = today - timedelta(days=ago)
    for t in pattern[ago]:
        details = {"score": 3, "total": 4, "perfect": False} if t == "memory_game" else {}
        user["activities"].append({"type": t, "date": d.isoformat(), "minutes": minutes[t], "details": details})
    progress.check_milestones(user, d)  # award badges on the day they were earned

user["memories"] = [
    {"fact": "She loves spending afternoons in her garden", "recorded_on": (today - timedelta(days=5)).isoformat(), "category": "hobby"},
    {"fact": "Her granddaughter Destiny has a volleyball game this weekend", "recorded_on": (today - timedelta(days=2)).isoformat(), "category": "family"},
]

member = {
    "id": family.new_id(),
    "name": "Jake",
    "phone": "+15555550123",
    "nickname": None,
    "relationship": "Grandson",
    "email": None,
    "email_opt_in": False,
    "onboarded": True,
    "low_queue_notified_at": None,
    "token": family.new_token(),
}
user["family"] = [member]

def _new_cheer(cheer_type, target, status, days_ago, played=False):
    filename = f"{family.new_id()}.wav"
    _make_placeholder_cheer_audio(CHEER_MEDIA_DIR / filename)
    return {
        "id": family.new_id(),
        "family_id": member["id"],
        "family_name": member["name"],
        "cheer_type": cheer_type,
        "target": target,
        "media_type": "audio",
        "file": filename,
        "photo_file": None,
        "storage": "local",
        "duration_seconds": 3,
        "recorded_on": (today - timedelta(days=days_ago)).isoformat(),
        "activities_at_recording": len(user["activities"]),
        "status": status,
        "played_on": (today - timedelta(days=days_ago - 1)).isoformat() if played else None,
    }

# One attached to the badge this demo is set up to earn live today (still
# locked -- that's the point), plus a few already on the Cheers screen so
# it doesn't look empty: an anytime one waiting to play, and a couple
# already played (replayable) from "earlier this week".
user["cheers"] = [
    _new_cheer("milestone", "streak_7", "locked", days_ago=1),
    _new_cheer("anytime", None, "unlocked", days_ago=2),
    _new_cheer("anytime", None, "played", days_ago=5, played=True),
    _new_cheer("milestone", "first_session", "played", days_ago=20, played=True),
]

store.save_user(user)
s = progress.streaks(user["activities"], today)
print(f"Seeded {args.name}: {len(user['activities'])} sessions, current streak {s['current']}, "
      f"badges {[m['title'] for m in user['milestones']]}")
print(f"Family: Jake is one cheer away from celebrating {args.name}'s 7 Day Streak -- "
      "finish one more session today to see it play. The Cheers screen also has "
      "an anytime cheer waiting and two already played, ready to replay.")
