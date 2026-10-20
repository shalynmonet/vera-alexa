"""Tiny JSON file store. One file holds every user's profile, activity log,
earned milestones and any in-progress memory game.

Good enough for a hackathon demo: no database to install, easy to inspect,
easy to reset (just delete data/vera.json or run seed_demo.py).
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(os.environ.get("VERA_DATA", Path(__file__).resolve().parent.parent / "data" / "vera.json"))

_lock = threading.Lock()


def _empty_user(user_id: str, name: str | None = None) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "name": name or "Friend",
        "weekly_goal_days": 4,
        "activities": [],      # {"type", "date", "minutes", "details"}
        "milestones": [],      # {"id", "title", "earned_on"}
        "game": None,          # in-progress memory game
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
