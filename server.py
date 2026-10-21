"""Vera MCP server: elder wellness tools for Alexa+.

Self-hosted MCP server, spec 2025-11-25, Streamable HTTP transport.
Endpoint: http://localhost:8000/mcp

Run:  python server.py
"""
from __future__ import annotations

import os
import re
from datetime import date

from mcp.server.fastmcp import FastMCP

from vera import matching_game, media, memories, memory_game, progress, saying_game, word_categories
from vera.content import GAMES
from vera.storage import Store

HOST = os.environ.get("VERA_HOST", "127.0.0.1")
PORT = int(os.environ.get("VERA_PORT", "8000"))

mcp = FastMCP(
    "Vera",
    instructions=(
        "Vera is a warm wellness companion for older adults. Speak slowly, kindly, "
        "and in short sentences. Never shame missed days. Offer games (memory, "
        "matching pairs, finish the saying, word categories), exercise routines, "
        "or meditations -- call list_sessions to see what's available. After a "
        "completed guided session, call log_completion; for anything else the "
        "person did on their own (a walk, a bike ride, gardening, dancing, "
        "swimming, or any other activity), call log_activity instead. Celebrate "
        "any new milestones a tool call returns. Save meaningful personal "
        "details (family, hobbies, upcoming events) with remember_fact so they "
        "can come up again naturally -- never health details."
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


def _slugify_activity(name: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return key or "activity"


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


# ---------- Matching pairs ----------

@mcp.tool()
def start_matching_game(user_id: str = "demo", difficulty: int | None = None) -> dict:
    """Start a matching pairs round: flip cards to find the matching
    pictures. difficulty is the number of pairs (3 to 6, meaning 6 to 12
    cards); if omitted, Vera uses the level from the person's last round."""
    u = store.get_user(user_id)
    level = difficulty or (u.get("matching") or {}).get("next_difficulty") or 3
    cards = matching_game.deal(level)
    pairs = len(cards) // 2
    u["matching"] = {"pairs": pairs}
    store.save_user(u)
    return {
        "pairs": pairs,
        "cards": cards,
        "say": f"Let's play a matching game, {u['name']}. Find the {pairs} pairs of pictures. Take your time.",
    }


@mcp.tool()
def submit_matching_result(attempts: int, user_id: str = "demo", on_date: str | None = None) -> dict:
    """Record a finished matching pairs round. attempts is how many times a
    pair of cards was flipped in total (the pairs count is from the last
    start_matching_game call). Adapts difficulty and logs the game."""
    u = store.get_user(user_id)
    state = u.get("matching") or {"pairs": matching_game.MIN_PAIRS}
    pairs = state["pairs"]
    nxt = matching_game.next_difficulty(pairs, attempts, pairs)
    u["matching"] = {"pairs": pairs, "next_difficulty": nxt}
    perfect = attempts <= pairs
    new = _log(u, "matching_game", 3, _today(on_date), {"pairs": pairs, "attempts": attempts, "perfect": perfect})
    store.save_user(u)
    say = "Every pair found with no wasted flips. Sharp eyes today!" if perfect else f"Well done, you found all {pairs} pairs!"
    return {"pairs": pairs, "attempts": attempts, "perfect": perfect, "next_difficulty": nxt, "say": say, "new_milestones": new}


# ---------- Finish the saying ----------

@mcp.tool()
def start_saying_game(user_id: str = "demo", difficulty: int | None = None) -> dict:
    """Start a 'Finish the Saying' round: classic sayings, multiple choice.
    difficulty is how many sayings are in the round (3 to 6); if omitted,
    Vera uses the level from the person's last round."""
    u = store.get_user(user_id)
    level = difficulty or (u.get("saying") or {}).get("next_difficulty") or 3
    items = saying_game.new_round(level)
    u["saying"] = {"items": items, "index": 0, "score": 0, "total": len(items)}
    store.save_user(u)
    return _saying_question(u)


def _saying_question(u: dict) -> dict:
    state = u["saying"]
    item = state["items"][state["index"]]
    choices = saying_game.choices_for(item)
    return {
        "question_number": state["index"] + 1,
        "total": state["total"],
        "beginning": item["beginning"],
        "choices": choices,
        "done": False,
        "say": f"Finish the saying: {item['beginning']}...?",
    }


@mcp.tool()
def submit_saying_answer(choice: str, user_id: str = "demo", on_date: str | None = None) -> dict:
    """Submit the chosen ending for the current 'Finish the Saying'
    question. Returns whether it was correct, and either the next question
    or, if the round is complete, the final score with any new milestones."""
    u = store.get_user(user_id)
    state = u.get("saying")
    if not state or state.get("index") is None:
        return {"error": "No saying round in progress. Call start_saying_game first."}
    item = state["items"][state["index"]]
    correct = saying_game.is_correct(choice, item["correct"])
    if correct:
        state["score"] += 1
    state["index"] += 1
    if state["index"] < state["total"]:
        store.save_user(u)
        return {"correct": correct, "answer": item["correct"], **_saying_question(u)}

    score, total = state["score"], state["total"]
    perfect = score == total
    nxt = saying_game.next_difficulty(total, score, total)
    u["saying"] = {"next_difficulty": nxt}
    new = _log(u, "saying_game", 2, _today(on_date), {"score": score, "total": total, "perfect": perfect})
    store.save_user(u)
    say = f"All {total} correct! Your memory for sayings is sharp." if perfect else f"You got {score} of {total}. Nice work."
    return {
        "correct": correct, "answer": item["correct"], "done": True,
        "score": score, "total": total, "perfect": perfect,
        "next_difficulty": nxt, "say": say, "new_milestones": new,
    }


# ---------- Word categories ----------

@mcp.tool()
def start_category_game(user_id: str = "demo", difficulty: int | None = None) -> dict:
    """Start a word categories round: name as many things as you can in a
    category (like fruits or animals). difficulty is the target number of
    items to aim for (3 to 8); if omitted, Vera uses the level from the
    person's last round."""
    u = store.get_user(user_id)
    level = difficulty or (u.get("category") or {}).get("next_difficulty") or 4
    level = max(word_categories.MIN_TARGET, min(word_categories.MAX_TARGET, level))
    category = word_categories.random_category()
    u["category"] = {"name": category, "target": level}
    store.save_user(u)
    return {
        "category": category,
        "target": level,
        "say": f"Let's name some things, {u['name']}. Can you name {level} {category}? Tell me when you're ready.",
    }


@mcp.tool()
def submit_category_answer(answer: str, user_id: str = "demo", on_date: str | None = None) -> dict:
    """Score a free-form list of items named for the current word category
    round (forgiving of extra words, order, and small mishearings). Adapts
    difficulty and logs the game."""
    u = store.get_user(user_id)
    state = u.get("category")
    if not state:
        return {"error": "No category round in progress. Call start_category_game first."}
    category, target = state["name"], state["target"]
    result = word_categories.score_answer(category, answer)
    count = result["count"]
    perfect = count >= target
    nxt = word_categories.next_difficulty(target, count, target)
    u["category"] = {"next_difficulty": nxt}
    new = _log(u, "category_game", 2, _today(on_date), {"category": category, "found": result["found"], "count": count, "target": target})
    store.save_user(u)
    say = f"Wonderful! You named {count} {category}." if perfect else f"You named {count} {category}. The target was {target} -- nice try!"
    return {**result, "category": category, "target": target, "perfect": perfect, "next_difficulty": nxt, "say": say, "new_milestones": new}


# ---------- Guided sessions ----------

@mcp.tool()
def list_sessions() -> dict:
    """List the available games, exercise routines, and meditations. Each
    exercise/meditation is flagged 'available' (its real recording exists)
    or not yet (show a friendly 'coming soon' note)."""
    return {
        "games": [{"id": k, "title": v["title"], "description": v["description"]} for k, v in GAMES.items()],
        "stretch_routines": [
            {"id": r["id"], "title": r["title"], "minutes": r["minutes"], "available": r["available"], "thumbnail_url": r["thumbnail_url"]}
            for r in media.exercise_routines()
        ],
        "meditations": [
            {"id": m["id"], "title": m["title"], "minutes": m["minutes"], "type": m.get("type", "audio"), "available": m["available"], "thumbnail_url": m["thumbnail_url"]}
            for m in media.meditations()
        ],
    }


@mcp.tool()
def start_stretch_routine(routine_id: str = "morning_chair_stretch", user_id: str = "demo") -> dict:
    """Start a guided, fully seated or standing exercise routine (chair
    stretch, seated strength, balance, or gentle walking). Returns the real
    video if it's been recorded yet, and the step by step narration Vera
    speaks while it plays either way (including a halfway check in)."""
    r = media.exercise_routine(routine_id)
    if not r:
        return {"error": f"Unknown routine. Options: {[x['id'] for x in media.exercise_routines()]}"}
    name = store.get_user(user_id)["name"]
    return {**r, "routine_id": routine_id, "say": f"Alright {name}, let's do {r['title'].lower()} together."}


@mcp.tool()
def start_meditation(meditation_id: str = "healing_affirmations", user_id: str = "demo") -> dict:
    """Start a guided meditation. Call list_sessions first to see what's
    available. Returns the real audio or video if it's been recorded, or an
    intro line and a target length otherwise."""
    m = media.meditation(meditation_id)
    if not m:
        return {"error": f"Unknown meditation. Options: {[x['id'] for x in media.meditations()]}"}
    return {**m, "meditation_id": meditation_id, "say": m["intro"]}


@mcp.tool()
def log_completion(activity_type: str, minutes: float, user_id: str = "demo", session_id: str | None = None, on_date: str | None = None) -> dict:
    """Record a finished guided stretch/exercise or meditation session.
    activity_type is 'stretch' or 'meditation'. For anything else the person
    did on their own, use log_activity instead. Returns updated streak and
    any new milestones to celebrate."""
    if activity_type not in ("stretch", "meditation"):
        return {"error": "activity_type must be 'stretch' or 'meditation' (memory games log themselves; other activities use log_activity)."}
    u = store.get_user(user_id)
    day = _today(on_date)
    new = _log(u, activity_type, minutes, day, {"session_id": session_id} if session_id else None)
    store.save_user(u)
    s = progress.streaks(u["activities"], day)
    say = f"Well done, {u['name']}."
    if new:
        say += " " + " ".join(m["celebration"] for m in new)
    return {"logged": True, "streak": s, "new_milestones": new, "say": say}


@mcp.tool()
def log_activity(activity: str, minutes: float, user_id: str = "demo", feeling: str | None = None, on_date: str | None = None) -> dict:
    """Log a self-reported activity that doesn't have its own guided session:
    a walk, a bike ride, a stationary bike ride, gardening, dancing,
    swimming, or any other activity by name (for example 'yoga'). Counts
    toward the streak, weekly goal, and milestones just like a stretch or
    meditation. feeling is optional: 'happy', 'okay', or 'tired'."""
    activity_key = _slugify_activity(activity)
    u = store.get_user(user_id)
    day = _today(on_date)
    details = {"feeling": feeling} if feeling else None
    new = _log(u, activity_key, minutes, day, details)
    store.save_user(u)
    s = progress.streaks(u["activities"], day)
    say = f"Nice work, {u['name']}! I've logged your {activity_key.replace('_', ' ')}."
    if new:
        say += " " + " ".join(m["celebration"] for m in new)
    return {"logged": True, "activity": activity_key, "streak": s, "new_milestones": new, "say": say}


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


# ---------- Memories ----------

@mcp.tool()
def remember_fact(fact: str, user_id: str = "demo", category: str | None = None, on_date: str | None = None) -> dict:
    """Save a meaningful personal detail the person shared in conversation --
    family, hobbies, upcoming events, things they're looking forward to --
    so Vera can naturally bring it up again later. category is optional
    (e.g. 'family', 'hobby', 'event'). Never call this with health details
    (diagnoses, medications, symptoms, or anything medical) -- those are
    refused and not saved."""
    if memories.is_health_related(fact):
        return {"saved": False, "error": "That sounds like a health detail -- Vera doesn't store those."}
    u = store.get_user(user_id)
    u.setdefault("memories", [])
    entry = memories.add(u["memories"], fact, _today(on_date).isoformat(), category)
    store.save_user(u)
    return {"saved": True, "memory": entry}


@mcp.tool()
def get_memories(user_id: str = "demo", limit: int = 10) -> dict:
    """Recent personal facts Vera has remembered about this person, most
    recent first, for bringing one up naturally in conversation."""
    u = store.get_user(user_id)
    return {"memories": memories.recent(u.get("memories", []), max(1, min(50, limit)))}


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
