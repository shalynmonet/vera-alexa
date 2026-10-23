"""Web app for Vera: an Echo Show style Alexa+ simulator in the browser.

Serves the static frontend and bridges it to the Vera MCP server. Every
activity screen (memory game, chair stretch, meditation, fitness log) calls
an MCP tool through this bridge, same as a real Alexa+ integration would.

Run (with the Vera MCP server already running on :8000), from the project root:
    python -m web.app
"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from vera import cloud_storage
from vera.family import MAX_CHEER_SECONDS, cheer_s3_key

from . import auth, mcp_bridge, polly_tts, rate_limit, ses_email, sms

try:
    from . import bedrock_chat
except ImportError:
    bedrock_chat = None

HOST = os.environ.get("WEB_HOST", "127.0.0.1")
PORT = int(os.environ.get("WEB_PORT", "8080"))
STATIC_DIR = Path(__file__).resolve().parent / "static"
CHEER_MEDIA_DIR = Path(__file__).resolve().parent / "cheer_media"
CHEER_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
MAX_CHEER_BYTES = 20 * 1024 * 1024  # generous for a 15 second clip; rejects anything clearly wrong
ALLOWED_MEDIA_TYPES = {"voice", "voice_photo", "video"}
# Broad category check (not exact mimetype matching) since MediaRecorder's
# content_type varies by browser/codec, e.g. 'video/webm;codecs=vp8,opus' --
# this still blocks anything that isn't actually audio/video/image.
ALLOWED_AV_PREFIXES = ("audio/", "video/")
ALLOWED_IMAGE_PREFIXES = ("image/",)
# A saved cheer's extension has to actually match its bytes -- cheer-media
# is served by a plain StaticFiles mount, which sets Content-Type from the
# filename's extension alone, not by sniffing the file. That's always been
# fine for a live browser recording (always audio/webm or video/webm), but
# "Upload a File Instead" can hand this a real WAV/MP3/M4A/MOV, so a few
# common ones are mapped explicitly; mimetypes covers most of the rest, and
# the old fixed webm/mp4 guess is the last-resort fallback.
_EXTENSION_OVERRIDES = {
    "audio/webm": "webm", "video/webm": "webm",
    "audio/x-m4a": "m4a", "audio/m4a": "m4a", "audio/mp4": "m4a",
}


def _media_extension(content_type: str | None, media_type: str) -> str:
    content_type = (content_type or "").split(";", 1)[0].strip().lower()
    if content_type in _EXTENSION_OVERRIDES:
        return _EXTENSION_OVERRIDES[content_type]
    guessed = mimetypes.guess_extension(content_type) if content_type else None
    if guessed:
        return guessed.lstrip(".")
    return "mp4" if media_type == "video" else "webm"


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
app.add_middleware(auth.AccessCodeMiddleware)


# ---------- Access code / demo login ----------
# A no-op (every request is "full" access) unless VERA_ACCESS_CODE is set --
# see web/auth.py for why a signed cookie is enough here instead of a real
# session store, and which paths (family cheer links, static assets) skip
# this gate entirely.

@app.get("/login")
async def login_page():
    return FileResponse(str(STATIC_DIR / "login.html"))


@app.post("/api/login")
async def api_login(payload: dict):
    if not auth.enabled() or auth.check_code(payload.get("code", "")):
        resp = JSONResponse({"ok": True})
        resp.set_cookie(auth.AUTH_COOKIE, auth.make_cookie_value("full"),
                         max_age=auth.COOKIE_MAX_AGE, httponly=True, samesite="lax")
        return resp
    raise HTTPException(status_code=401, detail="Incorrect code.")


@app.post("/api/demo-login")
async def api_demo_login():
    resp = JSONResponse({"ok": True})
    resp.set_cookie(auth.AUTH_COOKIE, auth.make_cookie_value("demo"),
                     max_age=auth.COOKIE_MAX_AGE, httponly=True, samesite="lax")
    return resp


@app.post("/api/logout")
async def api_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.AUTH_COOKIE)
    return resp


@app.get("/api/tools")
async def api_list_tools():
    return await mcp_bridge.list_tools()


@app.post("/api/tool/{name}")
async def api_call_tool(name: str, request: Request, arguments: dict | None = None):
    arguments = dict(arguments or {})
    if auth.is_demo(request):
        # create_profile and list_profiles both operate across every
        # profile in the store rather than one pinned user_id -- a real
        # family's profile names/ids would otherwise be visible from (or
        # creatable by) the no-code demo button, so each needs its own
        # special case rather than the usual user_id override below.
        if name == "create_profile":
            raise HTTPException(status_code=403, detail="The demo profile can't create new profiles.")
        if name == "list_profiles":
            profiles = []
            for uid in auth.DEMO_USER_IDS:
                try:
                    profile = await mcp_bridge.call_tool("get_profile", {"user_id": uid})
                    profiles.append({"user_id": uid, "name": profile.get("name", "Demo")})
                except mcp_bridge.ToolError:
                    profiles.append({"user_id": uid, "name": "Demo"})
            return {"profiles": profiles}
        arguments["user_id"] = auth.effective_user_id(request, arguments.get("user_id", "demo"))
    try:
        return await mcp_bridge.call_tool(name, arguments)
    except mcp_bridge.ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/chat")
async def api_chat(payload: dict, request: Request):
    if bedrock_chat is None:
        raise HTTPException(status_code=503, detail="Bedrock chat layer not configured.")
    if not rate_limit.chat_limiter.allow(auth.device_id(request)):
        raise HTTPException(status_code=429, detail="Too many requests -- please wait a moment and try again.")
    message = payload.get("message", "")
    history = payload.get("history", [])
    user_id = auth.effective_user_id(request, payload.get("user_id", "demo"))
    try:
        result = await bedrock_chat.converse(message, history, user_id)
    except bedrock_chat.ChatError as e:
        return JSONResponse(status_code=502, content={"error": str(e)})
    return result


@app.post("/api/greet")
async def api_greet(payload: dict, request: Request):
    if bedrock_chat is None:
        raise HTTPException(status_code=503, detail="Bedrock chat layer not configured.")
    if not rate_limit.chat_limiter.allow(auth.device_id(request)):
        raise HTTPException(status_code=429, detail="Too many requests -- please wait a moment and try again.")
    user_id = auth.effective_user_id(request, payload.get("user_id", "demo"))
    try:
        result = await bedrock_chat.greet(user_id)
    except bedrock_chat.ChatError as e:
        return JSONResponse(status_code=502, content={"error": str(e)})
    return result


@app.post("/api/speak")
async def api_speak(payload: dict, request: Request):
    if not rate_limit.speak_limiter.allow(auth.device_id(request)):
        raise HTTPException(status_code=429, detail="Too many requests -- please wait a moment and try again.")
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


# ---------- Demo profile baseline ----------
# The Rose demo profile resets nightly (deploy/reset_demo.py) from either
# this saved baseline or, if none exists yet, rose_demo_profile.json. This
# endpoint is how "Save as demo baseline" on her caregiver dashboard
# captures whatever she currently looks like (family, cheers, history,
# memories) as that baseline. Reachable from a demo-mode session (the
# dashboard itself is), but requires the real access code regardless of
# cookie mode -- a demo visitor can look, but only the real site owner can
# lock in a new baseline.

DEMO_BASELINE_DIR = Path(os.environ.get(
    "VERA_DEMO_BASELINE_DIR", str(Path(__file__).resolve().parent.parent / "data" / "demo_baselines"),
))


@app.post("/api/demo/save_baseline")
async def api_save_demo_baseline(payload: dict):
    if not auth.check_code(payload.get("code", "")):
        raise HTTPException(status_code=403, detail="Incorrect access code.")
    try:
        snapshot = await mcp_bridge.call_tool("export_demo_snapshot", {"user_id": auth.ROSE_DEMO_USER_ID})
    except mcp_bridge.ToolError as e:
        raise HTTPException(status_code=502, detail=str(e))
    DEMO_BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    (DEMO_BASELINE_DIR / "rose.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return {"ok": True, "saved_at": snapshot["saved_at"]}


@app.get("/api/cheer/context/{token}")
async def api_cheer_context(token: str):
    try:
        resolved = await mcp_bridge.call_tool("resolve_family_token", {"token": token})
        if "error" in resolved:
            return JSONResponse(status_code=404, content={"valid": False})
        user_id = resolved["user_id"]
        member = resolved["member"]
        profile = await mcp_bridge.call_tool("get_profile", {"user_id": user_id})
        prompts = await mcp_bridge.call_tool("get_cheer_prompts", {"user_id": user_id})
        sent = await mcp_bridge.call_tool("list_cheers", {"user_id": user_id, "family_id": member["id"]})
    except mcp_bridge.ToolError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {
        "valid": True,
        "recipient_name": profile["name"],
        "member": member,
        "prompts": prompts,
        "sent_count": len(sent["cheers"]),
        "goal": 5,
    }


@app.post("/api/cheer/update_member/{token}")
async def api_cheer_update_member(token: str, payload: dict):
    """A family member editing their own first-visit setup or a later
    detail (name, relationship, nickname, email, email opt-in) from their
    private record-page link -- no login, the token is already their only
    auth. Resolves the token to the right user_id/family_id itself rather
    than trusting anything the client sends for those, which is what lets
    this safely sit outside the access-code gate alongside the rest of the
    /cheer/<token> flow."""
    try:
        resolved = await mcp_bridge.call_tool("resolve_family_token", {"token": token})
    except mcp_bridge.ToolError as e:
        raise HTTPException(status_code=502, detail=str(e))
    if "error" in resolved:
        raise HTTPException(status_code=404, detail=resolved["error"])
    allowed_fields = {"name", "relationship", "nickname", "email", "email_opt_in"}
    fields = {k: v for k, v in (payload or {}).items() if k in allowed_fields}
    try:
        result = await mcp_bridge.call_tool("update_family_member", {
            "family_id": resolved["member"]["id"], "user_id": resolved["user_id"], **fields,
        })
    except mcp_bridge.ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@app.post("/api/cheer/upload/{token}")
async def api_cheer_upload(
    token: str,
    file: UploadFile = File(...),
    media_type: str = Form(...),
    duration_seconds: float = Form(...),
    cheer_type: str = Form("anytime"),
    target: str | None = Form(None),
    photo: UploadFile | None = File(None),
):
    if duration_seconds > MAX_CHEER_SECONDS + 1:
        raise HTTPException(status_code=400, detail=f"Cheers are {MAX_CHEER_SECONDS} seconds max.")
    if duration_seconds <= 0:
        raise HTTPException(status_code=400, detail="That recording looks empty.")
    if media_type not in ALLOWED_MEDIA_TYPES:
        raise HTTPException(status_code=400, detail="Unrecognized recording type.")
    if not (file.content_type or "").startswith(ALLOWED_AV_PREFIXES):
        raise HTTPException(status_code=400, detail="That file doesn't look like an audio or video recording.")
    if photo is not None and not (photo.content_type or "").startswith(ALLOWED_IMAGE_PREFIXES):
        raise HTTPException(status_code=400, detail="That file doesn't look like a photo.")
    try:
        resolved = await mcp_bridge.call_tool("resolve_family_token", {"token": token})
    except mcp_bridge.ToolError as e:
        raise HTTPException(status_code=502, detail=str(e))
    if "error" in resolved:
        raise HTTPException(status_code=404, detail=resolved["error"])
    user_id = resolved["user_id"]
    member = resolved["member"]

    content = await file.read()
    if len(content) > MAX_CHEER_BYTES:
        raise HTTPException(status_code=400, detail="That recording is too large.")
    photo_content = await photo.read() if photo else None
    if photo_content and len(photo_content) > MAX_CHEER_BYTES:
        raise HTTPException(status_code=400, detail="That photo is too large.")

    ext = _media_extension(file.content_type, media_type)
    filename = f"{uuid.uuid4().hex}.{ext}"
    photo_filename = f"{uuid.uuid4().hex}.jpg" if photo_content else None

    storage = "local"
    if cloud_storage.enabled():
        try:
            content_type = file.content_type or (f"video/{ext}" if media_type == "video" else f"audio/{ext}")
            await run_in_threadpool(cloud_storage.upload_bytes, cheer_s3_key(filename), content, content_type)
            if photo_content:
                await run_in_threadpool(cloud_storage.upload_bytes, cheer_s3_key(photo_filename), photo_content, photo.content_type or "image/jpeg")
            storage = "s3"
        except Exception:
            # S3 unreachable or misconfigured -- fall back to local disk
            # below rather than losing the recording.
            storage = "local"
    if storage == "local":
        (CHEER_MEDIA_DIR / filename).write_bytes(content)
        if photo_content:
            (CHEER_MEDIA_DIR / photo_filename).write_bytes(photo_content)

    try:
        result = await mcp_bridge.call_tool("add_cheer", {
            "family_id": member["id"],
            "media_type": media_type,
            "file": filename,
            "duration_seconds": duration_seconds,
            "user_id": user_id,
            "cheer_type": cheer_type,
            "target": target or None,
            "photo_file": photo_filename,
            "storage": storage,
        })
    except mcp_bridge.ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@app.post("/api/cheer/notify")
async def api_cheer_notify(payload: dict, request: Request):
    """Best-effort "almost there" nudge (email now; SMS too, once
    VERA_SMS_ENABLED is on and the family member has a phone on file) --
    copying the record link always works regardless of whether this
    succeeds."""
    user_id = auth.effective_user_id(request, payload.get("user_id", "demo"))
    family_id = payload.get("family_id")
    milestone_id = payload.get("milestone_id")

    family_res = await mcp_bridge.call_tool("list_family", {"user_id": user_id})
    member = next((m for m in family_res["family"] if m["id"] == family_id), None)
    if not member:
        raise HTTPException(status_code=404, detail="Family member not found.")

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

    sent_email = sent_sms = False
    errors = []
    if member.get("email"):
        try:
            await run_in_threadpool(ses_email.send_nudge_email, member["email"], "A cheer for your family member", body)
            sent_email = True
        except ses_email.EmailError as e:
            errors.append(str(e))
    if sms.enabled() and member.get("phone"):
        try:
            await run_in_threadpool(sms.send_nudge_sms, member["phone"], body)
            sent_sms = True
        except sms.SMSError as e:
            errors.append(str(e))

    if not sent_email and not sent_sms:
        raise HTTPException(status_code=502, detail="; ".join(errors) or "No email or phone on file, and SMS isn't enabled.")
    return {"sent_email": sent_email, "sent_sms": sent_sms}


@app.post("/api/family/check_alerts")
async def api_family_check_alerts(payload: dict, request: Request):
    """Runs on caregiver dashboard load (this app has no background job
    runner): sends a one-time "running low" email to any family member
    whose unlocked-cheer queue just dropped to 1 or 0, then marks it sent
    so it isn't repeated. Best-effort -- a failed send just gets retried
    next time the dashboard loads."""
    user_id = auth.effective_user_id(request, payload.get("user_id", "demo"))
    alerts = (await mcp_bridge.call_tool("check_family_alerts", {"user_id": user_id}))["alerts"]
    sent = []
    for a in alerts:
        link = f"{str(request.base_url).rstrip('/')}/cheer/{a['token']}"
        body = f"{a['message']}\n\nRecord one here: {link}"
        try:
            await run_in_threadpool(ses_email.send_nudge_email, a["email"], "Your cheers are running low", body)
        except ses_email.EmailError:
            continue
        await mcp_bridge.call_tool("mark_alert_sent", {"family_id": a["family_id"], "unplayed": a["unplayed"], "user_id": user_id})
        sent.append(a["family_id"])
    return {"sent": sent}


# ---------- Simulated living room display ----------

@app.get("/tv/{user_id}")
async def tv_display_page(user_id: str):
    """A big-screen, high-contrast 'Living Room Display' -- a SIMULATED
    Fire TV, not a real device integration. Mirrors whatever session (if
    any) has been handed off to it, via /api/display/events."""
    return FileResponse(str(STATIC_DIR / "tv" / "display.html"))


@app.get("/api/display/events/{user_id}")
async def api_display_events(user_id: str, request: Request):
    """Server-sent events so the TV display (and the main screen's 'Now
    playing on Living Room TV' banner) update the moment a session is
    handed off or brought back, instead of a client polling loop."""
    user_id = auth.effective_user_id(request, user_id)

    async def events():
        last_payload = None
        while True:
            try:
                state = await mcp_bridge.call_tool("get_display_session", {"user_id": user_id})
            except mcp_bridge.ToolError:
                state = {"display": None, "session": None, "updated_at": None}
            payload = json.dumps(state)
            if payload != last_payload:
                yield f"data: {payload}\n\n"
                last_payload = payload
            else:
                yield ": keep-alive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


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
