"""Family Cheers: tokens and ids for family members and the cheers they
record, plus the small amount of shared logic (display names, media URLs)
used by both server.py's tools and web/app.py's upload endpoint. Storage
lives alongside everything else in vera/storage.py. A cheer's media bytes
live either on local disk (see web/app.py's CHEER_MEDIA_DIR) or in S3 (see
vera/cloud_storage.py), referenced here only by filename/key plus a
"storage" marker.
"""
from __future__ import annotations

import secrets
import uuid

from . import cloud_storage

MAX_CHEER_SECONDS = 15
CHEER_GOAL = 5  # "2 of 5 sent" on the family link page


def new_token() -> str:
    """A unique, unguessable token for a family member's private,
    no-login record-page link."""
    return secrets.token_urlsafe(16)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def display_name(member: dict | None, user_first_name: str) -> str:
    """What this person calls the Vera user -- the family member's own
    answer once they've set it, falling back to the adder's guess, then
    the user's first name."""
    if not member:
        return user_first_name
    return member.get("nickname") or user_first_name


def cheer_s3_key(filename: str) -> str:
    """The S3 key a cheer recording (or its attached photo) is stored
    under -- also used by web/app.py's upload endpoint to upload the raw
    bytes before add_cheer ever sees them."""
    return f"cheers/{filename}"


def cheer_media_url(cheer: dict) -> str | None:
    """A fresh presigned URL for a cheer stored in S3; None for one stored
    locally, since the frontend already knows to fall back to
    /cheer-media/<file> for those."""
    if cheer.get("storage") != "s3" or not cheer.get("file"):
        return None
    return cloud_storage.presigned_url(cheer_s3_key(cheer["file"]))


def cheer_photo_url(cheer: dict) -> str | None:
    """Same as cheer_media_url, but for the optional photo attached to a
    'voice + photo' cheer."""
    if cheer.get("storage") != "s3" or not cheer.get("photo_file"):
        return None
    return cloud_storage.presigned_url(cheer_s3_key(cheer["photo_file"]))
