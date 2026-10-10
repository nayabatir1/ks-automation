"""Kingshot job: <what it does>.  Copy to jobs/<name>.py (no leading underscore).

Starts on the city screen (bottom menu visible, no pop-up); game.py's on_open/before_job see to that.
The app is closed by the runner afterwards, also when the job fails.

Return when the job may run next:
    timedelta(...)  -> that long from now (e.g. a countdown read with phone.read_duration(region=...))
    datetime        -> exactly then
    None            -> next slot of schedule= (or retry_minutes if there is none)
Run it now:  .venv/bin/python run.py --job <name> --no-sleep
"""
from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from core.task import job
from regions import Q4

if TYPE_CHECKING:
    from logging import Logger

    from core.phone import Phone
    from game import Kingshot


@job(retry_minutes=30)
def my_job(app: Kingshot, phone: Phone, log: Logger):
    phone.tap(image="some_icon", region=Q4, timeout=10)    # templates/some_icon.png
    phone.wait_for(text="Some title", timeout=10)          # confirm the screen changed
    return timedelta(hours=1)
