"""Pause switch (pause.json): while paused, the runner starts no sessions.

Set by hand (`run.py --pause 2h`, `run.py --resume`) or by the runner itself when the game says the account
was logged in on another device. A pause always ends by itself at `until`; jobs that came due meanwhile
simply run on the first tick after it.
"""
import json
import logging
from datetime import datetime, timedelta

import config
from core.schedule import utcnow

log = logging.getLogger("runner")


def get() -> dict | None:
    """{"until": datetime, "reason": str} while paused, else None (an expired pause file is removed)."""
    try:
        data = json.loads(config.PAUSE_FILE.read_text())
        until = datetime.fromisoformat(data["until"])
    except (FileNotFoundError, ValueError, KeyError):
        return None
    if until <= utcnow():
        config.PAUSE_FILE.unlink(missing_ok=True)
        log.info("Pause (%s) is over; running all pending jobs", data.get("reason", ""))
        return None
    return {"until": until, "reason": data.get("reason", "")}


def pause_for(duration: timedelta, reason: str) -> datetime:
    until = utcnow() + duration
    config.PAUSE_FILE.write_text(json.dumps({"until": until.isoformat(timespec="seconds"), "reason": reason}))
    return until


def resume() -> bool:
    """Clear the pause. Returns True if there was one."""
    was = get() is not None
    config.PAUSE_FILE.unlink(missing_ok=True)
    return was
