"""Optional Amazon S3 storage for exercise/meditation media and Family
Cheers recordings, served back out via presigned URLs so the bucket itself
can stay private.

Entirely optional: when VERA_S3_BUCKET isn't set, every caller here is a
no-op and callers fall back to serving the same files from local disk --
all a laptop demo needs. In a cloud deployment it's not just nicer, it's
required, since an AWS App Runner instance's local disk doesn't survive a
restart and isn't shared across instances.
"""
from __future__ import annotations

import os
from functools import lru_cache

import boto3
from botocore.exceptions import BotoCoreError, ClientError

BUCKET = os.environ.get("VERA_S3_BUCKET")
PREFIX = os.environ.get("VERA_S3_PREFIX", "").strip("/")
REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

_client = None


def enabled() -> bool:
    return bool(BUCKET)


def _s3():
    global _client
    if _client is None:
        _client = boto3.client("s3", region_name=REGION)
    return _client


def _full_key(key: str) -> str:
    return f"{PREFIX}/{key}" if PREFIX else key


def upload_bytes(key: str, data: bytes, content_type: str) -> None:
    if not enabled():
        raise RuntimeError("VERA_S3_BUCKET is not configured.")
    _s3().put_object(Bucket=BUCKET, Key=_full_key(key), Body=data, ContentType=content_type)


@lru_cache(maxsize=256)
def object_exists(key: str) -> bool:
    """Cached for the life of the process -- media files don't change
    during a demo, and a fresh process (the normal way to pick up a newly
    uploaded file) gets a clean cache."""
    if not enabled():
        return False
    try:
        _s3().head_object(Bucket=BUCKET, Key=_full_key(key))
        return True
    except (ClientError, BotoCoreError):
        return False


def presigned_url(key: str, expires_in: int = 3600) -> str | None:
    if not enabled():
        return None
    try:
        return _s3().generate_presigned_url(
            "get_object", Params={"Bucket": BUCKET, "Key": _full_key(key)}, ExpiresIn=expires_in,
        )
    except (ClientError, BotoCoreError):
        return None
