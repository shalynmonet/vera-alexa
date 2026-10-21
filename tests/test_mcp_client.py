"""End to end: start the real server over Streamable HTTP and call tools with
the official MCP client, the same way Alexa+ (or the web simulator) would."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
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


def test_full_flow(tmp_path):
    port = _free_port()
    env = {**os.environ, "VERA_PORT": str(port), "VERA_DATA": str(tmp_path / "vera.json")}
    proc = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), 0.2).close()
                break
            except OSError:
                time.sleep(0.2)

        async def run():
            async with streamable_http_client(f"http://127.0.0.1:{port}/mcp") as (r, w, _):
                async with ClientSession(r, w) as s:
                    init = await s.initialize()
                    assert init.protocolVersion == "2025-11-25"
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
                    assert {g["id"] for g in sessions["games"]} == {"memory_game"}

                    profiles = _data(await s.call_tool("list_profiles", {}))
                    assert {"user_id": "demo", "name": "Rose"} in profiles["profiles"]

                    created = _data(await s.call_tool("create_profile", {"name": "Tom"}))
                    assert created["user_id"] == "tom"
                    profiles = _data(await s.call_tool("list_profiles", {}))
                    assert {p["user_id"] for p in profiles["profiles"]} == {"demo", "tom"}

        asyncio.run(run())
    finally:
        proc.terminate()
        proc.wait(5)
