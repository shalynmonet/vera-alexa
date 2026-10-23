"""The single shared-access-code gate for the main app and the caregiver
dashboard, plus the no-code judge demo mode.

There's no per-user account system here -- the whole household (and
anyone they show it to) shares one access code from VERA_ACCESS_CODE, so a
signed, long-lived cookie is enough: no session store, no database. The
cookie's value is just "<mode>.<hmac>" where mode is "full" (the real
code was entered) or "demo" (the no-code judge button was used); the HMAC
is unforgeable without the server's secret, so there's nothing to check
beyond "does the signature match this mode". If VERA_ACCESS_CODE isn't
set at all, the gate is skipped entirely -- same "optional unless
configured" pattern as Polly/S3/SES elsewhere in this app, so local dev
never needs it.

Family cheer links (/cheer/<token>) are a separate, already-private
auth mechanism (the token itself) and are never gated by this module.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

ACCESS_CODE = os.environ.get("VERA_ACCESS_CODE", "").strip()
# Falls back to the access code itself as the signing secret when no
# separate one is set -- both are already meant to be kept secret, and a
# dedicated VERA_SECRET_KEY is only needed if the access code is ever
# rotated without wanting to invalidate existing "remembered" devices.
SECRET = (os.environ.get("VERA_SECRET_KEY", "").strip() or ACCESS_CODE).encode()

DEMO_USER_ID = os.environ.get("VERA_DEMO_USER_ID", "judge_demo")
# A second, full-featured demo profile (history, streak, badges, memories,
# family) -- same no-code demo button, but picked by name instead of being
# pinned to a single id, so it can be set up for a recorded walkthrough
# without ever exposing a real family's data.
ROSE_DEMO_USER_ID = os.environ.get("VERA_DEMO_ROSE_USER_ID", "rose_demo")
DEMO_USER_IDS = (DEMO_USER_ID, ROSE_DEMO_USER_ID)

AUTH_COOKIE = "vera_auth"
DEVICE_COOKIE = "vera_device_id"
COOKIE_MAX_AGE = 60 * 60 * 24 * 400  # ~400 days, the longest Chrome allows

MODES = ("full", "demo")

# Paths (and prefixes) reachable with no cookie at all: static assets, the
# login page itself and its API, and the family cheer flow, which is
# authenticated by its own private token instead.
_PUBLIC_PREFIXES = (
    "/css/", "/js/", "/img/", "/media/", "/favicon",
    "/login", "/api/login", "/api/demo-login",
    "/cheer/", "/api/cheer/context/", "/api/cheer/upload/",
)


def enabled() -> bool:
    return bool(ACCESS_CODE)


def _sign(mode: str) -> str:
    return hmac.new(SECRET, mode.encode(), hashlib.sha256).hexdigest()


def make_cookie_value(mode: str) -> str:
    assert mode in MODES
    return f"{mode}.{_sign(mode)}"


def verify_cookie_value(value: str | None) -> str | None:
    if not value or "." not in value:
        return None
    mode, _, sig = value.partition(".")
    if mode not in MODES:
        return None
    if not hmac.compare_digest(sig, _sign(mode)):
        return None
    return mode


def check_code(code: str) -> bool:
    return hmac.compare_digest((code or "").strip(), ACCESS_CODE)


def _is_public(path: str) -> bool:
    return any(path == p.rstrip("/") or path.startswith(p) for p in _PUBLIC_PREFIXES)


class AccessCodeMiddleware(BaseHTTPMiddleware):
    """Gates every request except the public ones above behind a valid
    "full" or "demo" cookie. Also stamps every response with a random,
    long-lived per-device id cookie (if the browser doesn't have one yet)
    used purely to bucket rate limits per device -- it carries no auth
    weight of its own."""

    async def dispatch(self, request: Request, call_next):
        request.state.auth_mode = "full"  # the no-op default when the gate is off
        needs_device_cookie = DEVICE_COOKIE not in request.cookies

        if enabled() and not _is_public(request.url.path):
            mode = verify_cookie_value(request.cookies.get(AUTH_COOKIE))
            if mode is None:
                if request.url.path.startswith("/api/"):
                    return JSONResponse({"error": "Not logged in."}, status_code=401)
                return RedirectResponse(f"/login?next={request.url.path}", status_code=303)
            request.state.auth_mode = mode

        response = await call_next(request)
        if needs_device_cookie:
            response.set_cookie(
                DEVICE_COOKIE, uuid.uuid4().hex,
                max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax",
            )
        return response


def device_id(request: Request) -> str:
    """Best-effort per-device key for rate limiting -- the cookie set by
    the middleware above, falling back to the client IP for the rare
    first request that arrives before a response could set it."""
    return request.cookies.get(DEVICE_COOKIE) or (request.client.host if request.client else "unknown")


def is_demo(request: Request) -> bool:
    return getattr(request.state, "auth_mode", "full") == "demo"


def effective_user_id(request: Request, requested: str) -> str:
    """The user_id a request is actually allowed to touch: for a demo-mode
    session, only one of the two fixed demo profiles (DEMO_USER_IDS) is
    ever reachable, no matter what the client asked for -- defaulting to
    the judge demo profile for anything else -- so a real family's data
    can never be reached from the no-code demo button."""
    if not is_demo(request):
        return requested
    return requested if requested in DEMO_USER_IDS else DEMO_USER_ID
