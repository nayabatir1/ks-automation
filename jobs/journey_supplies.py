"""Kingshot job: claim journey supplies. 00:05 + 12:00 UTC (5:35am + 5:30pm IST), with intel_mission.

The free claim opens at 08:00 and 16:00 UTC; each run comes after one of those, so it finds one to claim.
World map -> side panel -> Daily tab -> Realm Journey's arrow -> "+" by the supply counter -> green "Claim"
(10 supplies) if it's green. !! Never the orange gem button ("Spend Gems to buy").
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from core import vision
from core.phone import ElementNotFound
from core.schedule import At
from core.task import job
from jobs.online_rewards import ROW_BUTTON_X, close_panel, open_daily_tab
from regions import (
    JOURNEY_CLAIM,
    JOURNEY_CLOSE,
    JOURNEY_PLUS,
    SIDE_PANEL,
)

if TYPE_CHECKING:
    from logging import Logger

    from core.phone import Phone
    from game import Kingshot


@job(schedule=At("00:05", "12:00", tz="UTC"), priority=112)  # 5:35am + 5:30pm IST, after intel_mission (110)
def journey_supplies(app: Kingshot, phone: Phone, log: Logger):
    open_daily_tab(app, phone, log)
    row = phone.wait_for(text="Realm Journey", region=SIDE_PANEL, timeout=5)
    arrow = (ROW_BUTTON_X, row.center[1] + 23)
    box = (arrow[0] - 35, arrow[1] - 30, arrow[0] + 35, arrow[1] + 30)
    hue = vision.median_hue(phone.last_screen, box)
    if not 85 <= hue <= 100:  # the teal arrow ~92 (a green tick ~79)
        raise RuntimeError(f"Realm Journey: no teal arrow at {arrow} (hue {hue:.0f}); not tapping")
    phone.tap_xy(*arrow)
    time.sleep(3)
    phone.tap_xy(*JOURNEY_PLUS)
    try:
        m = phone.wait_for(text="Claim", region=JOURNEY_CLAIM, timeout=5)
    except ElementNotFound:
        log.info("journey supplies: not ready (Next Supply timer)")
        m = None
    if m:
        button = (m.x - 90, m.y - 20, m.x + m.w + 90, m.y + m.h + 25)
        if 35 <= vision.median_hue(phone.last_screen, button) <= 85:
            phone.tap_xy(*m.center)
            time.sleep(1.5)
            log.info("journey supplies: claimed 10")
        else:
            log.info("journey supplies: Claim isn't green; not tapping")
    phone.tap_xy(*JOURNEY_CLOSE)  # close the supply box
    time.sleep(1)
    phone.back()  # Realm Journey -> world map
    close_panel(phone)  # if the side panel is still open
