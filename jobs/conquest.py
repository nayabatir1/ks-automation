"""Kingshot job: conquest.

Starts on the city screen or world map (bottom menu visible, no pop-up) — game.py's on_open/before_job
open the game and close all pop-ups first.
"""
from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from core.phone import ElementNotFound
from core.schedule import utcnow
from core.task import job
from core.vision import coloured_share
from regions import (
    BLANK_SPOT,
    CHEST_CLAIM,
    CONQUER_BUTTON,
    IDLE_BOX_TOP,
    IDLE_CLAIM,
    NAV_Q3,
)

if TYPE_CHECKING:
    from logging import Logger

    from core.phone import Phone
    from game import Kingshot

IDLE_FULL = timedelta(hours=9)      # "Max Idle Time: 9 hrs"


@job()
def conquest(app: Kingshot, phone: Phone, log: Logger):
    # 1. "Conquest" at the bottom-left of the bottom menu (Q3); its red dot may come and go, so match the text
    app.tap_on_main(phone, log, text="Conquest", region=NAV_Q3)
    phone.wait_for(text="Conquer", region=CONQUER_BUTTON, timeout=10)   # conquest screen: big "Conquer" button
    log.info("conquest screen open")

    # 2. the chest's "Claim" button (right side, above the stage track) -> "Idle Income" box.
    #    Green = something to claim; grey (right after a claim) = nothing yet, and tapping it does nothing.
    try:
        m = phone.wait_for(text="Claim", region=CHEST_CLAIM, timeout=5)
        green = coloured_share(phone.last_screen, (m.x - 50, m.y - 12, m.x + m.w + 50, m.y + m.h + 12)) > 0.3
    except ElementNotFound:
        green = False
    if green:
        phone.tap_xy(*m.center)
    else:
        known = app.previous_next_at
        if known and known > utcnow():
            log.info("nothing to claim yet; keeping the known time")
            return known
        log.info("nothing to claim yet; checking again in %s", IDLE_FULL)
        return IDLE_FULL
    phone.wait_for(text="Idle Time", region=IDLE_BOX_TOP, timeout=10)    # "Idle Time 09:00:00 (Max)"
    log.info("idle income box open")

    # 3. the box's big green "Claim"
    phone.tap(text="Claim", region=IDLE_CLAIM, timeout=10)
    phone.wait_gone(text="Idle Time", region=IDLE_BOX_TOP, timeout=10)
    log.info("idle income claimed")

    # 4. "Rewards" screen: "Tap anywhere to exit"
    phone.wait_for(text="Tap anywhere", region=CONQUER_BUTTON, timeout=10)
    phone.tap_xy(*BLANK_SPOT)
    phone.wait_gone(text="Tap anywhere", region=CONQUER_BUTTON, timeout=10)

    # idle income fills up to its 9 h maximum: come back then (the runner then does the next due job,
    # or closes the game)
    return IDLE_FULL
