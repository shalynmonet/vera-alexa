"""Loads the exercise and meditation manifests: JSON files that sit right
alongside the real media files in web/static/media/<category>/manifest.json.

Each manifest entry names the video/audio/thumbnail file it expects. This
module checks whether that file actually exists on disk and reports
`available` accordingly, so a routine shows a friendly "video coming soon"
card until the real recording is dropped in with the exact filename the
manifest expects -- no code change needed when it arrives.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MEDIA_ROOT = Path(__file__).resolve().parent.parent / "web" / "static" / "media"
EXERCISE_DIR = MEDIA_ROOT / "exercise"
MEDITATION_DIR = MEDIA_ROOT / "meditations"


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _public_url(media_dir: Path, filename: str | None) -> str | None:
    if not filename:
        return None
    rel = media_dir.relative_to(MEDIA_ROOT)
    return f"/media/{rel.as_posix()}/{filename}"


def _enrich(entry: dict[str, Any], media_dir: Path) -> dict[str, Any]:
    out = dict(entry)
    file_name = entry.get("file")
    thumb_name = entry.get("thumbnail")
    available = bool(file_name) and (media_dir / file_name).exists()
    has_thumbnail = bool(thumb_name) and (media_dir / thumb_name).exists()
    out["available"] = available
    out["media_url"] = _public_url(media_dir, file_name) if available else None
    out["thumbnail_url"] = _public_url(media_dir, thumb_name) if has_thumbnail else None
    return out


def exercise_routines() -> list[dict[str, Any]]:
    return [_enrich(e, EXERCISE_DIR) for e in _load_manifest(EXERCISE_DIR / "manifest.json")]


def meditations() -> list[dict[str, Any]]:
    return [_enrich(e, MEDITATION_DIR) for e in _load_manifest(MEDITATION_DIR / "manifest.json")]


def exercise_routine(routine_id: str) -> dict[str, Any] | None:
    return next((r for r in exercise_routines() if r["id"] == routine_id), None)


def meditation(meditation_id: str) -> dict[str, Any] | None:
    return next((m for m in meditations() if m["id"] == meditation_id), None)
