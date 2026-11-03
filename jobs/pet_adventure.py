"""Kingshot job: pet adventure. 00:05 + 12:00 UTC (5:35am + 5:30pm IST), after intel_mission.

World map -> side panel -> Daily tab -> Pet Adventure's arrow -> Ally Treasure (bottom right) -> its "Claim All"
(green) -> tap away the rewards -> close (X) -> the page's "Claim All" (green; finished hunts) -> tap away the
rewards -> "Hunt All" (teal; sends the pets out) -> Back to the world map.
Each button only when it's there and in its colour; Ally Treasure has no Claim All once the day's claims are used.
No Pet Adventure row in the Daily tab (hidden once done): nothing to do.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from core import vision
from core.schedule import At
from core.task import job
from jobs.online_rewards import ROW_BUTTON_X, close_panel, find_daily_row, open_daily_tab
from regions import (
    ALLY_CLAIM_ALL,
    ALLY_CLOSE,
    ALLY_TITLE,
    PET_ALLY_TREASURE,
    PET_BUTTON,
    PET_TITLE,
    REWARDS_EXIT,
)

if TYPE_CHECKING:
    from logging import Logger

    from core.phone import Phone
    from game import Kingshot

GREEN = (60, 80)  # hue of a green button (~70)
TEAL = (85, 100)  # hue of the teal Hunt All (~91)
BLANK_SPOT = (540, 250)  # "Tap anywhere to exit" the rewards


@job(schedule=At("00:05", "12:00", tz="UTC"), priority=113)  # 5:35am + 5:30pm IST, after intel_mission (110)
def pet_adventure(app: Kingshot, phone: Phone, log: Logger):
    open_daily_tab(app, phone, log)
    row = find_daily_row(phone, "Pet Adventure")
    if not row:  # hidden once done for now ("Hide after mission completion"): nothing to do
        log.info("no Pet Adventure row in the Daily tab (hidden: done for now)")
        close_panel(phone)
        return
    phone.tap_xy(ROW_BUTTON_X, row.center[1] + 23)  # its arrow
    phone.wait_for(text="Pet Adventure", region=PET_TITLE, timeout=10)
    log.info("pet adventure open")

    # Ally Treasure: the alliance's shared chests
    phone.tap_xy(*PET_ALLY_TREASURE)
    phone.wait_for(text="Ally Treasure", region=ALLY_TITLE, timeout=10)
    if claim(phone, log, "Claim All", ALLY_CLAIM_ALL, GREEN):
        log.info("ally treasure claimed")
    else:
        log.info("ally treasure: nothing to claim")
    phone.tap_xy(*ALLY_CLOSE)
    phone.wait_gone(text="Ally Treasure", region=ALLY_TITLE, timeout=5)

    # finished hunts, then send the pets out again
    if claim(phone, log, "Claim All", PET_BUTTON, GREEN):
        log.info("hunt rewards claimed")
    if press(phone, "Hunt All", PET_BUTTON, TEAL, timeout=6):  # it shows a moment after the claim
        time.sleep(2)
        log.info("hunt all: pets sent out")
    else:
        log.info("no Hunt All (pets still out)")

    phone.back()  # Pet Adventure -> world map
    time.sleep(1.5)


def press(phone: Phone, label: str, region, hues: tuple[int, int], timeout: float = 0) -> bool:
    """Tap the button only when it's there and in its colour; look again until `timeout` (s) is up."""
    end = time.monotonic() + timeout
    while True:
        phone.forget_screen()
        m = phone.find(text=label, region=region)
        if m:
            box = (m.x - 60, m.y - 20, m.x + m.w + 60, m.y + m.h + 20)
            if hues[0] <= vision.median_hue(phone.last_screen, box) <= hues[1]:
                phone.tap_xy(*m.center)
                return True
        if time.monotonic() >= end:
            return False
        time.sleep(1)


def claim(phone: Phone, log: Logger, label: str, region, hues: tuple[int, int]) -> bool:
    """press(), then tap away the rewards screen. A tap can go to the system bars instead: then once more."""
    for _ in range(2):
        if not press(phone, label, region, hues):
            return False
        if phone.exists(text="Tap anywhere", region=REWARDS_EXIT, timeout=5):
            phone.tap_xy(*BLANK_SPOT)
            phone.wait_gone(text="Tap anywhere", region=REWARDS_EXIT, timeout=5)
            time.sleep(1)
            return True
        log.info("%s: no rewards screen; tapping again", label)
    return False
