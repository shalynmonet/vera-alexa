"""Loads the exercise and meditation manifests: JSON files that sit right
alongside the real media files in web/static/media/<category>/manifest.json.

Each manifest entry names the video/audio/thumbnail file it expects. When
Amazon S3 is configured (see vera/cloud_storage.py), that file is served
from the bucket via a presigned URL; otherwise this module checks whether
it exists on local disk instead, so a routine with no recording yet simply
shows a friendly "coming soon" card -- no code change needed once the real
file is dropped in (locally, or uploaded to the bucket) with the exact
filename the manifest expects.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import cloud_storage

MEDIA_ROOT = Path(__file__).resolve().parent.parent / "web" / "static" / "media"
EXERCISE_DIR = MEDIA_ROOT / "exercise"
MEDITATION_DIR = MEDIA_ROOT / "meditations"


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _local_url(media_dir: Path, filename: str) -> str:
    rel = media_dir.relative_to(MEDIA_ROOT)
    return f"/media/{rel.as_posix()}/{filename}"


def _s3_key(media_dir: Path, filename: str) -> str:
    rel = media_dir.relative_to(MEDIA_ROOT)
    return f"media/{rel.as_posix()}/{filename}"


def _resolve_url(media_dir: Path, filename: str | None) -> str | None:
    if not filename:
        return None
    if cloud_storage.enabled():
        key = _s3_key(media_dir, filename)
        if cloud_storage.object_exists(key):
            return cloud_storage.presigned_url(key)
    if (media_dir / filename).exists():
        return _local_url(media_dir, filename)
    return None


def _enrich(entry: dict[str, Any], media_dir: Path) -> dict[str, Any]:
    out = dict(entry)
    media_url = _resolve_url(media_dir, entry.get("file"))
    out["available"] = bool(media_url)
    out["media_url"] = media_url
    out["thumbnail_url"] = _resolve_url(media_dir, entry.get("thumbnail"))
    return out


def exercise_routines() -> list[dict[str, Any]]:
    return [_enrich(e, EXERCISE_DIR) for e in _load_manifest(EXERCISE_DIR / "manifest.json")]


def meditations() -> list[dict[str, Any]]:
    return [_enrich(e, MEDITATION_DIR) for e in _load_manifest(MEDITATION_DIR / "manifest.json")]


def exercise_routine(routine_id: str) -> dict[str, Any] | None:
    return next((r for r in exercise_routines() if r["id"] == routine_id), None)


def meditation(meditation_id: str) -> dict[str, Any] | None:
    return next((m for m in meditations() if m["id"] == meditation_id), None)
