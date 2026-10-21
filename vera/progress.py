"""Fitness log, streaks, and milestones.

Design choices for older users:
- Any activity counts toward the streak (a meditation day is a good day).
- Grace day: a single missed day does not break a streak. Two missed days in
  a row do. Missed days are never framed as failures.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta


def active_days(activities: list[dict]) -> list[date]:
    return sorted({date.fromisoformat(a["date"]) for a in activities})


def _streak_runs(days: list[date]) -> list[tuple[date, date, int]]:
    """Split active days into runs. Gaps of 1 missed day (grace) keep a run going.
    Returns (start, end, active_day_count) per run."""
    runs = []
    for d in days:
        if runs and (d - runs[-1][1]).days <= 2:
            s, _, c = runs[-1]
            runs[-1] = (s, d, c + 1)
        else:
            runs.append((d, d, 1))
    return runs


def streaks(activities: list[dict], today: date) -> dict:
    runs = _streak_runs(active_days(activities))
    longest = max((c for _, _, c in runs), default=0)
    current = 0
    if runs and (today - runs[-1][1]).days <= 1:
        current = runs[-1][2]
    did_today = bool(runs) and runs[-1][1] == today
    return {"current": current, "longest": longest, "active_today": did_today}


def week_summary(activities: list[dict], today: date, goal_days: int) -> dict:
    start = today - timedelta(days=today.weekday())  # Monday
    in_week = [a for a in activities if start <= date.fromisoformat(a["date"]) <= today]
    days = {date.fromisoformat(a["date"]) for a in in_week}
    return {
        "week_start": start.isoformat(),
        "active_days": len(days),
        "goal_days": goal_days,
        "goal_met": len(days) >= goal_days,
        "active_minutes": round(sum(a["minutes"] for a in in_week)),
    }


def calendar(activities: list[dict], today: date, days: int = 28) -> list[dict]:
    """One entry per day, oldest first, for the big calendar grid on screen."""
    by_day: dict[str, list[str]] = {}
    for a in activities:
        by_day.setdefault(a["date"], []).append(a["type"])
    out = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        out.append({"date": d, "active": d in by_day, "activities": sorted(set(by_day.get(d, [])))})
    return out


# id -> (title, celebration line, test(activities, counts, streak_info, week, game_perfect))
MILESTONES = [
    ("first_session", "First Session", "You've started something wonderful."),
    ("streak_3", "3 Day Streak", "Three days in a row. You're building a habit."),
    ("streak_7", "7 Day Streak", "Seven days in a row. That's wonderful."),
    ("streak_30", "30 Day Streak", "Thirty days. That is truly something to be proud of."),
    ("stretch_10", "10 Stretch Sessions", "Ten stretch sessions. Your body thanks you."),
    ("meditation_10", "10 Meditations", "Ten moments of calm. Well done."),
    ("memory_perfect", "Perfect Memory Game", "Every word, remembered. Sharp as a tack."),
    ("weekly_goal", "Weekly Goal Met", "You met your goal for the week."),
    ("first_walk", "First Walk", "Your first walk, logged. One step at a time."),
    ("first_ride", "First Ride", "Your first ride, logged. Keep on pedaling."),
    ("active_60_week", "60 Active Minutes This Week", "Sixty minutes of activity this week. Wonderful."),
    ("active_100_lifetime", "100 Active Minutes", "A hundred minutes of activity. That really adds up."),
]

# Milestones re-earnable each new week (tracked per-week, not just once).
WEEKLY_MILESTONES = {"weekly_goal", "active_60_week"}


def _earned(mid: str, counts: Counter, streak: dict, week: dict, any_perfect: bool, lifetime_minutes: float) -> bool:
    total = sum(counts.values())
    return {
        "first_session": total >= 1,
        "streak_3": streak["longest"] >= 3,
        "streak_7": streak["longest"] >= 7,
        "streak_30": streak["longest"] >= 30,
        "stretch_10": counts["stretch"] >= 10,
        "meditation_10": counts["meditation"] >= 10,
        "memory_perfect": any_perfect,
        "weekly_goal": week["goal_met"],
        "first_walk": counts.get("walk", 0) >= 1,
        "first_ride": counts.get("bike", 0) + counts.get("stationary_bike", 0) >= 1,
        "active_60_week": week["active_minutes"] >= 60,
        "active_100_lifetime": lifetime_minutes >= 100,
    }[mid]


def check_milestones(user: dict, today: date) -> list[dict]:
    """Award any newly earned milestones. Mutates user; returns the new ones.
    Milestones in WEEKLY_MILESTONES can be earned again each new week."""
    acts = user["activities"]
    counts = Counter(a["type"] for a in acts)
    streak = streaks(acts, today)
    week = week_summary(acts, today, user.get("weekly_goal_days", 4))
    any_perfect = any(a["type"] == "memory_game" and a.get("details", {}).get("perfect") for a in acts)
    lifetime_minutes = sum(a["minutes"] for a in acts)

    have = {(m["id"], m.get("week")) for m in user["milestones"]}
    new = []
    for mid, title, line in MILESTONES:
        key_week = week["week_start"] if mid in WEEKLY_MILESTONES else None
        if (mid, key_week) in have:
            continue
        if _earned(mid, counts, streak, week, any_perfect, lifetime_minutes):
            m = {"id": mid, "title": title, "celebration": line, "earned_on": today.isoformat()}
            if key_week:
                m["week"] = key_week
            user["milestones"].append(m)
            new.append(m)
    return new
