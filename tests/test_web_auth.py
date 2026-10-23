"""Access-code login, the no-code judge demo mode, and per-device/global
rate limiting (web/auth.py, web/rate_limit.py, and the gating wired into
web/app.py). Uses FastAPI's TestClient against the real app object, with
mcp_bridge.call_tool monkeypatched so these run with no MCP server, AWS
credentials, or Bedrock/Polly access needed -- they're testing the gate,
not what's behind it."""
import json

import pytest
from fastapi.testclient import TestClient

from web import app as app_module
from web import auth, mcp_bridge, rate_limit

client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    # Each limiter instance is a shared module-level singleton -- give
    # every test a clean slate instead of leaking hits between tests.
    for limiter in (rate_limit.chat_limiter, rate_limit.speak_limiter):
        limiter._device_hits.clear()
        limiter._global_hits.clear()
    yield


@pytest.fixture
def code_enabled(monkeypatch):
    """Simulates VERA_ACCESS_CODE being set, without needing a real env
    var at import time -- auth.py reads it once at module load, so tests
    patch the already-loaded module's attributes instead."""
    monkeypatch.setattr(auth, "ACCESS_CODE", "letmein")
    monkeypatch.setattr(auth, "SECRET", b"letmein")
    return "letmein"


# ---------- gate disabled (no code configured) ----------

def test_gate_is_a_no_op_when_no_access_code_is_configured():
    assert auth.ACCESS_CODE == ""  # the default test environment has none set
    res = client.get("/", follow_redirects=False)
    assert res.status_code == 200


# ---------- gate enabled ----------

def test_root_redirects_to_login_without_a_cookie(code_enabled):
    res = client.get("/", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"].startswith("/login")


def test_api_paths_get_401_json_without_a_cookie_not_a_redirect(code_enabled):
    res = client.post("/api/tool/get_profile", json={}, follow_redirects=False)
    assert res.status_code == 401
    assert res.json() == {"error": "Not logged in."}


def test_wrong_code_is_rejected(code_enabled):
    res = client.post("/api/login", json={"code": "wrong"})
    assert res.status_code == 401
    assert auth.AUTH_COOKIE not in res.cookies


def test_correct_code_sets_a_cookie_that_unlocks_the_app(code_enabled):
    res = client.post("/api/login", json={"code": code_enabled})
    assert res.status_code == 200
    assert auth.AUTH_COOKIE in res.cookies

    unlocked = client.get("/", cookies=res.cookies, follow_redirects=False)
    assert unlocked.status_code == 200


def test_cookie_is_rejected_once_the_access_code_changes(code_enabled):
    """Rotating VERA_ACCESS_CODE (the signing secret derives from it)
    should invalidate every previously "remembered" device."""
    res = client.post("/api/login", json={"code": code_enabled})
    stale_cookies = res.cookies

    # The operator rotates the code.
    auth.ACCESS_CODE = "a-new-code"
    auth.SECRET = b"a-new-code"

    res2 = client.get("/", cookies=stale_cookies, follow_redirects=False)
    assert res2.status_code == 303


def test_demo_login_needs_no_code(code_enabled):
    res = client.post("/api/demo-login")
    assert res.status_code == 200
    assert auth.AUTH_COOKIE in res.cookies

    unlocked = client.get("/", cookies=res.cookies, follow_redirects=False)
    assert unlocked.status_code == 200


# ---------- family cheer links bypass the gate entirely ----------

def test_cheer_record_page_needs_no_cookie(code_enabled):
    res = client.get("/cheer/some-token-shaped-string", follow_redirects=False)
    assert res.status_code == 200


def test_static_assets_need_no_cookie(code_enabled):
    res = client.get("/css/style.css", follow_redirects=False)
    assert res.status_code == 200


# ---------- demo mode is pinned to the judge profile, never a real one ----------

def test_demo_mode_pins_unrecognized_ids_to_the_judge_profile(code_enabled, monkeypatch):
    captured = {}

    async def fake_call_tool(name, arguments=None):
        captured["name"] = name
        captured["arguments"] = arguments
        return {"ok": True}

    monkeypatch.setattr(mcp_bridge, "call_tool", fake_call_tool)

    demo_cookies = client.post("/api/demo-login").cookies
    client.post("/api/tool/get_fitness_log", json={"user_id": "someone_elses_real_profile"}, cookies=demo_cookies)

    assert captured["arguments"]["user_id"] == auth.DEMO_USER_ID


def test_demo_mode_lets_through_the_rose_demo_profile_specifically(code_enabled, monkeypatch):
    """The fix for Rose's profile being unreachable in demo mode: unlike
    an arbitrary/real user_id, her fixed demo id is one of the two the
    no-code button is allowed to touch, so it passes through unchanged
    instead of being overridden to the judge profile."""
    captured = {}

    async def fake_call_tool(name, arguments=None):
        captured["arguments"] = arguments
        return {"ok": True}

    monkeypatch.setattr(mcp_bridge, "call_tool", fake_call_tool)

    demo_cookies = client.post("/api/demo-login").cookies
    client.post("/api/tool/get_fitness_log", json={"user_id": auth.ROSE_DEMO_USER_ID}, cookies=demo_cookies)

    assert captured["arguments"]["user_id"] == auth.ROSE_DEMO_USER_ID


def test_demo_mode_cannot_create_new_profiles(code_enabled):
    demo_cookies = client.post("/api/demo-login").cookies
    res = client.post("/api/tool/create_profile", json={"name": "Someone New"}, cookies=demo_cookies)
    assert res.status_code == 403


def test_demo_mode_list_profiles_shows_both_demo_profiles(code_enabled, monkeypatch):
    """The two-profile picker: demo mode should offer Judge Demo and Rose,
    nothing else -- never a real family's profile."""
    names = {auth.DEMO_USER_ID: "Judge Demo", auth.ROSE_DEMO_USER_ID: "Rose"}

    async def fake_call_tool(name, arguments=None):
        assert name == "get_profile"
        assert arguments["user_id"] in names
        return {"name": names[arguments["user_id"]]}

    monkeypatch.setattr(mcp_bridge, "call_tool", fake_call_tool)

    demo_cookies = client.post("/api/demo-login").cookies
    res = client.post("/api/tool/list_profiles", json={}, cookies=demo_cookies)
    assert res.json() == {
        "profiles": [
            {"user_id": auth.DEMO_USER_ID, "name": "Judge Demo"},
            {"user_id": auth.ROSE_DEMO_USER_ID, "name": "Rose"},
        ]
    }


# ---------- saving Rose's demo baseline ----------

def test_save_baseline_rejects_the_wrong_code(code_enabled, monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "DEMO_BASELINE_DIR", tmp_path)

    async def fake_call_tool(name, arguments=None):
        raise AssertionError("should never reach the MCP call -- the code check must fail first")

    monkeypatch.setattr(mcp_bridge, "call_tool", fake_call_tool)

    res = client.post("/api/demo/save_baseline", json={"code": "wrong"})
    assert res.status_code == 403
    assert not (tmp_path / "rose.json").exists()


def test_save_baseline_writes_the_snapshot_with_the_right_code(code_enabled, monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "DEMO_BASELINE_DIR", tmp_path)
    snapshot = {"saved_at": "2026-10-23T12:00:00", "name": "Rose", "weekly_goal_days": 4,
                "activities": [], "memories": [], "family": [], "cheers": []}

    async def fake_call_tool(name, arguments=None):
        assert name == "export_demo_snapshot"
        assert arguments == {"user_id": auth.ROSE_DEMO_USER_ID}
        return snapshot

    monkeypatch.setattr(mcp_bridge, "call_tool", fake_call_tool)

    res = client.post("/api/demo/save_baseline", json={"code": code_enabled})
    assert res.status_code == 200
    assert res.json() == {"ok": True, "saved_at": "2026-10-23T12:00:00"}

    saved = json.loads((tmp_path / "rose.json").read_text(encoding="utf-8"))
    assert saved == snapshot


def test_save_baseline_is_reachable_from_a_demo_mode_session(code_enabled, monkeypatch, tmp_path):
    """The dashboard button is shown in a demo-mode session too (so the
    site owner can use it while trying the no-code flow themselves) --
    it's the access code in the request body that actually gates it, not
    the cookie's auth mode."""
    monkeypatch.setattr(app_module, "DEMO_BASELINE_DIR", tmp_path)
    snapshot = {"saved_at": "now", "name": "Rose", "weekly_goal_days": 4,
                "activities": [], "memories": [], "family": [], "cheers": []}

    async def fake_call_tool(name, arguments=None):
        return snapshot

    monkeypatch.setattr(mcp_bridge, "call_tool", fake_call_tool)

    demo_cookies = client.post("/api/demo-login").cookies
    res = client.post("/api/demo/save_baseline", json={"code": code_enabled}, cookies=demo_cookies)
    assert res.status_code == 200


def test_full_mode_does_not_pin_user_id(code_enabled, monkeypatch):
    captured = {}

    async def fake_call_tool(name, arguments=None):
        captured["arguments"] = arguments
        return {"ok": True}

    monkeypatch.setattr(mcp_bridge, "call_tool", fake_call_tool)

    full_cookies = client.post("/api/login", json={"code": code_enabled}).cookies
    client.post("/api/tool/get_fitness_log", json={"user_id": "rose"}, cookies=full_cookies)

    assert captured["arguments"]["user_id"] == "rose"


# ---------- rate limiting ----------

def test_speak_endpoint_returns_429_once_its_limiter_says_no(monkeypatch):
    """Confirms the wiring, not just the RateLimiter class above: a
    limiter that's already out of budget should stop the request before
    it ever reaches Polly."""
    monkeypatch.setattr(rate_limit.speak_limiter, "allow", lambda device_id: False)
    res = client.post("/api/speak", json={"text": "hello"})
    assert res.status_code == 429


def test_chat_endpoint_returns_429_once_its_limiter_says_no(monkeypatch):
    monkeypatch.setattr(rate_limit.chat_limiter, "allow", lambda device_id: False)
    res = client.post("/api/chat", json={"message": "hi", "history": []})
    assert res.status_code == 429


def test_rate_limiter_blocks_a_device_past_its_per_device_limit():
    limiter = rate_limit.RateLimiter(per_device_limit=3, per_device_window=60, global_limit=1000, global_window=60)
    for _ in range(3):
        assert limiter.allow("device-a") is True
    assert limiter.allow("device-a") is False
    # A different device is unaffected -- the cap is per device, not shared.
    assert limiter.allow("device-b") is True


def test_rate_limiter_global_cap_applies_even_across_many_devices():
    limiter = rate_limit.RateLimiter(per_device_limit=1000, per_device_window=60, global_limit=2, global_window=60)
    assert limiter.allow("device-a") is True
    assert limiter.allow("device-b") is True
    assert limiter.allow("device-c") is False  # global cap hit even though device-c itself never has


def test_rate_limiter_window_expires_old_hits():
    # A generous window/sleep margin -- this runs alongside a lot of other
    # subprocess-heavy tests in the full suite, where tight timing (a
    # previous version used a 50ms window) is flaky under scheduling jitter.
    limiter = rate_limit.RateLimiter(per_device_limit=1, per_device_window=0.2, global_limit=1000, global_window=60)
    assert limiter.allow("device-a") is True
    assert limiter.allow("device-a") is False
    import time
    time.sleep(0.4)
    assert limiter.allow("device-a") is True


# ---------- saved filename extension matches the real file type ----------
# cheer_media is served by a plain StaticFiles mount, which sets
# Content-Type from the filename's extension alone -- "Upload a File
# Instead" can hand the server a real WAV/MP3/M4A, not just a MediaRecorder
# webm/mp4 blob, so the saved extension has to actually match the bytes or
# playback can break.

def test_media_extension_prefers_known_overrides():
    assert app_module._media_extension("audio/webm", "voice") == "webm"
    assert app_module._media_extension("video/webm", "video") == "webm"
    assert app_module._media_extension("audio/wav", "voice") == "wav"
    assert app_module._media_extension("audio/mpeg", "voice") == "mp3"
    assert app_module._media_extension("audio/x-m4a", "voice") == "m4a"


def test_media_extension_falls_back_when_unknown():
    assert app_module._media_extension(None, "voice") == "webm"
    assert app_module._media_extension("audio/x-some-made-up-codec", "video") == "mp4"


def test_cheer_upload_saves_an_uploaded_file_with_its_real_extension(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "CHEER_MEDIA_DIR", tmp_path)
    captured = {}

    async def fake_call_tool(name, arguments=None):
        if name == "resolve_family_token":
            return {"user_id": "demo", "member": {"id": "fam1"}}
        if name == "add_cheer":
            captured["file"] = arguments["file"]
            return {"cheer": {"id": "c1"}, "sent_count": 1, "goal": 5}
        raise AssertionError(f"unexpected tool call: {name}")

    monkeypatch.setattr(mcp_bridge, "call_tool", fake_call_tool)

    res = client.post(
        "/api/cheer/upload/some-token",
        data={"media_type": "voice", "duration_seconds": "3"},
        files={"file": ("my-recording.wav", b"RIFF....fake wav bytes", "audio/wav")},
    )
    assert res.status_code == 200
    assert captured["file"].endswith(".wav")
    assert (tmp_path / captured["file"]).exists()


def test_cheer_upload_keeps_webm_for_a_live_browser_recording(monkeypatch, tmp_path):
    """Also fixes a pre-existing mismatch: a live video recording is
    really video/webm (MediaRecorder never produces mp4), but used to be
    saved with a hardcoded .mp4 extension regardless."""
    monkeypatch.setattr(app_module, "CHEER_MEDIA_DIR", tmp_path)
    captured = {}

    async def fake_call_tool(name, arguments=None):
        if name == "resolve_family_token":
            return {"user_id": "demo", "member": {"id": "fam1"}}
        if name == "add_cheer":
            captured["file"] = arguments["file"]
            return {"cheer": {"id": "c1"}, "sent_count": 1, "goal": 5}
        raise AssertionError(f"unexpected tool call: {name}")

    monkeypatch.setattr(mcp_bridge, "call_tool", fake_call_tool)

    res = client.post(
        "/api/cheer/upload/some-token",
        data={"media_type": "video", "duration_seconds": "5"},
        files={"file": ("cheer.webm", b"fake video bytes", "video/webm")},
    )
    assert res.status_code == 200
    assert captured["file"].endswith(".webm")


# ---------- cheer upload validation ----------
# No access code involved here -- /api/cheer/upload/<token> is exempt from
# the gate (the token is its own auth) -- this is purely about not
# trusting what a browser claims a file is.

def test_cheer_upload_rejects_a_non_media_content_type(monkeypatch):
    async def fake_call_tool(name, arguments=None):
        raise AssertionError("should never reach an MCP call -- content-type check must fail first")

    monkeypatch.setattr(mcp_bridge, "call_tool", fake_call_tool)

    res = client.post(
        "/api/cheer/upload/some-token",
        data={"media_type": "voice", "duration_seconds": "5"},
        files={"file": ("cheer.exe", b"not actually audio", "application/x-msdownload")},
    )
    assert res.status_code == 400


def test_cheer_upload_rejects_an_unrecognized_media_type(monkeypatch):
    async def fake_call_tool(name, arguments=None):
        raise AssertionError("should never reach an MCP call -- media_type check must fail first")

    monkeypatch.setattr(mcp_bridge, "call_tool", fake_call_tool)

    res = client.post(
        "/api/cheer/upload/some-token",
        data={"media_type": "something_unexpected", "duration_seconds": "5"},
        files={"file": ("cheer.webm", b"fake audio bytes", "audio/webm")},
    )
    assert res.status_code == 400


def test_cheer_upload_accepts_a_real_audio_content_type(monkeypatch):
    """Confirms the validation doesn't just reject everything -- a
    legitimate recording still gets through to the (here, faked) MCP
    call."""
    async def fake_call_tool(name, arguments=None):
        if name == "resolve_family_token":
            return {"user_id": "demo", "member": {"id": "fam1", "token": "some-token"}}
        if name == "add_cheer":
            return {"cheer": {"id": "c1"}, "sent_count": 1, "goal": 5}
        raise AssertionError(f"unexpected tool call: {name}")

    monkeypatch.setattr(mcp_bridge, "call_tool", fake_call_tool)

    res = client.post(
        "/api/cheer/upload/some-token",
        data={"media_type": "voice", "duration_seconds": "5"},
        files={"file": ("cheer.webm", b"fake audio bytes", "audio/webm")},
    )
    assert res.status_code == 200


# ---------- cheer update_member: the bug where a family member's own
# first-visit setup / later edit needed a login they could never have ----------

def test_cheer_update_member_needs_no_cookie_even_with_access_code_set(code_enabled, monkeypatch):
    """The actual bug: a family member visiting their /cheer/<token> link
    has no login at all. update_member must work exactly like
    /api/cheer/context and /api/cheer/upload already do -- reachable with
    no cookie -- even once VERA_ACCESS_CODE is configured. Before the fix
    this route didn't exist and the page called the cookie-gated generic
    /api/tool/update_family_member instead, which 401'd for every family
    member and showed "Link not found"."""
    async def fake_call_tool(name, arguments=None):
        if name == "resolve_family_token":
            return {"user_id": "rose", "member": {"id": "fam1"}}
        if name == "update_family_member":
            assert arguments == {"user_id": "rose", "family_id": "fam1", "nickname": "Grandma"}
            return {"member": {"id": "fam1", "nickname": "Grandma"}}
        raise AssertionError(f"unexpected tool call: {name}")

    monkeypatch.setattr(mcp_bridge, "call_tool", fake_call_tool)

    res = client.post("/api/cheer/update_member/tok", json={"nickname": "Grandma"})
    assert res.status_code == 200
    assert res.json() == {"member": {"id": "fam1", "nickname": "Grandma"}}


def test_cheer_update_member_rejects_an_unknown_token(monkeypatch):
    async def fake_call_tool(name, arguments=None):
        assert name == "resolve_family_token"
        return {"error": "This link isn't valid."}

    monkeypatch.setattr(mcp_bridge, "call_tool", fake_call_tool)

    res = client.post("/api/cheer/update_member/bad-token", json={"nickname": "x"})
    assert res.status_code == 404


def test_cheer_update_member_ignores_client_supplied_ids(monkeypatch):
    """family_id/user_id come only from resolving the token server-side,
    never from the request body -- a client can't redirect the edit to
    someone else's profile."""
    async def fake_call_tool(name, arguments=None):
        if name == "resolve_family_token":
            return {"user_id": "rose", "member": {"id": "real-fam-id"}}
        if name == "update_family_member":
            assert arguments["user_id"] == "rose"
            assert arguments["family_id"] == "real-fam-id"
            return {"member": {}}
        raise AssertionError(f"unexpected tool call: {name}")

    monkeypatch.setattr(mcp_bridge, "call_tool", fake_call_tool)

    res = client.post(
        "/api/cheer/update_member/tok",
        json={"user_id": "someone_elses_profile", "family_id": "spoofed-id", "nickname": "ok"},
    )
    assert res.status_code == 200
