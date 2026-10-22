"""Vera MCP server: elder wellness tools for Alexa+.

Self-hosted MCP server, spec 2025-11-25, Streamable HTTP transport.
Endpoint: http://localhost:8000/mcp

Run:  python server.py
"""
from __future__ import annotations

import os
import re
from collections import Counter
from datetime import date, datetime

from mcp.server.fastmcp import FastMCP

from vera import engagement, family, matching_game, media, memories, memory_game, progress, saying_game, word_categories, word_verify
from vera.content import GAMES
from vera.storage import Store

HOST = os.environ.get("VERA_HOST", "127.0.0.1")
PORT = int(os.environ.get("VERA_PORT", "8000"))
MAX_CHEERS_PER_DAY = int(os.environ.get("VERA_MAX_CHEERS_PER_DAY", "2"))

mcp = FastMCP(
    "Vera",
    instructions=(
        "Vera is a warm wellness companion for older adults. Speak slowly, kindly, "
        "and in short sentences. Never shame missed days. Offer games (memory, "
        "matching pairs, finish the saying, word categories), exercise routines, "
        "or meditations -- call list_sessions to see what's available. Only log "
        "an activity as done when the person says they've already finished it "
        "(clear past tense) -- a future or conditional statement ('I will', "
        "'I'm going to', 'that sounds good') is a plan, not a completion: call "
        "plan_activity instead and encourage them, never log_completion or "
        "log_activity for it. When you do call either, pass completed and "
        "user_statement honestly -- the call is refused if they don't hold up, "
        "which means ask or encourage rather than retry. After a completed "
        "guided session, call log_completion; for anything else the person did "
        "on their own (a walk, a bike ride, gardening, dancing, swimming, or "
        "any other activity), call log_activity instead. Celebrate "
        "any new milestones a tool call returns. Save meaningful personal "
        "details (family, hobbies, upcoming events) with remember_fact so they "
        "can come up again naturally -- never health details. Family members "
        "can record audio/video cheers for this person via a private link from "
        "the caregiver dashboard (reachable from the Progress screen); if asked "
        "about messages from family, check list_cheers. If asked how they're "
        "doing with a particular game lately, check get_engagement_trends -- "
        "share it warmly and plainly, never as a score, a diagnosis, or a "
        "health claim. If asked to put the current exercise, meditation, or "
        "progress screen on the TV (or similar, like 'let's do chair yoga in "
        "the living room'), call handoff_session_to_display; if asked to bring "
        "it back to the main screen, call it again with session left out."
    ),
    host=HOST,
    port=PORT,
    stateless_http=True,
)
store = Store()


def _today(on_date: str | None) -> date:
    """on_date is meant to be an ISO date for demos/tests to pin a fixed
    day; Nova occasionally passes something else ('today') by analogy with
    a free-text field elsewhere in the same call, so a bad value falls
    back to the real today instead of crashing the whole tool call."""
    if not on_date:
        return date.today()
    try:
        return date.fromisoformat(on_date)
    except ValueError:
        return date.today()


def _log(user: dict, activity_type: str, minutes: float, day: date, details: dict | None = None) -> list[dict]:
    user["activities"].append({"type": activity_type, "date": day.isoformat(), "minutes": minutes, "details": details or {}})
    new_milestones = progress.check_milestones(user, day)
    _unlock_cheers(user, {m["id"] for m in new_milestones}, activity_type)
    return new_milestones


def _unlock_cheers(user: dict, newly_earned_ids: set[str], logged_activity_type: str) -> None:
    """A milestone cheer unlocks the moment its milestone is earned; an
    activity cheer unlocks the moment that activity type is next logged;
    an anytime cheer unlocks on the person's next completed activity after
    it was recorded (any type) -- so a cheer always arrives after some
    real moment of effort, never the instant it's dropped in the box."""
    earned_ids = {m["id"] for m in user["milestones"]} | newly_earned_ids
    for c in user.get("cheers", []):
        if c["status"] != "locked":
            continue
        if c["cheer_type"] == "milestone" and c["target"] in earned_ids:
            c["status"] = "unlocked"
        elif c["cheer_type"] == "activity" and c["target"] == logged_activity_type:
            c["status"] = "unlocked"
        elif c["cheer_type"] == "anytime" and len(user["activities"]) > c.get("activities_at_recording", 0):
            c["status"] = "unlocked"


def _slugify_activity(name: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return key or "activity"


# Stated intent ("I'll walk later") must never be logged as a completed
# activity -- this is the server-side half of that guard (the other half is
# the system prompt telling Nova to pass these honestly). Only engages when
# user_statement is given, i.e. only on Nova's conversational path: UI
# buttons and a session's own "ended"/"I'm done" event never pass one,
# since the tap or the event itself already is the completion signal.
_FUTURE_INTENT_RE = re.compile(
    r"\b(will|gonna|going to|plan(?:ning)? to|later|tomorrow|tonight|maybe|perhaps|"
    r"i'll|might|thinking about|about to|hoping to|soon)\b|sounds (good|nice|great|lovely)",
    re.IGNORECASE,
)
_CLEAR_COMPLETION_RE = re.compile(
    r"\b(i(?:'ve| have)? ?(?:just )?(?:walked|rode|biked|swam|danced|gardened|did|"
    r"finished|completed|went|done)|got back|finished my|completed my|did my)\b",
    re.IGNORECASE,
)


def _completion_guard_error(completed: bool, user_statement: str | None, minutes: float | None = None) -> str | None:
    """None if this is safe to log as a completed activity; otherwise an
    error message explaining why not, meant for Nova to see as a tool
    error and respond to (ask a clarifying question, offer encouragement,
    or call plan_activity) instead of logging."""
    if user_statement is None:
        return None
    if not completed:
        return (
            "This hasn't happened yet -- don't log it as completed. Encourage them warmly, "
            "and call plan_activity so Vera can ask how it went later, instead of logging it now."
        )
    if minutes is not None and minutes <= 0:
        return (
            "No real duration was given (minutes was zero or missing) -- don't log a made-up "
            "number. Ask the person directly how many minutes it was, and log it once they answer."
        )
    if _FUTURE_INTENT_RE.search(user_statement) and not _CLEAR_COMPLETION_RE.search(user_statement):
        return (
            "That reads as a plan for later, not something already finished -- don't log it. "
            "Call plan_activity instead so Vera can ask about it later, and encourage them warmly now."
        )
    return None


def _elapsed_seconds(started_at: str | None) -> float | None:
    """How long since a game's started_at timestamp -- for the gentle
    per-game response-time trend (vera/engagement.py). None if missing or
    malformed, never raises: timing is a nice-to-have, not load-bearing."""
    if not started_at:
        return None
    try:
        return max(0.0, (datetime.now() - datetime.fromisoformat(started_at)).total_seconds())
    except ValueError:
        return None


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
    u["game"] = {"words": words, "difficulty": len(words), "started_at": datetime.now().isoformat()}
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
    response_seconds = _elapsed_seconds(game.get("started_at"))
    u["game"] = {"words": None, "next_difficulty": nxt}
    details = {"score": result["score"], "total": result["total"], "perfect": result["perfect"]}
    if response_seconds is not None:
        details["response_seconds"] = response_seconds
    new = _log(u, "memory_game", 2, _today(on_date), details)
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
    u["matching"] = {"pairs": pairs, "started_at": datetime.now().isoformat()}
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
    response_seconds = _elapsed_seconds(state.get("started_at"))
    u["matching"] = {"pairs": pairs, "next_difficulty": nxt}
    perfect = attempts <= pairs
    details = {"pairs": pairs, "attempts": attempts, "perfect": perfect}
    if response_seconds is not None:
        details["response_seconds"] = response_seconds
    new = _log(u, "matching_game", 3, _today(on_date), details)
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
    u["saying"] = {"items": items, "index": 0, "score": 0, "total": len(items), "response_seconds_total": 0.0, "response_count": 0}
    store.save_user(u)
    return _saying_question(u)


def _saying_question(u: dict) -> dict:
    state = u["saying"]
    state["q_started_at"] = datetime.now().isoformat()
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
    elapsed = _elapsed_seconds(state.get("q_started_at"))
    if elapsed is not None:
        state["response_seconds_total"] += elapsed
        state["response_count"] += 1
    state["index"] += 1
    if state["index"] < state["total"]:
        store.save_user(u)
        return {"correct": correct, "answer": item["correct"], **_saying_question(u)}

    score, total = state["score"], state["total"]
    perfect = score == total
    nxt = saying_game.next_difficulty(total, score, total)
    details = {"score": score, "total": total, "perfect": perfect}
    if state["response_count"]:
        details["response_seconds"] = state["response_seconds_total"] / state["response_count"]
    u["saying"] = {"next_difficulty": nxt}
    new = _log(u, "saying_game", 2, _today(on_date), details)
    store.save_user(u)
    say = f"All {total} correct! Your memory for sayings is sharp." if perfect else f"You got {score} of {total}. Nice work."
    return {
        "correct": correct, "answer": item["correct"], "done": True,
        "score": score, "total": total, "perfect": perfect,
        "next_difficulty": nxt, "say": say, "new_milestones": new,
    }


# ---------- Word categories ----------

def _join_words(words: list[str]) -> str:
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + f" and {words[-1]}"


_MULTIPLE_WORDS = {2: "twice", 3: "three times", 4: "four times", 5: "five times"}


def _category_say(category: str, count: int, target: int, unmatched: list[str]) -> str:
    beyond = count - target
    if beyond > 0:
        multiple = count // target if target else 0
        if multiple >= 2:
            say = (
                f"You named {count} {category}! The goal was {target}. "
                f"That's {_MULTIPLE_WORDS.get(multiple, f'{multiple} times')} the goal, wonderful!"
            )
        else:
            say = f"You named {count} {category} -- past your goal of {target}, wonderful!"
    elif count >= target:
        say = f"Wonderful! You named {count} {category}."
    else:
        say = f"You named {count} {category}. The goal was {target} -- nice try!"
    if unmatched:
        words = _join_words(unmatched)
        if len(unmatched) == 1:
            singular = category[:-1] if category.endswith("s") else category
            article = "an " if singular[:1] in "aeiou" else "a "
            say += f" I'm not sure {words} counts as {article}{singular}, but I love the creativity!"
        else:
            say += f" I'm not sure {words} count as {category}, but I love the creativity!"
    return say


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
    u["category"] = {"name": category, "target": level, "started_at": datetime.now().isoformat()}
    store.save_user(u)
    return {
        "category": category,
        "target": level,
        "say": f"Let's name some things, {u['name']}. Can you name {level} {category}? Tell me when you're ready.",
    }


@mcp.tool()
def submit_category_answer(answer: str, user_id: str = "demo", on_date: str | None = None) -> dict:
    """Score a free-form list of items named for the current word category
    round (forgiving of extra words, order, duplicates, plurals, and small
    mishearings). The goal is a target to reach, not a cap -- every valid
    item counts, however many are named. A word the built-in list doesn't
    recognize is checked with Vera's own judgment before being left out, so
    an uncommon but real answer (like "platypus" for animals) still counts.
    Adapts difficulty and logs the game."""
    u = store.get_user(user_id)
    state = u.get("category")
    if not state:
        return {"error": "No category round in progress. Call start_category_game first."}
    category, target = state["name"], state["target"]
    result = word_categories.score_answer(category, answer, verify_unknown=word_verify.verify)
    count = result["count"]
    perfect = count >= target
    beyond_goal = count > target
    nxt = word_categories.next_difficulty(target, count, target)
    response_seconds = _elapsed_seconds(state.get("started_at"))
    u["category"] = {"next_difficulty": nxt}
    details = {"category": category, "found": result["found"], "count": count, "target": target}
    if result["unmatched"]:
        details["unmatched"] = result["unmatched"]
    if response_seconds is not None:
        details["response_seconds"] = response_seconds
    new = _log(u, "category_game", 2, _today(on_date), details)
    store.save_user(u)
    say = _category_say(category, count, target, result["unmatched"])
    return {
        **result, "category": category, "target": target, "perfect": perfect,
        "beyond_goal": beyond_goal, "next_difficulty": nxt, "say": say, "new_milestones": new,
    }


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


def _clear_matching_plan(user: dict, activity_key: str, day_iso: str) -> None:
    user["planned_activities"] = [
        p for p in user.get("planned_activities", [])
        if not (p["activity"] == activity_key and p["planned_on"] == day_iso)
    ]


@mcp.tool()
def log_completion(activity_type: str, minutes: float, completed: bool, user_statement: str, user_id: str = "demo", session_id: str | None = None, on_date: str | None = None) -> dict:
    """Record a finished guided stretch/exercise or meditation session.
    activity_type is 'stretch' or 'meditation'. For anything else the person
    did on their own, use log_activity instead. completed and user_statement
    are for Nova's conversational path only (when the person describes
    finishing this in their own words rather than tapping the screen's own
    completion button/event): pass the person's exact words as
    user_statement and whether they actually said they finished as
    completed, so a merely-intended session ('I'll do my stretch later')
    can't be logged as done -- the call is refused with a helpful error
    otherwise. UI-driven calls don't need either to be meaningful; pass
    completed=true and any short note. Returns updated streak and any new
    milestones to celebrate."""
    if activity_type not in ("stretch", "meditation"):
        return {"error": "activity_type must be 'stretch' or 'meditation' (memory games log themselves; other activities use log_activity)."}
    guard_error = _completion_guard_error(completed, user_statement, minutes)
    if guard_error:
        return {"error": guard_error}
    u = store.get_user(user_id)
    day = _today(on_date)
    new = _log(u, activity_type, minutes, day, {"session_id": session_id} if session_id else None)
    _clear_matching_plan(u, activity_type, day.isoformat())
    store.save_user(u)
    s = progress.streaks(u["activities"], day)
    say = f"Well done, {u['name']}."
    if new:
        say += " " + " ".join(m["celebration"] for m in new)
    return {"logged": True, "streak": s, "new_milestones": new, "say": say}


@mcp.tool()
def log_activity(activity: str, minutes: float, completed: bool, user_statement: str, user_id: str = "demo", feeling: str | None = None, on_date: str | None = None) -> dict:
    """Log a self-reported activity that doesn't have its own guided session:
    a walk, a bike ride, a stationary bike ride, gardening, dancing,
    swimming, or any other activity by name (for example 'yoga'). Counts
    toward the streak, weekly goal, and milestones just like a stretch or
    meditation. feeling is optional: 'happy', 'okay', or 'tired'. completed
    and user_statement are for Nova's conversational path only: pass the
    person's exact words as user_statement and whether they actually said
    they'd finished as completed, so stated intent ('I'm going to walk
    later') can't be logged as if it already happened -- the call is
    refused with a helpful error otherwise. UI-driven calls (the Log an
    Activity screen, a self-logged timer's 'I'm done') don't need either
    to be meaningful; pass completed=true and any short note."""
    activity_key = _slugify_activity(activity)
    guard_error = _completion_guard_error(completed, user_statement, minutes)
    if guard_error:
        return {"error": guard_error}
    u = store.get_user(user_id)
    day = _today(on_date)
    details = {"feeling": feeling} if feeling else None
    new = _log(u, activity_key, minutes, day, details)
    _clear_matching_plan(u, activity_key, day.isoformat())
    store.save_user(u)
    s = progress.streaks(u["activities"], day)
    say = f"Nice work, {u['name']}! I've logged your {activity_key.replace('_', ' ')}."
    if new:
        say += " " + " ".join(m["celebration"] for m in new)
    return {"logged": True, "activity": activity_key, "streak": s, "new_milestones": new, "say": say}


@mcp.tool()
def log_chat_game(game_name: str, minutes: float, user_id: str = "demo", on_date: str | None = None) -> dict:
    """Record a free-form talking game actually played with Vera in
    conversation -- 20 Questions, a riddle, trivia, word association,
    would you rather, the alphabet game, or similar -- once it's actually
    finished or after a few real rounds. Never call this for a game that
    was only discussed, explained, or asked about, not played. game_name
    is a short label like '20 Questions' or 'Animal riddles'; minutes is
    your honest estimate of how long it ran. Counts toward the streak,
    weekly goal, and milestones the same as any other activity."""
    name = game_name.strip() or "a talking game"
    u = store.get_user(user_id)
    day = _today(on_date)
    new = _log(u, "chat_game", max(minutes, 0.5), day, {"game_name": name})
    store.save_user(u)
    s = progress.streaks(u["activities"], day)
    say = f"That was fun, {u['name']}! I've logged {name}."
    if new:
        say += " " + " ".join(m["celebration"] for m in new)
    return {"logged": True, "game_name": name, "streak": s, "new_milestones": new, "say": say}


@mcp.tool()
def plan_activity(activity: str, user_id: str = "demo", when: str | None = None, on_date: str | None = None) -> dict:
    """Save that the person said they intend to do an activity -- not yet
    completed, like 'I'm going to walk later' or 'maybe I'll meditate
    tonight'. Replaces any existing plan for the same activity today.
    Vera will ask about it on the next proactive greeting or later the
    same day ('Did you get your walk in today?') instead of logging it
    now. Never used to shame a plan that didn't happen -- it just quietly
    stops being brought up once the day ends."""
    activity_key = _slugify_activity(activity)
    u = store.get_user(user_id)
    day_iso = _today(on_date).isoformat()
    u.setdefault("planned_activities", [])
    u["planned_activities"] = [p for p in u["planned_activities"] if p["planned_on"] == day_iso]  # quietly drop stale plans
    _clear_matching_plan(u, activity_key, day_iso)
    plan = {
        "id": family.new_id(),
        "activity": activity_key,
        "activity_label": activity.strip(),
        "when": when,
        "planned_on": day_iso,
    }
    u["planned_activities"].append(plan)
    store.save_user(u)
    return {"plan": plan}


@mcp.tool()
def get_planned_activities(user_id: str = "demo", on_date: str | None = None) -> dict:
    """Today's planned-but-not-yet-done activities (stated intent that
    hasn't been logged), for the proactive greeting to naturally ask
    about -- 'Did you get your walk in today?' Plans from a previous day
    are never returned; they expire quietly rather than being raised as a
    missed commitment."""
    u = store.get_user(user_id)
    day_iso = _today(on_date).isoformat()
    return {"planned": [p for p in u.get("planned_activities", []) if p["planned_on"] == day_iso]}


# ---------- Fitness log ----------

@mcp.tool()
def get_fitness_log(user_id: str = "demo", days: int = 28, on_date: str | None = None) -> dict:
    """Activity calendar for the on screen fitness log (one entry per day, oldest
    first), plus totals, streak, this week's goal progress, and earned badges.
    calendar_weeks is the same history grouped into 5 Sunday-Saturday rows for
    the Progress screen's calendar grid; badges_summary collapses a repeatable
    badge (like Weekly Goal Met) into one card with a count instead of one per
    time it was earned."""
    u = store.get_user(user_id)
    day = _today(on_date)
    acts = u["activities"]
    totals: dict[str, int] = {}
    for a in acts:
        totals[a["type"]] = totals.get(a["type"], 0) + 1
    return {
        "name": u["name"],
        "calendar": progress.calendar(acts, day, max(7, min(90, days))),
        "calendar_weeks": progress.calendar_weeks(acts, day),
        "totals": totals,
        "total_minutes": round(sum(a["minutes"] for a in acts)),
        "streak": progress.streaks(acts, day),
        "week": progress.week_summary(acts, day, u["weekly_goal_days"]),
        "milestones": u["milestones"],
        "badges_summary": progress.badge_summary(u["milestones"]),
    }


@mcp.tool()
def get_day_detail(user_id: str = "demo", on_date: str | None = None) -> dict:
    """Everything that happened on one day -- for tapping a square on the
    Progress calendar: activities logged (minutes, feeling, game scores),
    cheers that played, and any badges newly earned that day."""
    u = store.get_user(user_id)
    return progress.day_detail(u, _today(on_date))


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


@mcp.tool()
def get_engagement_trends(user_id: str = "demo", on_date: str | None = None) -> dict:
    """Gentle, descriptive engagement trends for the cognitive games this
    person has played recently -- accuracy and pace, compared to the month
    before. For the Progress screen and caregiver dashboard. Never a
    diagnosis, an alert, or a health claim -- just a warm, plain-language
    observation like 'Memory game scores steady this month.'"""
    u = store.get_user(user_id)
    return {"trends": engagement.game_trends(u["activities"], _today(on_date))}


# ---------- Family Cheers ----------

@mcp.tool()
def list_family(user_id: str = "demo") -> dict:
    """List this person's family members, each with their private cheer
    record link's token and how many unlocked cheers of theirs are still
    waiting to play (unplayed_count), for the caregiver dashboard."""
    u = store.get_user(user_id)
    out = []
    for m in u.get("family", []):
        unplayed = sum(1 for c in u.get("cheers", []) if c["family_id"] == m["id"] and c["status"] == "unlocked")
        out.append({**m, "unplayed_count": unplayed})
    return {"family": out}


@mcp.tool()
def add_family_member(name: str, phone: str, nickname: str | None = None, user_id: str = "demo") -> dict:
    """Add a family member who can record cheers for this person -- just a
    name and phone number. nickname is optional: a guess at what this
    family member calls the person (e.g. 'Grandma'), shown as a starting
    point until the family member sets their own on their first visit.
    Returns their record, including the token for their private, no-login
    record-page link (the caregiver dashboard turns this into a 'Text
    invite' sms: link and a copyable URL)."""
    u = store.get_user(user_id)
    u.setdefault("family", [])
    member = {
        "id": family.new_id(),
        "name": name.strip(),
        "phone": phone.strip(),
        "nickname": (nickname or "").strip() or None,
        "relationship": None,
        "email": None,
        "email_opt_in": False,
        "onboarded": False,
        "low_queue_notified_at": None,
        "token": family.new_token(),
    }
    u["family"].append(member)
    store.save_user(u)
    return {"member": member}


@mcp.tool()
def update_family_member(family_id: str, user_id: str = "demo", name: str | None = None, relationship: str | None = None, nickname: str | None = None, email: str | None = None, email_opt_in: bool | None = None) -> dict:
    """Update a family member's own details -- their first-visit setup (name
    confirmed, relationship, what they call the person, email) or a later
    edit. Only given fields change. Setting a relationship marks them as
    onboarded, so their next visit skips straight to recording."""
    u = store.get_user(user_id)
    member = next((m for m in u.get("family", []) if m["id"] == family_id), None)
    if not member:
        return {"error": "Family member not found."}
    if name is not None:
        member["name"] = name.strip()
    if relationship is not None:
        member["relationship"] = relationship.strip()
        member["onboarded"] = True
    if nickname is not None:
        member["nickname"] = nickname.strip() or None
    if email is not None:
        member["email"] = email.strip() or None
    if email_opt_in is not None:
        member["email_opt_in"] = email_opt_in
    store.save_user(u)
    return {"member": member}


@mcp.tool()
def remove_family_member(family_id: str, user_id: str = "demo") -> dict:
    """Remove a family member; their record link stops working."""
    u = store.get_user(user_id)
    before = len(u.get("family", []))
    u["family"] = [m for m in u.get("family", []) if m["id"] != family_id]
    store.save_user(u)
    return {"removed": len(u["family"]) < before}


@mcp.tool()
def resolve_family_token(token: str) -> dict:
    """Resolve a family member's private record-page token to their
    user_id and own record -- the record page has no other way to know
    who they are or who they're recording for. The record page shows the
    first-visit welcome/setup screen when onboarded is false, and skips
    straight to suggestions/recording once it's true."""
    user_id, member = store.find_family_member(token)
    if not user_id:
        return {"error": "Invalid or expired link."}
    return {"user_id": user_id, "member": member}


@mcp.tool()
def upcoming_milestones(user_id: str = "demo", on_date: str | None = None) -> dict:
    """Milestones this person is one step away from, each with a ready-made
    'almost there' nudge for the caregiver dashboard to show family members."""
    u = store.get_user(user_id)
    day = _today(on_date)
    items = progress.upcoming(u, day)
    for item in items:
        item["nudge"] = (
            f"{u['name']} is {item['distance_label']} from their {item['title']}! "
            "Record a cheer and Vera will play it the moment they get there."
        )
    return {"upcoming": items}


_ANYTIME_SCRIPTS = [
    "Keep going, I'm so proud of you.",
    "Hope you're having a beautiful day.",
    "Way to go playing all the games today!",
]
_ACTIVITY_SCRIPTS = {
    "walk": "I hope you have a nice walk!",
    "bike": "I hope you have a nice bike ride!",
    "stationary_bike": "Enjoy your ride!",
    "gardening": "Have fun out in the garden!",
    "dancing": "Dance like nobody's watching!",
    "swimming": "Enjoy your swim!",
    "stretch": "Enjoy your stretching!",
    "meditation": "Enjoy your meditation, {called}.",
}


@mcp.tool()
def get_cheer_prompts(user_id: str = "demo", on_date: str | None = None) -> dict:
    """Ready-made cheer scripts for the family link page: one per milestone
    the person is close to ('coming_up', tagged to that milestone), three
    fixed 'anytime' lines, and one per activity type they actually do
    ('activity', tagged to that activity type) -- generated from their
    real data so every suggestion is genuinely relevant."""
    u = store.get_user(user_id)
    day = _today(on_date)
    called = u["name"].split()[0]

    coming_up = [
        {"cheer_type": "milestone", "target": m["id"], "script": f"Congrats on your {m['title'].lower()}!", "note": f"{called} is {m['distance_label']}"}
        for m in progress.upcoming(u, day)
    ]
    anytime = [{"cheer_type": "anytime", "target": None, "script": s} for s in _ANYTIME_SCRIPTS]
    counts = Counter(a["type"] for a in u["activities"])
    activity = [
        {"cheer_type": "activity", "target": t, "script": _ACTIVITY_SCRIPTS.get(t, f"Enjoy your {t.replace('_', ' ')}, {called}!").format(called=called)}
        for t, _ in counts.most_common(3)
        if t not in {"memory_game", "matching_game", "saying_game", "category_game"}
    ]
    return {"coming_up": coming_up, "anytime": anytime, "activity": activity}


def _initial_cheer_status(user: dict, cheer_type: str, target: str | None) -> str:
    if cheer_type == "milestone":
        return "unlocked" if target in {m["id"] for m in user["milestones"]} else "locked"
    if cheer_type == "activity":
        return "unlocked" if any(a["type"] == target for a in user["activities"]) else "locked"
    return "locked"  # anytime: unlocks on the person's next completed activity


@mcp.tool()
def add_cheer(family_id: str, media_type: str, file: str, duration_seconds: float, user_id: str = "demo",
              cheer_type: str = "anytime", target: str | None = None, photo_file: str | None = None,
              storage: str = "local", on_date: str | None = None) -> dict:
    """Register a cheer that's already been uploaded. cheer_type is
    'milestone' (target is a milestone id), 'activity' (target is an
    activity type), or 'anytime' (no target). file is the saved filename
    (local) or S3 object key (storage='s3'); photo_file likewise for a
    'voice + photo' cheer's picture. Rejects anything over 15 seconds.
    Starts locked unless its condition is already true (the milestone's
    already earned, or this is an activity cheer for something already
    logged) -- otherwise it unlocks the moment that happens."""
    if duration_seconds > family.MAX_CHEER_SECONDS + 1:  # +1s grace for encoder/clock rounding
        return {"error": f"Cheers are {family.MAX_CHEER_SECONDS} seconds max."}
    if cheer_type not in ("milestone", "activity", "anytime"):
        return {"error": "cheer_type must be 'milestone', 'activity', or 'anytime'."}
    u = store.get_user(user_id)
    members = u.get("family", [])
    member = next((m for m in members if m["id"] == family_id), None)
    cheer = {
        "id": family.new_id(),
        "family_id": family_id,
        "family_name": family.display_name(member, u["name"].split()[0]),
        "cheer_type": cheer_type,
        "target": target,
        "media_type": media_type,
        "file": file,
        "photo_file": photo_file,
        "storage": storage,
        "duration_seconds": duration_seconds,
        "recorded_on": _today(on_date).isoformat(),
        "activities_at_recording": len(u["activities"]),
        "status": _initial_cheer_status(u, cheer_type, target),
        "played_on": None,
    }
    u.setdefault("cheers", [])
    u["cheers"].append(cheer)
    store.save_user(u)
    cheer["url"] = family.cheer_media_url(cheer)
    cheer["photo_url"] = family.cheer_photo_url(cheer)
    # The "X of 5 sent" goal is per family member, not a total across
    # everyone who's ever recorded a cheer for this person -- a brand new
    # family member's first cheer must read "1 of 5", not however many
    # cheers other family members (or seeded demo data) happen to have.
    sent_count = sum(1 for c in u["cheers"] if c["family_id"] == family_id)
    return {"cheer": cheer, "sent_count": sent_count, "goal": family.CHEER_GOAL}


@mcp.tool()
def list_cheers(user_id: str = "demo", status: str | None = None, cheer_type: str | None = None, target: str | None = None, family_id: str | None = None) -> dict:
    """List this person's cheers, optionally filtered by status
    ('locked'/'unlocked'/'played'), cheer_type, target, and/or family_id.
    Each cheer includes a fresh playback url (and photo_url, if any) when
    stored in S3."""
    u = store.get_user(user_id)
    cheers = u.get("cheers", [])
    if status is not None:
        cheers = [c for c in cheers if c["status"] == status]
    if cheer_type is not None:
        cheers = [c for c in cheers if c["cheer_type"] == cheer_type]
    if target is not None:
        cheers = [c for c in cheers if c["target"] == target]
    if family_id is not None:
        cheers = [c for c in cheers if c["family_id"] == family_id]
    for c in cheers:
        c["url"] = family.cheer_media_url(c)
        c["photo_url"] = family.cheer_photo_url(c)
    return {"cheers": cheers}


@mcp.tool()
def next_cheer(user_id: str = "demo", on_date: str | None = None) -> dict:
    """The next unlocked cheer due to actually play -- for a milestone
    moment, a workout's step-break pause, or the home shelf -- respecting
    the daily cap (VERA_MAX_CHEERS_PER_DAY, default 2) and rotating across
    family members so one person's cheers don't all play in a row. Returns
    {"cheer": null} if nothing's due right now."""
    u = store.get_user(user_id)
    day = _today(on_date)
    played_today = [c for c in u.get("cheers", []) if c["status"] == "played" and c.get("played_on") == day.isoformat()]
    if len(played_today) >= MAX_CHEERS_PER_DAY:
        return {"cheer": None}
    unlocked = sorted((c for c in u.get("cheers", []) if c["status"] == "unlocked"), key=lambda c: c["recorded_on"])
    if not unlocked:
        return {"cheer": None}
    last_family_id = played_today[-1]["family_id"] if played_today else None
    pick = next((c for c in unlocked if c["family_id"] != last_family_id), unlocked[0])
    pick["url"] = family.cheer_media_url(pick)
    pick["photo_url"] = family.cheer_photo_url(pick)
    return {"cheer": pick}


@mcp.tool()
def mark_cheer_played(cheer_id: str, user_id: str = "demo", on_date: str | None = None) -> dict:
    """Mark a cheer as played, so it moves from the shelf's unlocked list
    to the replayable 'played' list and next_cheer won't offer it again."""
    u = store.get_user(user_id)
    found = False
    for c in u.get("cheers", []):
        if c["id"] == cheer_id:
            c["status"] = "played"
            c["played_on"] = _today(on_date).isoformat()
            found = True
    store.save_user(u)
    return {"ok": found}


@mcp.tool()
def delete_cheer(cheer_id: str, user_id: str = "demo") -> dict:
    """Delete a cheer (available to the user or the caregiver)."""
    u = store.get_user(user_id)
    before = len(u.get("cheers", []))
    u["cheers"] = [c for c in u.get("cheers", []) if c["id"] != cheer_id]
    store.save_user(u)
    return {"deleted": len(u["cheers"]) < before}


@mcp.tool()
def check_family_alerts(user_id: str = "demo") -> dict:
    """Family members whose unlocked-cheer queue just dropped to 1 or 0 and
    haven't been emailed at this level yet (email_opt_in required). Call
    mark_alert_sent right after actually sending, so it isn't repeated."""
    u = store.get_user(user_id)
    called = u["name"].split()[0]
    alerts = []
    for m in u.get("family", []):
        if not (m.get("email") and m.get("email_opt_in")):
            continue
        unplayed = sum(1 for c in u.get("cheers", []) if c["family_id"] == m["id"] and c["status"] == "unlocked")
        if unplayed <= 1 and m.get("low_queue_notified_at") != unplayed:
            nickname = family.display_name(m, called)
            alerts.append({
                "family_id": m["id"],
                "email": m["email"],
                "token": m["token"],
                "unplayed": unplayed,
                "message": f"{nickname} has heard your cheers! You have {unplayed} left in the queue. Record another?",
            })
    return {"alerts": alerts}


@mcp.tool()
def mark_alert_sent(family_id: str, unplayed: int, user_id: str = "demo") -> dict:
    """Record that a running-low alert was just sent at this unplayed
    count, so check_family_alerts doesn't repeat it until the count changes
    again."""
    u = store.get_user(user_id)
    member = next((m for m in u.get("family", []) if m["id"] == family_id), None)
    if not member:
        return {"ok": False}
    member["low_queue_notified_at"] = unplayed
    store.save_user(u)
    return {"ok": True}


# ---------- Simulated living room display ----------

@mcp.tool()
def handoff_session_to_display(user_id: str = "demo", display: str = "tv", session: dict | None = None) -> dict:
    """Hand the active session (an exercise routine, a meditation, or the
    progress screen) from the main screen to a simulated display, such as
    the Living Room TV -- call this when the person asks to 'put this on
    the TV' or similar ('let's do chair yoga in the living room'). session
    is a small, free-form snapshot of what's currently playing (title,
    current step, progress) that the display mirrors; pass session=None to
    bring the session back to the main screen."""
    u = store.get_user(user_id)
    u["display_session"] = (
        {"display": display, "session": session, "updated_at": datetime.now().isoformat()}
        if session is not None else None
    )
    store.save_user(u)
    return {"ok": True, "active": session is not None}


@mcp.tool()
def get_display_session(user_id: str = "demo") -> dict:
    """The session currently handed off to a simulated display, if any --
    polled by the display itself (and by the main screen, to know whether
    to show 'Now playing on Living Room TV') to mirror playback."""
    u = store.get_user(user_id)
    return u.get("display_session") or {"display": None, "session": None, "updated_at": None}


def build_app():
    """Streamable HTTP ASGI app with CORS (so the browser based Alexa+
    simulator can call it) and, once VERA_MCP_TOKEN is set, a bearer-token
    gate in front of everything."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.middleware.cors import CORSMiddleware
    from starlette.responses import JSONResponse

    class BearerAuthMiddleware(BaseHTTPMiddleware):
        """Requires `Authorization: Bearer <VERA_MCP_TOKEN>` on every
        request once that env var is set -- this server has no other
        access control of its own, so once it's reachable from the public
        internet (behind the Caddy reverse proxy in production) this is
        what stops a stranger from calling its tools directly. A no-op
        when VERA_MCP_TOKEN is unset, same "optional unless configured"
        pattern as everything else in this app, so local dev (and MCP
        Inspector) still needs no token."""

        def __init__(self, app, token: str | None):
            super().__init__(app)
            self.token = token

        async def dispatch(self, request, call_next):
            if self.token and request.headers.get("authorization") != f"Bearer {self.token}":
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            return await call_next(request)

    app = mcp.streamable_http_app()
    app.add_middleware(BearerAuthMiddleware, token=os.environ.get("VERA_MCP_TOKEN", "").strip() or None)
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
