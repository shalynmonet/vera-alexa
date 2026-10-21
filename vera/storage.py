"""Tiny JSON file store. One file holds every user's profile, activity log,
earned milestones and any in-progress memory game.

Good enough for a hackathon demo: no database to install, easy to inspect,
easy to reset (just delete data/vera.json or run seed_demo.py).
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(os.environ.get("VERA_DATA", Path(__file__).resolve().parent.parent / "data" / "vera.json"))

_lock = threading.Lock()


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "friend"


def _empty_user(user_id: str, name: str | None = None) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "name": name or "Friend",
        "weekly_goal_days": 4,
        "activities": [],      # {"type", "date", "minutes", "details"}
        "milestones": [],      # {"id", "title", "earned_on"}
        "game": None,          # in-progress memory game
        "memories": [],        # {"fact", "recorded_on", "category"}
        "family": [],          # {"id", "name", "relationship", "email", "token"}
        "cheers": [],          # {"id", "family_id", "family_name", "milestone_id", "media_type", "file", "recorded_on", "queued", "played"}
    }


class Store:
    def __init__(self, path: Path | str = DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"users": {}}
        with self.path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self, data: dict[str, Any]) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(self.path)

    def get_user(self, user_id: str) -> dict[str, Any]:
        with _lock:
            data = self._load()
            return data["users"].get(user_id) or _empty_user(user_id)

    def save_user(self, user: dict[str, Any]) -> None:
        with _lock:
            data = self._load()
            data["users"][user["user_id"]] = user
            self._save(data)

    def reset(self) -> None:
        with _lock:
            self._save({"users": {}})

    def list_users(self) -> list[dict[str, Any]]:
        """Everyone with a profile, for the start screen's profile picker."""
        with _lock:
            data = self._load()
            return [{"user_id": uid, "name": u.get("name", "Friend")} for uid, u in data["users"].items()]

    def new_user_id(self, name: str) -> str:
        """A fresh, unique user_id slugified from a person's name (for 'Add a person')."""
        with _lock:
            data = self._load()
            base = _slugify(name)
            user_id = base
            n = 2
            while user_id in data["users"]:
                user_id = f"{base}-{n}"
                n += 1
            return user_id

    def find_family_member(self, token: str) -> tuple[str | None, dict[str, Any] | None]:
        """Resolve a family member's private record-page token to their
        (user_id, member record), scanning every user -- there's no login to
        scope the lookup by, so the token itself is the only key."""
        with _lock:
            data = self._load()
            for uid, u in data["users"].items():
                for member in u.get("family", []):
                    if member.get("token") == token:
                        return uid, member
            return None, None
