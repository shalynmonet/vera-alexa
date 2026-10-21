"""End to end: start the real server over Streamable HTTP and call tools with
the official MCP client, the same way Alexa+ (or the web simulator) would.

Split into a few focused tests (each starting its own short-lived server)
rather than one giant sequential flow -- keeps any single test's tool-call
count down, which matters on this project's Windows dev environment where a
very long sequence of calls in one session has occasionally hit a transient
read timeout."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parent.parent


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _data(result):
    return json.loads(result.content[0].text)


@asynccontextmanager
async def _server_session(tmp_path):
    port = _free_port()
    env = {**os.environ, "VERA_PORT": str(port), "VERA_DATA": str(tmp_path / "vera.json")}
    # stdout/stderr go to DEVNULL, not PIPE: a PIPE nobody reads fills its OS
    # buffer after enough log lines (uvicorn logs one per request) and then
    # blocks the server process on its next write -- a real, reproducible
    # hang on a long enough test, not just "transient flakiness". See
    # FRICTION_LOG.md.
    proc = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), 0.2).close()
                break
            except OSError:
                time.sleep(0.2)
        async with streamable_http_client(f"http://127.0.0.1:{port}/mcp") as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                yield s
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(5)


def test_games_and_activities_flow(tmp_path):
    async def run():
        async with _server_session(tmp_path) as s:
            names = {t.name for t in (await s.list_tools()).tools}
            assert {"start_memory_game", "submit_memory_answer", "start_stretch_routine", "start_meditation",
                    "log_completion", "get_fitness_log", "get_streak", "check_milestones", "get_daily_summary"} <= names

            await s.call_tool("set_profile", {"name": "Rose"})
            game = _data(await s.call_tool("start_memory_game", {"difficulty": 3}))
            res = _data(await s.call_tool("submit_memory_answer", {"answer": " ".join(game["words"])}))
            assert res["perfect"]
            assert {"first_session", "memory_perfect"} <= {m["id"] for m in res["new_milestones"]}

            st = _data(await s.call_tool("start_stretch_routine", {}))
            assert any(step.get("check_in") for step in st["steps"])
            done = _data(await s.call_tool("log_completion", {"activity_type": "stretch", "minutes": 8}))
            assert done["streak"]["current"] == 1

            log = _data(await s.call_tool("get_fitness_log", {}))
            assert log["totals"] == {"memory_game": 1, "stretch": 1}
            summ = _data(await s.call_tool("get_daily_summary", {}))
            assert "Rose completed 2 activities today" in summ["summary"]

            sessions = _data(await s.call_tool("list_sessions", {}))
            assert {g["id"] for g in sessions["games"]} == {
                "memory_game", "matching_game", "saying_game", "category_game",
            }
            assert {r["id"] for r in sessions["stretch_routines"]} == {
                "morning_chair_stretch", "seated_strength", "balance", "gentle_walking",
            }
            assert all(not r["available"] for r in sessions["stretch_routines"])
            med_ids = {m["id"] for m in sessions["meditations"]}
            assert "healing_affirmations" in med_ids

            profiles = _data(await s.call_tool("list_profiles", {}))
            assert {"user_id": "demo", "name": "Rose"} in profiles["profiles"]
            created = _data(await s.call_tool("create_profile", {"name": "Tom"}))
            assert created["user_id"] == "tom"
            profiles = _data(await s.call_tool("list_profiles", {}))
            assert {p["user_id"] for p in profiles["profiles"]} == {"demo", "tom"}

            walk = _data(await s.call_tool("log_activity", {"activity": "walk", "minutes": 20, "feeling": "happy"}))
            assert walk["activity"] == "walk"
            assert "first_walk" in {m["id"] for m in walk["new_milestones"]}
            custom = _data(await s.call_tool("log_activity", {"activity": "Evening Yoga!", "minutes": 15}))
            assert custom["activity"] == "evening_yoga"

            match = _data(await s.call_tool("start_matching_game", {"difficulty": 3}))
            assert len(match["cards"]) == 6
            match_res = _data(await s.call_tool("submit_matching_result", {"attempts": 3}))
            assert match_res["perfect"]

            saying = _data(await s.call_tool("start_saying_game", {"difficulty": 3}))
            assert saying["total"] == 3
            # The correct ending is kept server-side, so just answer with
            # whatever's offered and walk the round to completion.
            saying_res = _data(await s.call_tool("submit_saying_answer", {"choice": saying["choices"][0]}))
            while not saying_res["done"]:
                saying_res = _data(await s.call_tool("submit_saying_answer", {"choice": saying_res["choices"][0]}))
            assert saying_res["total"] == 3

            category = _data(await s.call_tool("start_category_game", {"difficulty": 3}))
            items = {"fruits": "apple banana orange", "animals": "dog cat horse",
                     "colors": "red blue green", "furniture": "chair table sofa",
                     "vegetables": "carrot potato tomato"}[category["category"]]
            category_res = _data(await s.call_tool("submit_category_answer", {"answer": items}))
            assert category_res["count"] == 3

            tried_all = _data(await s.call_tool("get_fitness_log", {}))
            assert "tried_every_game" in {m["id"] for m in tried_all["milestones"]}
            summary = _data(await s.call_tool("get_daily_summary", {}))
            memory_entry = next(a for a in summary["activities_today"] if a["type"] == "memory_game")
            assert memory_entry["details"]["response_seconds"] >= 0

            trends = _data(await s.call_tool("get_engagement_trends", {}))["trends"]
            memory_trend = next(t for t in trends if t["game"] == "memory_game")
            assert "just getting started" in memory_trend["label"]

    asyncio.run(run())


def test_memories_flow(tmp_path):
    async def run():
        async with _server_session(tmp_path) as s:
            await s.call_tool("set_profile", {"name": "Rose"})
            saved = _data(await s.call_tool("remember_fact", {
                "fact": "Her granddaughter Mia has a volleyball game Saturday",
                "category": "family",
            }))
            assert saved["saved"]
            refused = _data(await s.call_tool("remember_fact", {"fact": "Started a new blood pressure medication"}))
            assert not refused["saved"]
            mems = _data(await s.call_tool("get_memories", {}))
            assert len(mems["memories"]) == 1
            assert "Mia" in mems["memories"][0]["fact"]

    asyncio.run(run())


def test_family_cheers_flow(tmp_path):
    async def run():
        async with _server_session(tmp_path) as s:
            await s.call_tool("set_profile", {"name": "Rose"})

            # Earn first_session/memory_perfect so a milestone cheer attached
            # to one of them can start out already unlocked.
            game = _data(await s.call_tool("start_memory_game", {"difficulty": 3}))
            await s.call_tool("submit_memory_answer", {"answer": " ".join(game["words"])})

            added = _data(await s.call_tool("add_family_member", {
                "name": "Jake", "phone": "+15551234567", "nickname": "Grandma",
            }))
            member = added["member"]
            assert member["token"] and member["phone"] == "+15551234567"
            assert member["onboarded"] is False

            family_list = _data(await s.call_tool("list_family", {}))
            assert family_list["family"][0]["unplayed_count"] == 0

            resolved = _data(await s.call_tool("resolve_family_token", {"token": member["token"]}))
            assert resolved["user_id"] == "demo" and resolved["member"]["id"] == member["id"]
            bad = _data(await s.call_tool("resolve_family_token", {"token": "not-a-real-token"}))
            assert "error" in bad

            # First-visit onboarding: the family member's own answers.
            updated = _data(await s.call_tool("update_family_member", {
                "family_id": member["id"], "relationship": "Grandson", "nickname": "Nana",
                "email": "jake@example.com", "email_opt_in": True,
            }))["member"]
            assert updated["onboarded"] is True and updated["nickname"] == "Nana"

            upcoming = _data(await s.call_tool("upcoming_milestones", {}))
            assert isinstance(upcoming["upcoming"], list)

            prompts = _data(await s.call_tool("get_cheer_prompts", {}))
            assert len(prompts["anytime"]) == 3

            # Rejected: over the 15 second cap.
            too_long = _data(await s.call_tool("add_cheer", {
                "family_id": member["id"], "media_type": "video", "file": "x.webm",
                "duration_seconds": 25, "cheer_type": "anytime",
            }))
            assert "error" in too_long

            # Milestone cheer for one already earned -- starts unlocked.
            milestone_cheer = _data(await s.call_tool("add_cheer", {
                "family_id": member["id"], "media_type": "video", "file": "a.webm",
                "duration_seconds": 10, "cheer_type": "milestone", "target": "memory_perfect",
            }))["cheer"]
            assert milestone_cheer["status"] == "unlocked"
            assert milestone_cheer["family_name"] == "Nana"

            # Anytime cheer -- always starts locked, unlocks on the next
            # completed activity after it was recorded.
            anytime_cheer = _data(await s.call_tool("add_cheer", {
                "family_id": member["id"], "media_type": "audio", "file": "b.webm",
                "duration_seconds": 8, "cheer_type": "anytime",
            }))["cheer"]
            assert anytime_cheer["status"] == "locked"

            unlocked = _data(await s.call_tool("list_cheers", {"status": "unlocked"}))["cheers"]
            assert {c["file"] for c in unlocked} == {"a.webm"}
            locked = _data(await s.call_tool("list_cheers", {"status": "locked"}))["cheers"]
            assert {c["file"] for c in locked} == {"b.webm"}

            await s.call_tool("log_activity", {"activity": "walk", "minutes": 10})
            unlocked_after = _data(await s.call_tool("list_cheers", {"status": "unlocked"}))["cheers"]
            assert {c["file"] for c in unlocked_after} == {"a.webm", "b.webm"}

            # next_cheer: oldest unlocked first, respecting the daily cap.
            first = _data(await s.call_tool("next_cheer", {}))["cheer"]
            assert first["file"] == "a.webm"
            await s.call_tool("mark_cheer_played", {"cheer_id": first["id"]})

            second = _data(await s.call_tool("next_cheer", {}))["cheer"]
            assert second["file"] == "b.webm"
            await s.call_tool("mark_cheer_played", {"cheer_id": second["id"]})

            # A third unlocked cheer exists, but the default daily cap (2) is hit.
            third_cheer = _data(await s.call_tool("add_cheer", {
                "family_id": member["id"], "media_type": "video", "file": "c.webm",
                "duration_seconds": 5, "cheer_type": "milestone", "target": "first_session",
            }))["cheer"]
            assert third_cheer["status"] == "unlocked"
            capped = _data(await s.call_tool("next_cheer", {}))
            assert capped["cheer"] is None

            played = _data(await s.call_tool("list_cheers", {"status": "played"}))["cheers"]
            assert {c["file"] for c in played} == {"a.webm", "b.webm"}

            deleted = _data(await s.call_tool("delete_cheer", {"cheer_id": third_cheer["id"]}))
            assert deleted["deleted"]

            # Running-low alert: Jake is down to 0 unplayed and opted into email.
            alerts = _data(await s.call_tool("check_family_alerts", {}))["alerts"]
            assert len(alerts) == 1 and alerts[0]["family_id"] == member["id"] and alerts[0]["unplayed"] == 0
            await s.call_tool("mark_alert_sent", {"family_id": member["id"], "unplayed": 0})
            alerts_after = _data(await s.call_tool("check_family_alerts", {}))["alerts"]
            assert alerts_after == []

            removed = _data(await s.call_tool("remove_family_member", {"family_id": member["id"]}))
            assert removed["removed"]
            family_after = _data(await s.call_tool("list_family", {}))
            assert family_after["family"] == []

    asyncio.run(run())
