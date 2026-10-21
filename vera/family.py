"""Family Cheers: tokens and ids for family members and the cheers they
record. Generation only -- storage lives alongside everything else in
vera/storage.py, and the actual media bytes live on disk (see
web/app.py's CHEER_MEDIA_DIR), referenced here only by filename.
"""
from __future__ import annotations

import secrets
import uuid


def new_token() -> str:
    """A unique, unguessable token for a family member's private,
    no-login record-page link."""
    return secrets.token_urlsafe(16)


def new_id() -> str:
    return uuid.uuid4().hex[:12]
