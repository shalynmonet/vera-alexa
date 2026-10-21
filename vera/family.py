"""Family Cheers: tokens and ids for family members and the cheers they
record. Generation only -- storage lives alongside everything else in
vera/storage.py. A cheer's media bytes live either on local disk (see
web/app.py's CHEER_MEDIA_DIR) or in S3 (see vera/cloud_storage.py),
referenced here only by filename/key plus a "storage" marker.
"""
from __future__ import annotations

import secrets
import uuid

from . import cloud_storage


def new_token() -> str:
    """A unique, unguessable token for a family member's private,
    no-login record-page link."""
    return secrets.token_urlsafe(16)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def cheer_s3_key(filename: str) -> str:
    return f"cheers/{filename}"


def cheer_media_url(cheer: dict) -> str | None:
    """A fresh presigned URL for a cheer stored in S3; None for one stored
    locally, since the frontend already knows to fall back to
    /cheer-media/<file> for those."""
    if cheer.get("storage") != "s3":
        return None
    return cloud_storage.presigned_url(cheer_s3_key(cheer["file"]))
