"""Web app for Vera: an Echo Show style Alexa+ simulator in the browser.

Serves the static frontend and bridges it to the Vera MCP server. Every
activity screen (memory game, chair stretch, meditation, fitness log) calls
an MCP tool through this bridge, same as a real Alexa+ integration would.

Run (with the Vera MCP server already running on :8000), from the project root:
    python -m web.app
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import mcp_bridge

try:
    from . import bedrock_chat
except ImportError:
    bedrock_chat = None

HOST = os.environ.get("WEB_HOST", "127.0.0.1")
PORT = int(os.environ.get("WEB_PORT", "8080"))
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Vera Web Simulator")


@app.get("/api/tools")
async def api_list_tools():
    return await mcp_bridge.list_tools()


@app.post("/api/tool/{name}")
async def api_call_tool(name: str, arguments: dict | None = None):
    try:
        return await mcp_bridge.call_tool(name, arguments or {})
    except mcp_bridge.ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/chat")
async def api_chat(payload: dict):
    if bedrock_chat is None:
        raise HTTPException(status_code=503, detail="Bedrock chat layer not configured.")
    message = payload.get("message", "")
    history = payload.get("history", [])
    user_id = payload.get("user_id", "demo")
    try:
        result = await bedrock_chat.converse(message, history, user_id)
    except bedrock_chat.ChatError as e:
        return JSONResponse(status_code=502, content={"error": str(e)})
    return result


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    print(f"Vera web simulator on http://{HOST}:{PORT}")
    uvicorn.run("web.app:app", host=HOST, port=PORT)
