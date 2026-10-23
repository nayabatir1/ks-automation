"""Kingshot job: Voyage event (Deals). Every 8 h.

Deals (gift icon, top right) -> the Wavebound Voyage tab (found by its ship icon or name, wherever it is in the
tab row) while the event runs. Not there: do nothing.
Otherwise: green "Claim All" (ships back with chests) -> teal "Dispatch All" (sends them out again, ~8 h), then
Back to close Deals; the runner closes the game.
!! Never "Finish" / "Complete All" (speed up with items), the green "+", "Employ Voyager Team" or "Auto Voyage".
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import TYPE_CHECKING

from core.task import job
from core.vision import coloured_share, median_hue
from jobs.dailies import open_tab
from regions import (
    DEALS_LABEL,
    DEALS_TAB_ROW,
    SCREEN_TITLE,
    VOYAGE_BUTTON,
    VOYAGE_DURATION,
    VOYAGE_TAB,
)

if TYPE_CHECKING:
    from logging import Logger

    from core.phone import Phone
    from core.vision import Region
    from game import Kingshot

EVERY = timedelta(hours=8)  # the ships take ~8 h


@job()
def voyage(app: Kingshot, phone: Phone, log: Logger):
    # 1. Deals (top right) -> its first tab
    app.tap_on_main(phone, log, text="Deals", region=DEALS_LABEL)
    phone.wait_for(text="Deals", region=SCREEN_TITLE, timeout=10)
    if not open_voyage_tab(phone):
        log.info("voyage: event not running (no Wavebound Voyage tab in Deals); nothing to do")
        phone.back()  # close Deals
        return EVERY
    log.info("voyage open")

    # 2. Claim All (green) if ships are back, then Dispatch All (teal) if any can go out
    if tap_button(phone, "Claim All", hues=(35, 85)):
        log.info("voyage: claimed all")
        time.sleep(2)
    if tap_button(phone, "Dispatch All", hues=(75, 105)):
        log.info("voyage: dispatched all")
        time.sleep(2)

    # 3. how long the ships are out, then close Deals
    phone.forget_screen()
    log.info("voyage: ships back in %s", phone.read_duration(region=VOYAGE_DURATION) or "?")
    phone.back()  # close Deals
    return EVERY


def open_voyage_tab(phone: Phone) -> bool:
    """The Wavebound Voyage tab, wherever it is in the Deals tab row (a new event can push it along): already open,
    else its ship icon (big when selected, small with the name when not), else a tab named "Voyage" (the row is
    swiped to find it). True once the "Wavebound Voyage" sub-tab shows."""
    time.sleep(1.5)  # Deals settles (a swipe or tap right after it opens can be lost)
    if phone.exists(text="Voyage", region=VOYAGE_TAB, timeout=2):
        return True
    for icon in ("deals_voyage_ship_small", "deals_voyage_ship"):
        m = phone.find(image=icon, region=DEALS_TAB_ROW)
        if m:
            phone.tap_xy(*m.center)
            if phone.exists(text="Voyage", region=VOYAGE_TAB, timeout=5):
                return True
    return open_tab(phone, "Voyage") and phone.exists(text="Voyage", region=VOYAGE_TAB, timeout=5)


def tap_button(phone: Phone, label: str, hues: tuple[int, int], region: Region = VOYAGE_BUTTON) -> bool:
    """Tap the bottom-left button if it says `label` and is coloured (not grey) in the hue range."""
    m = phone.find(text=label, region=region)
    if not m:
        return False
    box = (m.x - 90, m.y - 20, m.x + m.w + 90, m.y + m.h + 25)  # the button around its label
    img = phone.last_screen
    if coloured_share(img, box) < 0.3 or not hues[0] <= median_hue(img, box) <= hues[1]:
        return False  # greyed out (nothing to do) or not the button we expect
    phone.tap_xy(*m.center)
    return True
