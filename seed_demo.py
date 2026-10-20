"""Fill the demo user with ~4 weeks of history so the fitness log, streaks,
and badges look alive on camera. Leaves today empty so a milestone can be
earned live during the demo video.

Run:  python seed_demo.py            (name defaults to "Rose")
      python seed_demo.py --name Evelyn
"""
import argparse
from datetime import date, timedelta

from vera import progress
from vera.storage import Store

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

store.save_user(user)
s = progress.streaks(user["activities"], today)
print(f"Seeded {args.name}: {len(user['activities'])} sessions, current streak {s['current']}, "
      f"badges {[m['title'] for m in user['milestones']]}")
