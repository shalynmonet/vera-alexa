"""Web app for Vera: an Echo Show style Alexa+ simulator in the browser.

Serves the static frontend and bridges it to the Vera MCP server. Every
activity screen (memory game, chair stretch, meditation, fitness log) calls
an MCP tool through this bridge, same as a real Alexa+ integration would.

Run (with the Vera MCP server already running on :8000), from the project root:
    python -m web.app
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from vera import cloud_storage
from vera.family import cheer_s3_key

from . import mcp_bridge, polly_tts, ses_email

try:
    from . import bedrock_chat
except ImportError:
    bedrock_chat = None

HOST = os.environ.get("WEB_HOST", "127.0.0.1")
PORT = int(os.environ.get("WEB_PORT", "8080"))
STATIC_DIR = Path(__file__).resolve().parent / "static"
CHEER_MEDIA_DIR = Path(__file__).resolve().parent / "cheer_media"
CHEER_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

class NoCacheStaticFiles(StaticFiles):
    """Static files change constantly during development/demos; without an
    explicit Cache-Control header, browsers apply heuristic caching off
    Last-Modified and can keep serving a stale JS/CSS file for a long time.
    Force revalidation on every request instead (cheap: it's a 304 if the
    file hasn't actually changed)."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


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


@app.post("/api/greet")
async def api_greet(payload: dict):
    if bedrock_chat is None:
        raise HTTPException(status_code=503, detail="Bedrock chat layer not configured.")
    user_id = payload.get("user_id", "demo")
    try:
        result = await bedrock_chat.greet(user_id)
    except bedrock_chat.ChatError as e:
        return JSONResponse(status_code=502, content={"error": str(e)})
    return result


@app.post("/api/speak")
async def api_speak(payload: dict):
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    try:
        filename = await run_in_threadpool(polly_tts.synthesize, text)
    except polly_tts.TTSError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"url": f"/audio-cache/{filename}"}


# ---------- Family Cheers ----------

@app.get("/cheer/{token}")
async def cheer_record_page(token: str):
    """A family member's private, no-login record page. The token itself
    is only validated client-side via /api/cheer/context -- this route just
    serves the page shell for any token-shaped path."""
    return FileResponse(str(STATIC_DIR / "cheer" / "record.html"))


@app.get("/caregiver/{user_id}")
async def caregiver_dashboard_page(user_id: str):
    return FileResponse(str(STATIC_DIR / "caregiver" / "dashboard.html"))


@app.get("/api/cheer/context/{token}")
async def api_cheer_context(token: str, milestone: str | None = None):
    try:
        resolved = await mcp_bridge.call_tool("resolve_family_token", {"token": token})
        if "error" in resolved:
            return JSONResponse(status_code=404, content={"valid": False})
        user_id = resolved["user_id"]
        member = resolved["member"]
        profile = await mcp_bridge.call_tool("get_profile", {"user_id": user_id})
        upcoming = await mcp_bridge.call_tool("upcoming_milestones", {"user_id": user_id})
    except mcp_bridge.ToolError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {
        "valid": True,
        "recipient_name": profile["name"],
        "family_name": member["name"],
        "upcoming_milestones": upcoming["upcoming"],
        "default_milestone_id": milestone,
    }


@app.post("/api/cheer/upload/{token}")
async def api_cheer_upload(
    token: str,
    file: UploadFile = File(...),
    media_type: str = Form(...),
    milestone_id: str | None = Form(None),
):
    try:
        resolved = await mcp_bridge.call_tool("resolve_family_token", {"token": token})
    except mcp_bridge.ToolError as e:
        raise HTTPException(status_code=502, detail=str(e))
    if "error" in resolved:
        raise HTTPException(status_code=404, detail=resolved["error"])
    user_id = resolved["user_id"]
    member = resolved["member"]

    filename = f"{uuid.uuid4().hex}.webm"
    content = await file.read()

    storage = "local"
    if cloud_storage.enabled():
        try:
            content_type = file.content_type or ("video/webm" if media_type == "video" else "audio/webm")
            await run_in_threadpool(cloud_storage.upload_bytes, cheer_s3_key(filename), content, content_type)
            storage = "s3"
        except Exception:
            # S3 unreachable or misconfigured -- fall back to local disk
            # below rather than losing the recording.
            storage = "local"
    if storage == "local":
        (CHEER_MEDIA_DIR / filename).write_bytes(content)

    try:
        result = await mcp_bridge.call_tool("save_cheer", {
            "family_id": member["id"],
            "media_type": media_type,
            "file": filename,
            "user_id": user_id,
            "milestone_id": milestone_id or None,
            "storage": storage,
        })
    except mcp_bridge.ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@app.post("/api/cheer/notify")
async def api_cheer_notify(payload: dict, request: Request):
    """Best-effort SES email nudge; copying the record link always works
    regardless of whether this succeeds."""
    user_id = payload.get("user_id", "demo")
    family_id = payload.get("family_id")
    milestone_id = payload.get("milestone_id")

    family_res = await mcp_bridge.call_tool("list_family", {"user_id": user_id})
    member = next((m for m in family_res["family"] if m["id"] == family_id), None)
    if not member or not member.get("email"):
        raise HTTPException(status_code=400, detail="This family member has no email on file.")

    nudge_text = f"Vera would love a cheer from you for {user_id}!"
    if milestone_id:
        upcoming_res = await mcp_bridge.call_tool("upcoming_milestones", {"user_id": user_id})
        item = next((i for i in upcoming_res["upcoming"] if i["id"] == milestone_id), None)
        if item:
            nudge_text = item["nudge"]

    link = f"{str(request.base_url).rstrip('/')}/cheer/{member['token']}"
    if milestone_id:
        link += f"?milestone={milestone_id}"
    body = f"{nudge_text}\n\nRecord your cheer here: {link}"

    try:
        await run_in_threadpool(ses_email.send_nudge_email, member["email"], "A cheer for your family member", body)
    except ses_email.EmailError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"sent": True}


# Mounted before the catch-all "/" static mount below so cached audio and
# cheer recordings are reachable at /audio-cache/<hash>.mp3 and
# /cheer-media/<id>.webm.
app.mount("/audio-cache", StaticFiles(directory=str(polly_tts.CACHE_DIR)), name="audio_cache")
app.mount("/cheer-media", StaticFiles(directory=str(CHEER_MEDIA_DIR)), name="cheer_media")

app.mount("/", NoCacheStaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    print(f"Vera web simulator on http://{HOST}:{PORT}")
    uvicorn.run("web.app:app", host=HOST, port=PORT)
