"""Gentle, descriptive engagement trends for the cognitive games -- accuracy
and response time, compared month over month. Deliberately not clinical:
this is a wellness companion, not a screening tool, so trends are phrased
as plain observations ("scores steady this month"), never as alerts,
scores against a norm, or anything that reads as a health claim. See
vera/progress.py for the streak/milestone logic this complements.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .content import GAMES

GAME_TYPES = set(GAMES)

# A change smaller than this (as a fraction of accuracy, 0-1) reads as
# "steady" rather than up or down -- day-to-day noise, not a trend.
ACCURACY_STEADY_BAND = 0.08
# A change in average response time smaller than this fraction of the
# earlier period's average reads as "about the same pace".
RESPONSE_STEADY_FRACTION = 0.2


def _accuracy(details: dict[str, Any]) -> float | None:
    if "score" in details and "total" in details and details["total"]:
        return details["score"] / details["total"]
    if "pairs" in details and "attempts" in details and details["attempts"]:
        return min(1.0, details["pairs"] / details["attempts"])
    if "found" in details and "target" in details and details["target"]:
        return min(1.0, details["count"] / details["target"])
    return None


def _split_periods(acts: list[dict], today: date) -> tuple[list[dict], list[dict]]:
    """(this_period, previous_period) -- rolling 30 day windows, not
    calendar months, so this doesn't depend on which day of the month it
    happens to be run."""
    this_start = today - timedelta(days=29)
    prev_start = today - timedelta(days=59)
    this_period, prev_period = [], []
    for a in acts:
        d = date.fromisoformat(a["date"])
        if this_start <= d <= today:
            this_period.append(a)
        elif prev_start <= d < this_start:
            prev_period.append(a)
    return this_period, prev_period


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _accuracy_label(title: str, this_acc: float | None, prev_acc: float | None) -> str | None:
    if this_acc is None:
        return None
    if prev_acc is None:
        return f"{title} scores: just getting started this month."
    delta = this_acc - prev_acc
    if abs(delta) <= ACCURACY_STEADY_BAND:
        return f"{title} scores steady this month."
    if delta > 0:
        return f"{title} scores a little higher this month."
    return f"{title} scores a bit different this month -- everyone has off days."


def _response_label(this_rt: float | None, prev_rt: float | None) -> str | None:
    if this_rt is None or prev_rt is None or prev_rt <= 0:
        return None
    change = (this_rt - prev_rt) / prev_rt
    if abs(change) <= RESPONSE_STEADY_FRACTION:
        return None  # not worth mentioning -- about the same pace
    if change < 0:
        return "Answering a little quicker lately."
    return "Taking a little more time to think things through lately -- no rush."


def game_trends(activities: list[dict], today: date | None = None) -> list[dict]:
    """One gentle trend entry per game type the person has played, most
    recently played first. Never a diagnosis, an alert, or a health claim --
    just a warm, descriptive note for Progress and the caregiver dashboard."""
    today = today or date.today()
    by_type: dict[str, list[dict]] = {}
    for a in activities:
        if a["type"] in GAME_TYPES:
            by_type.setdefault(a["type"], []).append(a)

    out = []
    for game_type, acts in by_type.items():
        this_period, prev_period = _split_periods(acts, today)
        if not this_period:
            continue  # hasn't played this one in the last month -- nothing to say

        title = GAMES[game_type]["title"]
        this_acc = _avg([a for a in (_accuracy(x["details"]) for x in this_period) if a is not None])
        prev_acc = _avg([a for a in (_accuracy(x["details"]) for x in prev_period) if a is not None])
        this_rt = _avg([x["details"]["response_seconds"] for x in this_period if x["details"].get("response_seconds")])
        prev_rt = _avg([x["details"]["response_seconds"] for x in prev_period if x["details"].get("response_seconds")])

        label = _accuracy_label(title, this_acc, prev_acc)
        if not label:
            continue
        response_note = _response_label(this_rt, prev_rt)

        out.append({
            "game": game_type,
            "title": title,
            "sessions_this_period": len(this_period),
            "label": label,
            "response_note": response_note,
            "_last_played": max(x["date"] for x in acts),
        })

    out.sort(key=lambda g: g.pop("_last_played"), reverse=True)
    return out
