"""End to end: a family cheer's occasion actually plays only at its own
moment -- before a guided session starts, when a self-timed activity
starts (or she tells Vera she's heading out), right after finishing a
game, or (unchanged) on the next completed activity for an anytime cheer
or the moment a milestone is earned. Same harness pattern as
test_mcp_client.py: a real server subprocess per test, kept focused so any
one test's call count stays low."""
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


async def _add_cheer(s, family_id, cheer_type, target=None, file="c.webm"):
    res = _data(await s.call_tool("add_cheer", {
        "family_id": family_id, "media_type": "audio", "file": file,
        "duration_seconds": 8, "cheer_type": cheer_type, "target": target,
    }))
    return res["cheer"]


def test_before_session_cheer_fires_right_when_meditation_or_stretch_starts(tmp_path):
    async def run():
        async with _server_session(tmp_path) as s:
            await s.call_tool("set_profile", {"name": "Rose"})
            member = _data(await s.call_tool("add_family_member", {"name": "Shalyn", "phone": "+15550001"}))["member"]
            meditation_cheer = await _add_cheer(s, member["id"], "before_session", "meditation", file="med.webm")
            stretch_cheer = await _add_cheer(s, member["id"], "before_session", "stretch", file="str.webm")
            assert meditation_cheer["status"] == "locked"
            assert stretch_cheer["status"] == "locked"

            # Starting the meditation is the trigger -- not anything about
            # meditations she's already done before.
            med_result = _data(await s.call_tool("start_meditation", {}))
            assert med_result["cheer"]["file"] == "med.webm"
            assert med_result["cheer"]["status"] == "played"
            # Stretch's cheer wasn't touched by starting the meditation.
            still_locked = _data(await s.call_tool("list_cheers", {"status": "locked"}))["cheers"]
            assert {c["file"] for c in still_locked} == {"str.webm"}

            stretch_result = _data(await s.call_tool("start_stretch_routine", {}))
            assert stretch_result["cheer"]["file"] == "str.webm"

    asyncio.run(run())


def test_before_activity_cheer_fires_on_timer_start_or_plan_activity(tmp_path):
    async def run():
        async with _server_session(tmp_path) as s:
            await s.call_tool("set_profile", {"name": "Rose"})
            member = _data(await s.call_tool("add_family_member", {"name": "Shalyn", "phone": "+15550001"}))["member"]
            walk_cheer = await _add_cheer(s, member["id"], "before_activity", "walk", file="walk.webm")
            bike_cheer = await _add_cheer(s, member["id"], "before_activity", "bike", file="bike.webm")
            assert walk_cheer["status"] == "locked" and bike_cheer["status"] == "locked"

            # Starting the app's own walk timer fires the walk cheer, not the bike one.
            started = _data(await s.call_tool("start_timed_activity", {"activity": "walk"}))
            assert started["cheer"]["file"] == "walk.webm"

            # Telling Vera she's heading out for a ride (plan_activity) fires the bike one.
            planned = _data(await s.call_tool("plan_activity", {"activity": "bike", "when": "now"}))
            assert planned["cheer"]["file"] == "bike.webm"

    asyncio.run(run())


def test_before_activity_wildcard_cheer_fires_for_any_simple_activity(tmp_path):
    """A "record my own" cheer saved generically for "before a walk or
    ride" (no specific target) fires for whichever one actually starts
    first."""
    async def run():
        async with _server_session(tmp_path) as s:
            await s.call_tool("set_profile", {"name": "Rose"})
            member = _data(await s.call_tool("add_family_member", {"name": "Shalyn", "phone": "+15550001"}))["member"]
            await _add_cheer(s, member["id"], "before_activity", None, file="generic.webm")

            started = _data(await s.call_tool("start_timed_activity", {"activity": "bike"}))
            assert started["cheer"]["file"] == "generic.webm"

    asyncio.run(run())


def test_after_game_cheer_fires_after_completing_a_game(tmp_path):
    async def run():
        async with _server_session(tmp_path) as s:
            await s.call_tool("set_profile", {"name": "Rose"})
            member = _data(await s.call_tool("add_family_member", {"name": "Shalyn", "phone": "+15550001"}))["member"]
            await _add_cheer(s, member["id"], "after_game", None, file="game.webm")

            game = _data(await s.call_tool("start_memory_game", {"difficulty": 3}))
            result = _data(await s.call_tool("submit_memory_answer", {"answer": " ".join(game["words"])}))
            assert result["cheer"]["file"] == "game.webm"
            assert result["cheer"]["status"] == "played"

    asyncio.run(run())


def test_occasion_cheers_never_appear_unlocked_and_respect_the_daily_cap(tmp_path):
    """The actual reported bug, end to end: a before_session cheer must
    never surface via next_cheer/the "New" list on a plain app open --
    only by actually starting that session -- and once today's 2-cheer
    cap is hit, it stays locked instead of leaking out anyway."""
    async def run():
        async with _server_session(tmp_path) as s:
            await s.call_tool("set_profile", {"name": "Rose"})
            member = _data(await s.call_tool("add_family_member", {"name": "Shalyn", "phone": "+15550001"}))["member"]
            await _add_cheer(s, member["id"], "before_session", "meditation", file="med.webm")

            # Never unlocked, never offered by next_cheer, before its moment.
            assert _data(await s.call_tool("list_cheers", {"status": "unlocked"}))["cheers"] == []
            assert _data(await s.call_tool("next_cheer", {}))["cheer"] is None

            # Use up today's 2-cheer cap with two anytime cheers played via next_cheer.
            await _add_cheer(s, member["id"], "anytime", None, file="any1.webm")
            await _add_cheer(s, member["id"], "anytime", None, file="any2.webm")
            await s.call_tool("log_activity", {"activity": "walk", "minutes": 5, "completed": True, "user_statement": "I walked"})
            for _ in range(2):
                pick = _data(await s.call_tool("next_cheer", {}))["cheer"]
                assert pick is not None
                await s.call_tool("mark_cheer_played", {"cheer_id": pick["id"]})
            assert _data(await s.call_tool("next_cheer", {}))["cheer"] is None  # cap reached

            # Now starting the meditation must NOT play the before_session
            # cheer -- the cap says no more today -- and it must stay locked
            # rather than becoming unlocked for later generic pickup.
            med_result = _data(await s.call_tool("start_meditation", {}))
            assert med_result["cheer"] is None
            still_locked = _data(await s.call_tool("list_cheers", {"status": "locked"}))["cheers"]
            assert {c["file"] for c in still_locked} == {"med.webm"}
            assert _data(await s.call_tool("list_cheers", {"status": "unlocked"}))["cheers"] == []

    asyncio.run(run())
