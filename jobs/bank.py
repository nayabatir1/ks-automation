"""Kingshot job: Bank (Deals > Bank), the Daily 5% box. Runs when its countdown ends.

Deals (gift icon, top right) -> Bank tab -> the Daily 5% box: "Withdraw" once its day is up (deposit + 5%), then
"Deposit" again (the dialog starts at the maximum). "In Deposit" = still running. The countdown above the box
says when it's due; the job runs again just after it.
!! Never "TOP UP NOW" (real money) or the other boxes (7 / 15 / 30 days).
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import TYPE_CHECKING

import config
from core import vision
from core.task import job
from jobs.dailies import back_to_main, dismiss_popup, open_tab
from regions import (
    BANK_DAILY_BUTTON,
    BANK_DAILY_TIMER,
    BANK_DIALOG_DEPOSIT,
    DEALS_LABEL,
    SCREEN_TITLE,
)

if TYPE_CHECKING:
    from logging import Logger

    from core.phone import Phone
    from core.vision import Region
    from game import Kingshot


@job()
def bank(app: Kingshot, phone: Phone, log: Logger):
    app.tap_on_main(phone, log, text="Deals", region=DEALS_LABEL, then={"text": "Deals", "region": SCREEN_TITLE})
    phone.wait_for(text="Deals", region=SCREEN_TITLE, timeout=10)
    time.sleep(2)  # the page settles first: a swipe right after it opens is lost
    if not open_tab(phone, "Bank"):
        raise RuntimeError("no Bank tab in Deals")
    daily_box(phone, log)
    time.sleep(1)
    phone.forget_screen()
    wait = phone.read_duration(region=BANK_DAILY_TIMER)
    back_to_main(phone)
    if wait is None:
        log.info("bank: can't read the Daily 5%% countdown; looking again in %d min", config.RETRY_MINUTES)
        return timedelta(minutes=config.RETRY_MINUTES)
    log.info("bank: daily box due in %s", wait)
    return wait + timedelta(seconds=30)  # just after it's due


def daily_box(phone: Phone, log: Logger) -> None:
    """The Daily 5% box: Withdraw if its day is up, then Deposit (the maximum) if it can."""
    time.sleep(1)
    phone.forget_screen()
    text = phone.read_text(BANK_DAILY_BUTTON)
    if "Withdraw" in text:
        phone.tap_xy(*button_centre(BANK_DAILY_BUTTON))
        dismiss_popup(phone)  # Rewards: the gems back
        log.info("bank: withdrew")
        phone.forget_screen()
        text = phone.read_text(BANK_DAILY_BUTTON)
    if "In Deposit" in text:
        log.info("bank: still in deposit")
        return
    if "Deposit" not in text:
        log.info("bank: daily box shows %r; not touching it", text)
        return
    phone.tap_xy(*button_centre(BANK_DAILY_BUTTON))
    m = phone.wait_for(text="Deposit", region=BANK_DIALOG_DEPOSIT, timeout=5)
    button = (m.x - 120, m.y - 25, m.x + m.w + 120, m.y + m.h + 30)
    if not 75 <= vision.median_hue(phone.last_screen, button) <= 105:
        raise RuntimeError("the deposit dialog's Deposit button isn't teal; not tapping")
    phone.tap_xy(*m.center)
    time.sleep(1.5)
    log.info("bank: deposited (the maximum)")


def button_centre(region: Region) -> tuple[int, int]:
    x1, y1, x2, y2 = region
    return int((x1 + x2) / 2 * 1080), int((y1 + y2) / 2 * 2340)
