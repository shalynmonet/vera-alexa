"""Resets both no-code demo profiles -- "Judge Demo" (judge_demo) and
"Rose" (rose_demo) -- so anyone evaluating the live site, or watching a
recorded walkthrough, always sees fresh, consistent demo data, never a
real family's (web/auth.py pins a demo-mode session to one of these two
ids no matter what user_id the client asks for, so a real profile is
never reachable from it either way), and never whatever a previous
visitor clicked around and left behind.

Judge Demo always resets from demo_profile.json. Rose resets from her
saved baseline (data/demo_baselines/rose.json, written by the "Save as
demo baseline" button on her caregiver dashboard -- see web/app.py) when
one exists, falling back to rose_demo_profile.json otherwise.

Either way, every date in the source is stored as "days_ago" relative to
when it was captured, resolved against today's date each time this runs
-- same idea as demo_profile.json's own pattern -- so streaks still line
up and the demo always reads as "this week", not frozen to whenever the
file was written.

Never deletes anything from web/cheer_media/: neither seed file has any
cheers of its own (there's nothing to place there), and a restored
baseline's cheers just point to files a real recording already put
there, which nothing here -- or anywhere else -- ever removes.

Meant to run nightly via the vera-demo-reset systemd timer (installed by
deploy/setup.sh); safe to run by hand too.

Run:  python deploy/reset_demo.py
"""
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# This script lives in deploy/, one level below the project root that
# `vera` is importable from -- Python only puts the script's own directory
# on sys.path automatically, not the root, regardless of cwd.
sys.path.insert(0, str(ROOT))

from vera import family, progress  # noqa: E402
from vera.storage import Store  # noqa: E402

JUDGE_PROFILE_PATH = ROOT / "demo_profile.json"
ROSE_SEED_PATH = ROOT / "rose_demo_profile.json"
# Same directory web/app.py's /api/demo/save_baseline writes to -- both
# sides respect VERA_DEMO_BASELINE_DIR so they always agree on where it is.
DEMO_BASELINE_DIR = Path(os.environ.get("VERA_DEMO_BASELINE_DIR", str(ROOT / "data" / "demo_baselines")))
ROSE_BASELINE_PATH = DEMO_BASELINE_DIR / "rose.json"


def _new_user_shell(user_id: str, name: str, weekly_goal_days: int) -> dict:
    return {
        "user_id": user_id,
        "name": name,
        "weekly_goal_days": weekly_goal_days,
        "activities": [],
        "milestones": [],
        "game": None,
        "display_session": None,
        "planned_activities": [],
    }


def _user_from_seed(profile: dict, user_id: str, today: date) -> dict:
    """A fresh user record from a demo_profile.json-style seed:
    activity_pattern/activity_minutes, memories with days_ago, and a
    family list that gets brand new ids/tokens -- never seeded with
    cheers (see module docstring)."""
    user = _new_user_shell(user_id, profile.get("name", "Friend"), profile.get("weekly_goal_days", 4))

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
        progress.check_milestones(user, d)  # award badges on the day they were earned

    user["memories"] = [
        {
            "fact": m["fact"],
            "recorded_on": (today - timedelta(days=m.get("days_ago", 0))).isoformat(),
            **({"category": m["category"]} if m.get("category") else {}),
        }
        for m in profile.get("memories", [])
    ]
    user["family"] = [
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
    user["cheers"] = []
    return user


def _user_from_baseline(snapshot: dict, user_id: str, today: date) -> dict:
    """A fresh user record from an export_demo_snapshot()-shaped baseline:
    explicit per-activity days_ago (not a pattern), and family
    members/cheers kept exactly as captured -- same ids, tokens, and media
    filenames -- so a family member's already-shared record link keeps
    working across a restore."""
    user = _new_user_shell(user_id, snapshot.get("name", "Friend"), snapshot.get("weekly_goal_days", 4))

    by_days_ago: dict[int, list[dict]] = {}
    for a in snapshot.get("activities", []):
        by_days_ago.setdefault(a["days_ago"], []).append(a)
    for ago in sorted(by_days_ago, reverse=True):
        d = today - timedelta(days=ago)
        for a in by_days_ago[ago]:
            user["activities"].append({
                "type": a["type"], "date": d.isoformat(),
                "minutes": a.get("minutes", 5), "details": a.get("details") or {},
            })
        progress.check_milestones(user, d)

    user["memories"] = [
        {
            "fact": m["fact"],
            "recorded_on": (today - timedelta(days=m["days_ago"])).isoformat(),
            **({"category": m["category"]} if m.get("category") else {}),
        }
        for m in snapshot.get("memories", [])
    ]
    user["family"] = snapshot.get("family", [])

    cheers = []
    for c in snapshot.get("cheers", []):
        entry = {k: v for k, v in c.items() if k not in ("days_ago_recorded", "days_ago_played")}
        entry["recorded_on"] = (today - timedelta(days=c["days_ago_recorded"])).isoformat()
        entry["played_on"] = (
            (today - timedelta(days=c["days_ago_played"])).isoformat()
            if c.get("days_ago_played") is not None else None
        )
        cheers.append(entry)
    user["cheers"] = cheers
    return user


def _report(label: str, user: dict, today: date, source: str | None = None) -> None:
    s = progress.streaks(user["activities"], today)
    extra = f" (from {source})" if source else ""
    print(
        f"Reset demo profile '{label}'{extra}: {len(user['activities'])} sessions, "
        f"streak {s['current']}, {len(user.get('cheers', []))} cheers, "
        f"{len(user.get('family', []))} family member(s)."
    )


def main() -> None:
    today = date.today()
    store = Store()

    judge_profile = json.loads(JUDGE_PROFILE_PATH.read_text(encoding="utf-8"))
    judge_user_id = os.environ.get("VERA_DEMO_USER_ID", judge_profile.get("user_id", "judge_demo"))
    judge_user = _user_from_seed(judge_profile, judge_user_id, today)
    # save_user() fully replaces this user_id's record, which is exactly
    # the "reset" this script is for -- anything a visitor did since the
    # last reset is gone, on purpose.
    store.save_user(judge_user)
    _report("Judge Demo", judge_user, today)

    rose_user_id = os.environ.get("VERA_DEMO_ROSE_USER_ID", "rose_demo")
    if ROSE_BASELINE_PATH.exists():
        snapshot = json.loads(ROSE_BASELINE_PATH.read_text(encoding="utf-8"))
        rose_user = _user_from_baseline(snapshot, rose_user_id, today)
        source = f"baseline saved {snapshot.get('saved_at', 'previously')}"
    else:
        rose_profile = json.loads(ROSE_SEED_PATH.read_text(encoding="utf-8"))
        rose_user = _user_from_seed(rose_profile, rose_user_id, today)
        source = "rose_demo_profile.json -- no baseline saved yet"
    store.save_user(rose_user)
    _report("Rose", rose_user, today, source=source)


if __name__ == "__main__":
    main()
