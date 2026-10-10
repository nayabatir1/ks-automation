"""Remembers per task / per job (state.json). All times are UTC.

    "example_settings":        {"last_run": ..., "status": "ok", "error": null, "duration_s": 12.3}
    "tower_defense.free_chest": {..., "next_at": "2026-10-03T14:20:00+00:00"}

Jobs are keyed "task.job" and carry next_at — when they can run next. Keyed by name (not by
time) so each job has exactly one entry; "what's next" is just these sorted by next_at.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class State:
    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self.data = json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = {}

    def last_run(self, name: str) -> datetime | None:
        return _parse(self.data.get(name, {}).get("last_run"))

    def next_at(self, name: str) -> datetime | None:
        return _parse(self.data.get(name, {}).get("next_at"))

    def record(self, name: str, started: datetime, status: str, error: str | None = None, seconds: float | None = None,
               next_at: datetime | None = None):
        entry = {
            "last_run": started.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "status": status,
            "error": error,
            "duration_s": round(seconds, 1) if seconds is not None else None,
        }
        if next_at is not None:
            entry["next_at"] = next_at.astimezone(timezone.utc).isoformat(timespec="seconds")
        try:                       # re-read first: other jobs' entries may have changed (a hand edit, another run)
            self.data = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        self.data[name] = entry
        self.save()

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2))
        os.replace(tmp, self.path)  # atomic, so a crash never leaves half a file
