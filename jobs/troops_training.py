"""Kingshot job: troops training. 00:30 + 11:30 UTC (6am + 5pm IST), first job of those sessions.

Town: Barracks -> tap twice (the first tap collects finished troops) -> menu "Train" -> training page. Its bottom
tabs switch between Barracks / Stable / Range; on each: quantity 950 -> Train. A tab that is still training shows
"Speedups" instead of Train and is left alone.
!! Never Finish (gems) or Speedups.
"""
import time

from core.phone import ElementNotFound
from core.schedule import At
from core.task import job
from core.timeparse import parse_duration
from regions import (
    NAV_REGION,
    TRAIN_BUTTON,
    TRAIN_LABEL,
    TRAIN_QTY,
    TRAIN_QTY_FIELD,
    TRAIN_TABS,
    TRAIN_TIMER,
    TRAIN_TITLE,
)
from town import go_to_building

QUANTITY = 950
QTY_BOX = (810, 1892)             # the quantity box


@job(schedule=At("00:30", "11:30", tz="UTC"), priority=90)   # 6am + 5pm IST, first in those sessions
def troops_training(app, phone, log):
    if phone.exists(text="Town", region=NAV_REGION):            # on the world map: the button names the town
        phone.tap(text="Town", region=NAV_REGION)
        phone.wait_for(text="World", region=NAV_REGION, timeout=15)
    x, y = go_to_building(phone, log, "Barracks", view=app.town_view)
    app.town_view = None
    open_training(phone, x, y)
    log.info("training page open")

    waits = []
    for tab, xy in TRAIN_TABS.items():
        phone.tap_xy(*xy)
        phone.wait_for(text="Apex", region=TRAIN_TITLE, timeout=10)
        time.sleep(1.5)                                  # the page settles (it can show "Train" for a moment)
        phone.forget_screen()
        if phone.exists(text="Training", region=TRAIN_TIMER):
            log.info("%s: still training", tab)
        elif phone.exists(text="Train", region=TRAIN_BUTTON):
            set_quantity(phone)
            phone.tap(text="Train", region=TRAIN_BUTTON, timeout=5)
            time.sleep(1.5)
            log.info("%s: training %d", tab, QUANTITY)
        else:
            raise RuntimeError(f"{tab}: neither Training nor a Train button; not touching it")
        phone.forget_screen()
        wait = parse_duration(phone.read_text(TRAIN_TIMER))
        if wait:
            waits.append(wait)
    phone.back()                                         # training page -> town
    log.info("next training done in %s", min(waits) if waits else "?")


def open_training(phone, x, y):
    """Tap the building until its menu shows (the first tap may only collect troops), then the menu's Train."""
    for _ in range(3):
        phone.tap_xy(x, y)
        try:
            m = phone.wait_for(text="Train", region=TRAIN_LABEL, timeout=2.5)
            break
        except ElementNotFound:
            continue
    else:
        raise ElementNotFound("the Barracks menu (Details / Upgrade / Train) didn't show")
    phone.tap_xy(m.center[0], m.center[1] - 88)         # the hexagon icon above its label
    phone.wait_for(text="Apex", region=TRAIN_TITLE, timeout=10)


def set_quantity(phone):
    phone.tap_xy(*QTY_BOX)
    phone.wait_for(text="OK", region=TRAIN_QTY_FIELD, timeout=3)   # !! else OK's spot is the Speedups button
    phone.key("KEYCODE_MOVE_END")
    for _ in range(6):
        phone.key("KEYCODE_DEL")
    phone.type_text(str(QUANTITY))
    phone.tap(text="OK", region=TRAIN_QTY_FIELD, timeout=3)
    time.sleep(1)
    phone.forget_screen()
    read = phone.read_text(TRAIN_QTY).replace(",", "")
    if str(QUANTITY) not in read:
        raise RuntimeError(f"quantity reads {read!r}, not {QUANTITY}; not training")

