"""Kingshot job: claim rewards. 00:30 + 11:30 UTC (6am + 5pm IST), after intel_mission.
Parts: mail_rewards, alliance_rewards, help_members.
Test one part: run.py --job claim_rewards --part alliance_rewards
Starts on the city screen or world map; after_job backs out to where it started.
"""
import time

import cv2

from core.phone import ElementNotFound
from core.schedule import At
from core.task import job, run_parts
from jobs.intel_mission import tap_to_exit
from regions import (
    ALLIANCE_CHESTS,
    ALLIANCE_HELP,
    ALLIANCE_TITLE,
    BIG_CHEST,
    CHEST_CLAIM_ALL,
    CHEST_TABS,
    HELP_ALL,
    MAIL_BUTTON,
    MAIL_CLAIM_ALL,
    MAIL_TABS,
    NAV_Q4,
    SCREEN_TITLE,
)


@job(schedule=At("00:30", "11:30", tz="UTC"), priority=115)   # 6am + 5pm IST, right after intel_mission (110)
def claim_rewards(app, phone, log):
    run_parts(app, phone, log, {"mail_rewards": mail_rewards, "alliance_rewards": alliance_rewards,
                                "help_members": help_members})


def mail_rewards(app, phone, log):
    """Mail (envelope, bottom right) -> on the Alliance, System and Reports tabs: "Read & Claim All", then close the
    Rewards pop-up. Wars and Starred are left alone. !! Never "Delete Read"."""
    app.tap_on_main(phone, log, image="mail_button", region=MAIL_BUTTON)
    phone.wait_for(text="Mail", region=SCREEN_TITLE, timeout=10)
    log.info("mail open")
    for tab, xy in MAIL_TABS.items():
        phone.tap_xy(*xy)
        time.sleep(1.5)
        phone.forget_screen()
        try:
            phone.tap(text="Claim All", region=MAIL_CLAIM_ALL, timeout=5)
        except ElementNotFound:
            log.info("mail, %s: no Read & Claim All", tab)
            continue
        time.sleep(1.5)
        tap_to_exit(phone, wait=3)                       # the Rewards pop-up, if anything was claimed
        log.info("mail, %s: read & claimed all", tab)
    phone.back()                                         # Mail -> city / world map


def alliance_rewards(app, phone, log):
    """Alliance (bottom menu) -> Chests: "Claim All" on the Loot Chest and Alliance Gift tabs (found by its text: it
    sits in a different place on each tab), then open the big chest while it glows (its badge number changes, so
    the glow decides). !! Never "Go" (shops) or the anonymous-gift checkbox."""
    open_alliance(app, phone, log)
    phone.tap_xy(*ALLIANCE_CHESTS)
    phone.wait_for(text="Chests", region=SCREEN_TITLE, timeout=10)
    log.info("alliance chests open")
    for tab, xy in CHEST_TABS.items():
        phone.tap_xy(*xy)
        time.sleep(1.5)
        phone.forget_screen()
        try:
            phone.tap(text="Claim All", region=CHEST_CLAIM_ALL, timeout=5)
        except ElementNotFound:
            log.info("chests, %s: no Claim All", tab)
            continue
        time.sleep(1.5)
        tap_to_exit(phone, wait=3)                       # the Rewards pop-up, if anything was claimed
        log.info("chests, %s: claimed all", tab)
    for n in range(10):                                  # big chest: open while it glows
        phone.forget_screen()
        if not chest_glowing(phone.screen()):
            break
        x1, y1, x2, y2 = BIG_CHEST
        phone.tap_xy((x1 + x2) // 2, (y1 + y2) // 2)
        time.sleep(2)
        tap_to_exit(phone, wait=3)
        log.info("chests: big chest opened (%d)", n + 1)
    phone.back()                                         # Chests -> Alliance
    phone.back()                                         # Alliance -> city / world map


def help_members(app, phone, log):
    """Alliance -> Help -> "Help All" (helps every member's request; earns alliance tokens). Nothing to do when the
    button isn't there (nobody left to help). !! Never "View" (Auto-Help is a paid monthly card)."""
    open_alliance(app, phone, log)
    phone.tap_xy(*ALLIANCE_HELP)
    phone.wait_for(text="Help", region=SCREEN_TITLE, timeout=10)
    try:
        phone.tap(text="Help All", region=HELP_ALL, timeout=3)
        time.sleep(1.5)
        log.info("help: helped all")
    except ElementNotFound:
        log.info("help: nobody to help")
    phone.back()                                         # Help -> Alliance
    phone.back()                                         # Alliance -> city / world map


def open_alliance(app, phone, log):
    app.tap_on_main(phone, log, text="Alliance", region=NAV_Q4)
    phone.wait_for(text="Alliance", region=ALLIANCE_TITLE, timeout=10)


def chest_glowing(img):
    """The big chest can be opened: its lid is open with bright light (glowing ~6,100-6,700 white px; shut ~2,900)."""
    x1, y1, x2, y2 = BIG_CHEST
    hsv = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    return int(((hsv[:, :, 1] < 50) & (hsv[:, :, 2] > 245)).sum()) > 4500
