"""Kingshot job: pet adventure. 00:05 + 12:00 UTC (5:35am + 5:30pm IST), after intel_mission.

World map -> side panel -> Daily tab -> Pet Adventure's arrow, then the parts (each can be switched off in jobs.toml):
- ally_treasure: Ally Treasure (bottom right) -> its "Claim All" (green) -> tap away the rewards -> close (X)
- my_shares: Ally Treasure -> red dot on "My Shares": that tab -> tap every teal "Share" -> close (X)
- hunt: the page's "Claim All" (green; finished hunts) -> tap away the rewards -> "Hunt All" (teal; pets out)
Then Back to the world map.
Each button only when it's there and in its colour; Ally Treasure has no Claim All once the day's claims are used.
No Pet Adventure row in the Daily tab (hidden once done): nothing to do.
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

import cv2

from core import vision
from core.schedule import At
from core.task import job, run_parts
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
    from core.vision import Image, TextTarget
    from game import Kingshot

GREEN = (60, 80)  # hue of a green button (~70)
TEAL = (85, 100)  # hue of the teal Hunt All (~91)
BLANK_SPOT = (540, 250)  # "Tap anywhere to exit" the rewards
MY_SHARES_TAB = (297, 718)  # Ally Treasure: the "My Shares" tab (left; "Alliance Shares" is right)
MY_SHARES_DOT = (495, 640, 560, 700)  # its red dot (top right of the tab): a chest of ours to share
ALLY_LIST = (0.6, 0.33, 0.95, 0.83)  # Ally Treasure: the list's buttons (teal Share / View at the right of each row)
SHARE = re.compile(r"^Share$")  # the button only, not the "My Shares" / "Alliance Shares" tabs
MAX_SHARE_SCROLLS = 10  # the list's end is found by the screen not moving; this only stops a runaway


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

    run_parts(app, phone, log, {"ally_treasure": ally_treasure, "my_shares": my_shares, "hunt": hunt})
    phone.back()  # Pet Adventure -> world map
    time.sleep(1.5)


def ally_treasure(app: Kingshot, phone: Phone, log: Logger) -> None:
    """Ally Treasure: the alliance's shared chests -> its green Claim All."""
    open_ally_treasure(phone)
    if claim(phone, log, "Claim All", ALLY_CLAIM_ALL, GREEN):
        log.info("ally treasure claimed")
    else:
        log.info("ally treasure: nothing to claim")
    close_ally_treasure(phone)


def my_shares(app: Kingshot, phone: Phone, log: Logger) -> None:
    """Ally Treasure > My Shares: when its tab has a red dot, tap every teal Share (a chest of ours not shared yet;
    the tap shares it at once, no pop-up, and the button turns into View). The list scrolls: look to its end."""
    open_ally_treasure(phone)
    if not red_dot(phone.screen(), MY_SHARES_DOT):
        log.info("my shares: nothing to share (no red dot)")
        close_ally_treasure(phone)
        return
    phone.tap_xy(*MY_SHARES_TAB)
    time.sleep(1.5)
    shared = 0
    for _ in range(MAX_SHARE_SCROLLS):
        while press(phone, SHARE, ALLY_LIST, TEAL):
            shared += 1
            time.sleep(1.5)
        img = phone.screen(ALLY_LIST)
        phone.swipe(540, 1700, 540, 1100, ms=700)
        time.sleep(1)
        phone.forget_screen()
        if vision.screen_diff(img, phone.screen(ALLY_LIST), ALLY_LIST) < 2:  # the list's end
            break
    log.info("my shares: %d chest(s) shared", shared)
    close_ally_treasure(phone)


def hunt(app: Kingshot, phone: Phone, log: Logger) -> None:
    """Pet Adventure: finished hunts (green Claim All), then send the pets out again (teal Hunt All)."""
    if claim(phone, log, "Claim All", PET_BUTTON, GREEN):
        log.info("hunt rewards claimed")
    if press(phone, "Hunt All", PET_BUTTON, TEAL, timeout=6):  # it shows a moment after the claim
        time.sleep(2)
        log.info("hunt all: pets sent out")
    else:
        log.info("no Hunt All (pets still out)")


def open_ally_treasure(phone: Phone) -> None:
    phone.tap_xy(*PET_ALLY_TREASURE)
    phone.wait_for(text="Ally Treasure", region=ALLY_TITLE, timeout=10)


def close_ally_treasure(phone: Phone) -> None:
    phone.tap_xy(*ALLY_CLOSE)
    phone.wait_gone(text="Ally Treasure", region=ALLY_TITLE, timeout=5)


def red_dot(img: Image, box: tuple[int, int, int, int]) -> bool:
    """A red notification dot inside box (x1, y1, x2, y2, pixels)."""
    x1, y1, x2, y2 = box
    hsv = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    red = ((hsv[:, :, 0] <= 8) | (hsv[:, :, 0] >= 172)) & (hsv[:, :, 1] > 150) & (hsv[:, :, 2] > 150)
    return int(red.sum()) > 60


def press(phone: Phone, label: TextTarget, region, hues: tuple[int, int], timeout: float = 0) -> bool:
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
