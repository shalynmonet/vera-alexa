"""Resets the no-code "Try the Demo" judge profile from demo_profile.json,
so anyone evaluating the live submission always sees a fresh, consistent
demo -- never a real family's data (web/auth.py pins demo-mode sessions to
this one profile id, VERA_DEMO_USER_ID, so a real profile is never
reachable from it either way), and never whatever a previous visitor
clicked around and left behind.

"days_ago" fields in demo_profile.json are resolved against today's date
each time this runs -- same idea as seed_demo.py's own pattern for the
submission demo video -- so the demo always reads as "this week", not
frozen to whenever the JSON was written.

Meant to run nightly via the vera-demo-reset systemd timer (installed by
deploy/setup.sh); safe to run by hand too.

Run:  python deploy/reset_demo.py
"""
import json
import math
import os
import struct
import sys
import wave
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# This script lives in deploy/, one level below the project root that
# `vera` is importable from -- Python only puts the script's own directory
# on sys.path automatically, not the root, regardless of cwd.
sys.path.insert(0, str(ROOT))

from vera import family, progress  # noqa: E402
from vera.storage import Store  # noqa: E402

PROFILE_PATH = ROOT / "demo_profile.json"
CHEER_MEDIA_DIR = ROOT / "web" / "cheer_media"


def _make_placeholder_cheer_audio(path: Path) -> None:
    """A short, gentle two-note chime standing in for a real family
    recording -- see seed_demo.py, which this mirrors."""
    path.parent.mkdir(parents=True, exist_ok=True)
    framerate = 22050
    seconds = 1.6
    amplitude = 6000
    notes = [523.25, 659.25]
    n_frames = int(framerate * seconds)
    frames = bytearray()
    for i in range(n_frames):
        t = i / framerate
        freq = notes[0] if t < seconds / 2 else notes[1]
        fade = min(1.0, (seconds / 2 - abs(t - seconds / 4)) * 8) if t < seconds / 2 else \
            min(1.0, (seconds / 2 - abs(t - (seconds / 4 + seconds / 2))) * 8)
        sample = int(amplitude * max(0.0, min(1.0, fade)) * math.sin(2 * math.pi * freq * t))
        frames += struct.pack("<h", sample)
    with wave.open(str(path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(framerate)
        f.writeframes(bytes(frames))


def main() -> None:
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    user_id = os.environ.get("VERA_DEMO_USER_ID", profile.get("user_id", "judge_demo"))
    today = date.today()

    user = {
        "user_id": user_id,
        "name": profile.get("name", "Judge Demo"),
        "weekly_goal_days": profile.get("weekly_goal_days", 4),
        "activities": [],
        "milestones": [],
        "game": None,
    }

    minutes_by_type = profile.get("activity_minutes", {})
    pattern = profile.get("activity_pattern", {})
    for ago_str in sorted(pattern, key=int, reverse=True):
        ago = int(ago_str)
        d = today - timedelta(days=ago)
        for activity_type in pattern[ago_str]:
            details = {"score": 3, "total": 4, "perfect": False} if activity_type == "memory_game" else {}
            user["activities"].append({
                "type": activity_type, "date": d.isoformat(),
                "minutes": minutes_by_type.get(activity_type, 5), "details": details,
            })
        progress.check_milestones(user, d)  # award badges on the day they were earned, like seed_demo.py

    user["memories"] = [
        {
            "fact": m["fact"],
            "recorded_on": (today - timedelta(days=m.get("days_ago", 0))).isoformat(),
            **({"category": m["category"]} if m.get("category") else {}),
        }
        for m in profile.get("memories", [])
    ]

    family_members = [
        {
            "id": family.new_id(),
            "name": fm["name"],
            "phone": fm.get("phone"),
            "nickname": fm.get("nickname"),
            "relationship": fm.get("relationship"),
            "email": fm.get("email"),
            "email_opt_in": fm.get("email_opt_in", False),
            "onboarded": True,
            "low_queue_notified_at": None,
            "token": family.new_token(),
        }
        for fm in profile.get("family", [])
    ]
    user["family"] = family_members
    primary_member = family_members[0] if family_members else None

    cheers = []
    if primary_member:
        for c in profile.get("cheers", []):
            filename = f"{family.new_id()}.wav"
            _make_placeholder_cheer_audio(CHEER_MEDIA_DIR / filename)
            days_ago = c.get("days_ago", 0)
            played = c.get("played", False)
            cheers.append({
                "id": family.new_id(),
                "family_id": primary_member["id"],
                "family_name": primary_member["name"],
                "cheer_type": c["cheer_type"],
                "target": c.get("target"),
                "media_type": "audio",
                "file": filename,
                "photo_file": None,
                "storage": "local",
                "duration_seconds": 3,
                "recorded_on": (today - timedelta(days=days_ago)).isoformat(),
                "activities_at_recording": len(user["activities"]),
                "status": c["status"],
                "played_on": (today - timedelta(days=max(days_ago - 1, 0))).isoformat() if played else None,
            })
    user["cheers"] = cheers

    # save_user() fully replaces this user_id's record, which is exactly
    # the "reset" this script is for -- anything a visitor did since the
    # last reset is gone, on purpose.
    Store().save_user(user)
    s = progress.streaks(user["activities"], today)
    print(f"Reset demo profile '{user_id}': {len(user['activities'])} sessions, "
          f"streak {s['current']}, {len(cheers)} cheers, {len(family_members)} family member(s).")


if __name__ == "__main__":
    main()
