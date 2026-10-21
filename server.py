"""Vera MCP server: elder wellness tools for Alexa+.

Self-hosted MCP server, spec 2025-11-25, Streamable HTTP transport.
Endpoint: http://localhost:8000/mcp

Run:  python server.py
"""
from __future__ import annotations

import os
from datetime import date

from mcp.server.fastmcp import FastMCP

from vera import memory_game, progress
from vera.content import GAMES, MEDITATIONS, STRETCH_ROUTINES
from vera.storage import Store

HOST = os.environ.get("VERA_HOST", "127.0.0.1")
PORT = int(os.environ.get("VERA_PORT", "8000"))

mcp = FastMCP(
    "Vera",
    instructions=(
        "Vera is a warm wellness companion for older adults. Speak slowly, kindly, "
        "and in short sentences. Never shame missed days. Offer the memory game, a "
        "chair stretch, or a meditation. After any completed session, call "
        "log_completion and celebrate any new milestones it returns."
    ),
    host=HOST,
    port=PORT,
    stateless_http=True,
)
store = Store()


def _today(on_date: str | None) -> date:
    return date.fromisoformat(on_date) if on_date else date.today()


def _log(user: dict, activity_type: str, minutes: float, day: date, details: dict | None = None) -> list[dict]:
    user["activities"].append({"type": activity_type, "date": day.isoformat(), "minutes": minutes, "details": details or {}})
    return progress.check_milestones(user, day)


# ---------- Profile ----------

@mcp.tool()
def get_profile(user_id: str = "demo") -> dict:
    """Get a user's name and weekly activity goal."""
    u = store.get_user(user_id)
    return {"user_id": u["user_id"], "name": u["name"], "weekly_goal_days": u["weekly_goal_days"]}


@mcp.tool()
def set_profile(user_id: str = "demo", name: str | None = None, weekly_goal_days: int | None = None) -> dict:
    """Set the user's preferred name and/or weekly goal (number of active days, 1 to 7)."""
    u = store.get_user(user_id)
    if name:
        u["name"] = name
    if weekly_goal_days:
        u["weekly_goal_days"] = max(1, min(7, weekly_goal_days))
    store.save_user(u)
    return get_profile(user_id)


@mcp.tool()
def list_profiles() -> dict:
    """List everyone who has a profile on this Vera, for the start screen's
    profile picker ('Continue as Rose', 'Add a person')."""
    return {"profiles": store.list_users()}


@mcp.tool()
def create_profile(name: str, weekly_goal_days: int = 4) -> dict:
    """Create a new person's profile ('Add a person' on the start screen) and
    return it, including the new user_id to use for every tool call after."""
    user_id = store.new_user_id(name)
    u = store.get_user(user_id)
    u["name"] = name
    u["weekly_goal_days"] = max(1, min(7, weekly_goal_days))
    store.save_user(u)
    return {"user_id": user_id, "name": u["name"], "weekly_goal_days": u["weekly_goal_days"]}


# ---------- Memory game ----------

@mcp.tool()
def start_memory_game(user_id: str = "demo", difficulty: int | None = None) -> dict:
    """Start a word recall round. Vera reads the words aloud, then asks the person
    to repeat them. Difficulty is the number of words (3 to 6); if omitted, Vera
    uses the level from the person's last game."""
    u = store.get_user(user_id)
    level = difficulty or (u.get("game") or {}).get("next_difficulty") or 3
    words = memory_game.new_round(level)
    u["game"] = {"words": words, "difficulty": len(words)}
    store.save_user(u)
    return {
        "words": words,
        "difficulty": len(words),
        "say": f"Let's play a memory game, {u['name']}. I'll say {len(words)} words. Listen closely: "
               + ", ".join(words) + ". Now, can you tell me the words you remember?",
    }


@mcp.tool()
def submit_memory_answer(answer: str, user_id: str = "demo", on_date: str | None = None) -> dict:
    """Score the person's spoken answer to the current memory game round.
    Logs the game as an activity and returns any new milestones."""
    u = store.get_user(user_id)
    game = u.get("game")
    if not game or not game.get("words"):
        return {"error": "No game in progress. Call start_memory_game first."}
    result = memory_game.score_answer(game["words"], answer)
    nxt = memory_game.next_difficulty(game["difficulty"], result["perfect"], result["score"], result["total"])
    u["game"] = {"words": None, "next_difficulty": nxt}
    new = _log(u, "memory_game", 2, _today(on_date), {"score": result["score"], "total": result["total"], "perfect": result["perfect"]})
    store.save_user(u)
    return {**result, "next_difficulty": nxt, "say": memory_game.encouragement(result), "new_milestones": new}


# ---------- Guided sessions ----------

@mcp.tool()
def list_sessions() -> dict:
    """List the available games, chair stretch routines, and meditations."""
    return {
        "games": [{"id": k, "title": v["title"], "description": v["description"]} for k, v in GAMES.items()],
        "stretch_routines": [{"id": k, "title": v["title"], "minutes": v["minutes"]} for k, v in STRETCH_ROUTINES.items()],
        "meditations": [{"id": k, "title": v["title"], "minutes": v["minutes"]} for k, v in MEDITATIONS.items()],
    }


@mcp.tool()
def start_stretch_routine(routine_id: str = "morning_chair_stretch", user_id: str = "demo") -> dict:
    """Start a guided, fully seated chair stretch. Returns the video and the
    step by step narration Vera speaks while it plays (including a halfway check in)."""
    r = STRETCH_ROUTINES.get(routine_id)
    if not r:
        return {"error": f"Unknown routine. Options: {list(STRETCH_ROUTINES)}"}
    name = store.get_user(user_id)["name"]
    return {"routine_id": routine_id, **r, "say": f"Alright {name}, let's stretch together. Everything today is done sitting down."}


@mcp.tool()
def start_meditation(meditation_id: str = "short_calm", user_id: str = "demo") -> dict:
    """Start a guided meditation: short_calm (3 min), long_calm (10 min), or bedtime."""
    m = MEDITATIONS.get(meditation_id)
    if not m:
        return {"error": f"Unknown meditation. Options: {list(MEDITATIONS)}"}
    return {"meditation_id": meditation_id, **m, "say": m["intro"]}


@mcp.tool()
def log_completion(activity_type: str, minutes: float, user_id: str = "demo", session_id: str | None = None, on_date: str | None = None) -> dict:
    """Record a finished stretch or meditation session. activity_type is
    'stretch' or 'meditation'. Returns updated streak and any new milestones to celebrate."""
    if activity_type not in ("stretch", "meditation"):
        return {"error": "activity_type must be 'stretch' or 'meditation' (memory games log themselves)."}
    u = store.get_user(user_id)
    day = _today(on_date)
    new = _log(u, activity_type, minutes, day, {"session_id": session_id} if session_id else None)
    store.save_user(u)
    s = progress.streaks(u["activities"], day)
    say = f"Well done, {u['name']}."
    if new:
        say += " " + " ".join(m["celebration"] for m in new)
    return {"logged": True, "streak": s, "new_milestones": new, "say": say}


# ---------- Fitness log ----------

@mcp.tool()
def get_fitness_log(user_id: str = "demo", days: int = 28, on_date: str | None = None) -> dict:
    """Activity calendar for the on screen fitness log (one entry per day, oldest
    first), plus totals, streak, this week's goal progress, and earned badges."""
    u = store.get_user(user_id)
    day = _today(on_date)
    acts = u["activities"]
    totals: dict[str, int] = {}
    for a in acts:
        totals[a["type"]] = totals.get(a["type"], 0) + 1
    return {
        "name": u["name"],
        "calendar": progress.calendar(acts, day, max(7, min(90, days))),
        "totals": totals,
        "total_minutes": round(sum(a["minutes"] for a in acts)),
        "streak": progress.streaks(acts, day),
        "week": progress.week_summary(acts, day, u["weekly_goal_days"]),
        "milestones": u["milestones"],
    }


@mcp.tool()
def get_streak(user_id: str = "demo", on_date: str | None = None) -> dict:
    """Current and longest streak. One missed day is forgiven (grace day)."""
    u = store.get_user(user_id)
    return progress.streaks(u["activities"], _today(on_date))


@mcp.tool()
def check_milestones(user_id: str = "demo", on_date: str | None = None) -> dict:
    """Award any milestones the person has earned but not yet received."""
    u = store.get_user(user_id)
    new = progress.check_milestones(u, _today(on_date))
    store.save_user(u)
    return {"new_milestones": new, "all_milestones": u["milestones"]}


# ---------- Caregiver ----------

@mcp.tool()
def get_daily_summary(user_id: str = "demo", on_date: str | None = None) -> dict:
    """Caregiver friendly summary: what the person did today, streak, weekly
    progress, and recent good news worth mentioning on a family call."""
    u = store.get_user(user_id)
    day = _today(on_date)
    todays = [a for a in u["activities"] if a["date"] == day.isoformat()]
    s = progress.streaks(u["activities"], day)
    w = progress.week_summary(u["activities"], day, u["weekly_goal_days"])
    recent = [m for m in u["milestones"] if (day - date.fromisoformat(m["earned_on"])).days <= 7]
    parts = [f"{u['name']} completed {len(todays)} activit{'y' if len(todays) == 1 else 'ies'} today"]
    if todays:
        parts[0] += " (" + ", ".join(sorted({a['type'].replace('_', ' ') for a in todays})) + ")"
    if w["goal_met"]:
        parts.append(f"weekly goal met with {w['active_days']} active days")
    else:
        parts.append(f"{w['active_days']} of {w['goal_days']} active days this week")
    if s["current"] >= 2:
        parts.append(f"a {s['current']} day streak")
    text = "; ".join(parts) + "."
    if recent:
        titles = list(dict.fromkeys(m["title"] for m in recent))
        text += " New this week: " + ", ".join(titles) + "."
    return {"date": day.isoformat(), "activities_today": todays, "streak": s, "week": w, "recent_milestones": recent, "summary": text}


def build_app():
    """Streamable HTTP ASGI app with CORS so the browser based Alexa+ simulator can call it."""
    from starlette.middleware.cors import CORSMiddleware

    app = mcp.streamable_http_app()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get("VERA_CORS_ORIGINS", "*").split(","),
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["Mcp-Session-Id", "MCP-Protocol-Version"],
    )
    return app


if __name__ == "__main__":
    import uvicorn

    print(f"Vera MCP server on http://{HOST}:{PORT}/mcp")
    uvicorn.run(build_app(), host=HOST, port=PORT)
