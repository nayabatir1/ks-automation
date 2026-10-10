"""Kingshot job: recruit heroes.

Starts on the city screen or world map (bottom menu visible, no pop-up) — game.py's on_open/before_job
open the game and close all pop-ups first; after_job backs out to where it started.
"""
from __future__ import annotations

import re
from datetime import timedelta
from typing import TYPE_CHECKING

from core.task import job
from core.timeparse import parse_duration
from core.vision import median_hue
from regions import (
    ADVANCED_TIMER,
    ADVANCED_X1,
    EPIC_TIMER,
    EPIC_X1,
    HEROES_TITLE,
    NAV_Q3,
    RECRUIT_BUTTON,
    RECRUIT_TITLE,
)

if TYPE_CHECKING:
    from logging import Logger

    from core.phone import Phone
    from core.vision import Region
    from game import Kingshot

TAP_TO_EXIT = (0.2, 0.84, 0.8, 0.88)     # Rewards screen: "Tap anywhere to exit" (an orange paid Recruit x1 sits above it)


@job()
def recruit_heroes(app: Kingshot, phone: Phone, log: Logger):
    # 1. "Heroes" in the bottom menu (Q3); its red dot may come and go, so match the text
    app.tap_on_main(phone, log, text="Heroes", region=NAV_Q3)
    phone.wait_for(text="Heroes", region=HEROES_TITLE, timeout=10)
    log.info("heroes screen open")

    # 2. "Recruit Heroes" (bottom right) -> Hero Recruitment (Advanced / Epic)
    phone.tap(text="Recruit Heroes", region=RECRUIT_BUTTON, timeout=10)
    phone.wait_for(text="Recruitment", region=RECRUIT_TITLE, timeout=10)
    log.info("hero recruitment screen open")

    # 3. Advanced and Epic: tap the green "Recruit x1 / Free" if it's there, then read "Next free: ..." above it.
    #    !! Every other recruit button is orange and costs keys: never tapped.
    waits = [recruit_free(phone, log, "advanced", ADVANCED_X1, ADVANCED_TIMER),
             recruit_free(phone, log, "epic", EPIC_X1, EPIC_TIMER)]
    waits = [w for w in waits if w is not None]
    if not waits:
        raise RuntimeError("could not read either 'Next free' timer")
    return min(waits) + timedelta(seconds=10)


def recruit_free(phone: Phone, log: Logger, kind: str, button: Region, timer: Region) -> timedelta | None:
    """Free recruit if the button is green and says Free; returns the time to the next free one (or None)."""
    m = phone.find(text="Free", region=button)
    if m and 35 <= median_hue(phone.last_screen, button) <= 85:
        phone.tap_xy(*m.center)
        exit_text = phone.wait_for(text="Tap anywhere", region=TAP_TO_EXIT, timeout=15)
        for _ in range(8):                          # taps during the chest animation are ignored: tap again
            phone.tap_xy(*exit_text.center)
            if phone.exists(text="Recruitment", region=RECRUIT_TITLE, timeout=1.5):
                break
        else:
            raise RuntimeError("the Rewards screen didn't close")
        log.info("%s: free recruit done", kind)
    wait = next_free(phone, timer)
    log.info("%s: next free in %s", kind, wait)
    return wait


def next_free(phone: Phone, timer: Region, tries: int = 3) -> timedelta | None:
    """'Next free: 1d 07:59:52' -> timedelta. OCR now and then drops part of it, so only a reading with a whole
    h:mm:ss clock counts; None if there isn't one (e.g. Advanced shows "Daily free recruitments: 5")."""
    for _ in range(tries):
        text = phone.read_text(timer)
        if re.search(r"\d:\d\d:\d\d", text):
            return parse_duration(text)
        phone.forget_screen()
    return None
