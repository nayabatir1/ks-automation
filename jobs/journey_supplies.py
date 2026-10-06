"""Kingshot job: claim journey supplies. 00:30 + 12:00 UTC (6am + 5:30pm IST), with intel_mission.

The free claim opens at 08:00 and 16:00 UTC; each run comes after one of those, so it finds one to claim.
Side panel (works from the town or the world map) -> scroll to its bottom -> Realm Journey -> "+" by the supply
counter -> green "Claim" (10 supplies) if it's green. !! Never the orange gem button ("Spend Gems to buy").
"""
import time

from core import vision
from core.phone import ElementNotFound
from core.schedule import At
from core.task import job
from regions import (
    JOURNEY_CLAIM,
    JOURNEY_CLOSE,
    JOURNEY_GO,
    JOURNEY_PLUS,
    LEFT_MID,
    SIDE_PANEL,
)


@job(schedule=At("00:30", "12:00", tz="UTC"), priority=112)   # 6am + 5:30pm IST, after intel_mission (110)
def journey_supplies(app, phone, log):
    phone.tap(image="side_tab", region=LEFT_MID, timeout=10)
    phone.wait_for(text="Wilderness", region=SIDE_PANEL, timeout=10)
    for _ in range(10):                                  # Realm Journey is the last section: scroll to the bottom
        phone.forget_screen()
        before = phone.screen(SIDE_PANEL)
        phone.swipe(330, 1450, 330, 700, ms=400)
        time.sleep(0.8)
        phone.forget_screen()
        if vision.screen_diff(before, phone.screen(SIDE_PANEL), SIDE_PANEL) < 2:
            break
    phone.wait_for(text="Realm Journey", region=SIDE_PANEL, timeout=5)
    phone.tap_xy(*JOURNEY_GO)
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
    phone.tap_xy(*JOURNEY_CLOSE)                         # close the supply box
    time.sleep(1)
    phone.back()                                         # Realm Journey -> city / world map
