"""Kingshot job: collect stamina. 00:30 + 12:00 UTC (6am + 5:30pm IST), after dailies, before intel_mission.

World map -> compass -> Intel Mission -> meat icon (top right) -> "Get More": tap Gourmet Feast's button if it's
lit (grey = not ready yet), then close everything.
!! In Get More only that button is tapped: never Use (spends items), Buy & Use (gems), Go (shops), the "+".
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from core.schedule import At
from core.task import job
from core.vision import coloured_share
from jobs.intel_mission import open_intel, tap_to_exit
from regions import FEAST_BUTTON, GET_MORE_TITLE, INTEL_MEAT_ICON, NAV_REGION

if TYPE_CHECKING:
    from logging import Logger

    from core.phone import Phone
    from game import Kingshot


@job(schedule=At("00:30", "12:00", tz="UTC"), priority=105)   # 6am + 5:30pm IST, after dailies
def collect_stamina(app: Kingshot, phone: Phone, log: Logger):
    if phone.exists(text="World", region=NAV_REGION):            # on the town: the button names the world map
        phone.tap(text="World", region=NAV_REGION)
        phone.wait_for(text="Town", region=NAV_REGION, timeout=15)
    open_intel(app, phone, log)
    phone.tap_xy(*INTEL_MEAT_ICON)
    phone.wait_for(text="Get More", region=GET_MORE_TITLE, timeout=10)
    if coloured_share(phone.screen(), FEAST_BUTTON) > 0.3:
        phone.tap_xy((FEAST_BUTTON[0] + FEAST_BUTTON[2]) // 2, (FEAST_BUTTON[1] + FEAST_BUTTON[3]) // 2)
        time.sleep(1.5)
        tap_to_exit(phone, wait=2)                       # a reward pop-up, if one shows
        log.info("gourmet feast claimed")
    else:
        log.info("gourmet feast not ready (button grey)")
    phone.back()                                         # Get More -> Intel Mission
    phone.back()                                         # Intel Mission -> world map
