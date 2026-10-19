"""Kingshot job: online rewards.
World map -> side panel -> Daily tab: "Online Rewards" is listed only while a chest is ready; its green tick
claims it, then the chest screen tells when the next one is ready. Not listed: look again later.

Starts on the city screen or world map (bottom menu visible, no pop-up) — game.py's on_open/before_job
see to that.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import cv2
import numpy as np

import config
from core.phone import ElementNotFound
from core.schedule import utcnow
from core.task import job
from core.vision import median_hue
from regions import (
    BLANK_SPOT,
    CHEST_TIMER,
    LEFT_MID,
    NAV_REGION,
    PANEL_TAB,
    Q4,
    SIDE_PANEL,
    SIDE_PANEL_DAILY_TAB,
)

if TYPE_CHECKING:
    from logging import Logger

    from core.phone import Phone
    from core.vision import Image
    from game import Kingshot

TICK_X = 606  # the green tick at the right end of the Online Rewards row


def no_reward_yet(app: Kingshot, log: Logger) -> datetime | timedelta:
    """No chest ready: keep the chest time we already know if it's still ahead, else look again later."""
    known = app.previous_next_at
    if known and known > utcnow():
        log.info("no online reward ready yet; keeping the known chest time")
        return known
    log.info("no online reward ready yet; checking again in %d min", config.RETRY_MINUTES)
    return timedelta(minutes=config.RETRY_MINUTES)


def close_panel(phone: Phone) -> None:
    """Close the side panel with its "<" tab (Back there would open the game's quit prompt).
    Closing the chest screen with a tap outside the panel can close the panel too: then there's nothing to do."""
    if not phone.exists(text="Wilderness", region=SIDE_PANEL, timeout=1):
        return
    phone.tap(image="side_tab_close", region=PANEL_TAB, timeout=5)
    phone.wait_gone(text="Wilderness", region=SIDE_PANEL, timeout=5)


@job()
def online_rewards(app: Kingshot, phone: Phone, log: Logger):
    # 1. World button (Q4) -> world map; the button then reads "Town". Skip if already there.
    if phone.exists(text="Town", region=NAV_REGION):
        log.info("already on the world map")
    else:
        app.tap_on_main(phone, log, image="world_icon", region=Q4, then={"text": "Town", "region": NAV_REGION})
        phone.wait_for(text="Town", region=NAV_REGION, timeout=15)
        log.info("on the world map")

    # 2. side tab ">" on the left edge, middle of the screen -> side panel (tabs Town / Wilderness / Daily).
    #    Skip if the panel is already open (the tab is hidden then).
    if (
        phone.wait_any(
            {"text": "Wilderness", "region": SIDE_PANEL}, {"image": "side_tab", "region": LEFT_MID}, timeout=10
        )
        == 0
    ):
        log.info("side panel already open")
    else:
        phone.tap(image="side_tab", region=LEFT_MID, timeout=5)
        phone.wait_for(text="Wilderness", region=SIDE_PANEL, timeout=10)
        log.info("side panel open")

    # 3. the Daily tab (its label doesn't OCR: tapped by position; the chosen tab is the bright one)
    for _ in range(3):
        if daily_tab_chosen(phone.screen()):
            break
        phone.tap_xy(*SIDE_PANEL_DAILY_TAB)
        time.sleep(1.5)
        phone.forget_screen()
    else:
        raise ElementNotFound("the side panel's Daily tab didn't open")
    log.info("daily tab open")

    # 4. "Online Rewards" (under My Rewards, at the top) is only listed while a chest is ready
    m = phone.find(text="Online Rewards", region=SIDE_PANEL)
    if not m:
        close_panel(phone)
        return no_reward_yet(app, log)
    log.info("found Online Rewards at %s", m.center)

    # 5. its green tick (right end of the row) claims the chest -> chest screen with "Next Chest Ready In: 01:47:56"
    tick = (TICK_X, m.center[1] + 23)
    hue = median_hue(phone.last_screen, (tick[0] - 35, tick[1] - 30, tick[0] + 35, tick[1] + 30))
    if not 65 <= hue <= 86:  # green tick ~79; the teal arrow buttons ~92
        raise RuntimeError(f"Online Rewards: no green tick at {tick} (hue {hue:.0f}); not tapping")
    phone.tap_xy(*tick)
    phone.wait_for(text="Next Chest Ready", region=CHEST_TIMER, timeout=10)
    log.info("online reward claimed")

    # 6. record when the next chest is ready, then tap a blank spot: that closes the chest screen and the panel
    wait = None
    for _ in range(8):  # the countdown is drawn a moment after "Next Chest Ready" shows
        wait = phone.read_duration(region=CHEST_TIMER)
        if wait is not None:
            break
        time.sleep(0.5)
        phone.forget_screen()
    if wait is None:
        raise RuntimeError("could not read the 'Next Chest Ready In' countdown")
    log.info("next chest in %s", wait)
    phone.tap_xy(*BLANK_SPOT)
    phone.wait_gone(text="Next Chest Ready", region=CHEST_TIMER, timeout=10)
    close_panel(phone)  # usually already closed
    return wait + timedelta(seconds=10)  # a little after it's ready


def daily_tab_chosen(img: Image) -> bool:
    """The chosen tab is bright (median brightness ~180); the others are dark (~99)."""
    x, y = SIDE_PANEL_DAILY_TAB
    hsv = cv2.cvtColor(img[y - 30 : y + 30, x - 90 : x + 90], cv2.COLOR_BGR2HSV)
    return float(np.median(hsv[:, :, 2])) > 140
