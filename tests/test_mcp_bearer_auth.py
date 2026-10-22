"""The MCP server's bearer-token gate (server.py's BearerAuthMiddleware,
wired in via VERA_MCP_TOKEN) -- the one thing standing between the public
internet and this server's tools once it's reachable behind Caddy in
production. A separate short-lived server per test (same pattern as
test_mcp_client.py's _server_session) since this one needs VERA_MCP_TOKEN
set, which the shared fixture deliberately leaves unset."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "test-bearer-token"


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@asynccontextmanager
async def _token_gated_server(tmp_path):
    port = _free_port()
    env = {**os.environ, "VERA_PORT": str(port), "VERA_DATA": str(tmp_path / "vera.json"), "VERA_MCP_TOKEN": TOKEN}
    proc = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), 0.2).close()
                break
            except OSError:
                time.sleep(0.2)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(5)


def test_request_without_the_bearer_token_is_rejected(tmp_path):
    async def run():
        async with _token_gated_server(tmp_path) as url:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                    headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json"},
                )
                assert resp.status_code == 401

    asyncio.run(run())


def test_request_with_the_wrong_bearer_token_is_rejected(tmp_path):
    async def run():
        async with _token_gated_server(tmp_path) as url:
            async with httpx.AsyncClient(headers={"Authorization": "Bearer not-the-right-token"}) as client:
                resp = await client.post(
                    url,
                    json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                    headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json"},
                )
                assert resp.status_code == 401

    asyncio.run(run())


def test_request_with_the_correct_bearer_token_is_allowed_through(tmp_path):
    async def run():
        async with _token_gated_server(tmp_path) as url:
            authed_client = httpx.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"})
            async with streamable_http_client(url, http_client=authed_client) as (r, w, _):
                async with ClientSession(r, w) as s:
                    await s.initialize()
                    result = await s.call_tool("set_profile", {"name": "Rose"})
                    data = json.loads(result.content[0].text)
                    assert data["name"] == "Rose"

    asyncio.run(run())
