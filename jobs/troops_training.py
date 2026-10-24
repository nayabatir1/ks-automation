"""Kingshot job: troops training. Runs again when the slowest of the three trainings is done.

Town: Barracks -> tap twice (the first tap collects finished troops) -> menu "Train" -> training page. Its bottom
tabs switch between Barracks / Stable / Range; on each: its quantity (jobs.toml [troops_training.quantity]) -> Train. A tab that is still
training shows "Speedups" instead of Train and is left alone.
!! Never Finish (gems) or Speedups.
"""

from __future__ import annotations

import re
import time
from datetime import timedelta
from typing import TYPE_CHECKING

from core import switches, vision
from core.phone import ElementNotFound
from core.task import job
from core.timeparse import parse_duration
from regions import (
    TRAIN_BUTTON,
    TRAIN_LABEL,
    TRAIN_QTY,
    TRAIN_QTY_FIELD,
    TRAIN_TABS,
    TRAIN_TIMER,
    TRAIN_TITLE,
    TRAIN_XI,
)
from town import drag, find_building, go_to_building

if TYPE_CHECKING:
    from logging import Logger

    from core.phone import Phone
    from game import Kingshot

NO_TIMER_WAIT = timedelta(hours=1)  # no countdown read at all: look again this soon
TROOP_KIND = {"Barracks": "Infantry", "Stable": "Cavalry", "Range": "Archers"}
TROOP_TITLE = re.compile(r"Apex|Truegold")  # training page title: "Apex Infantry", "Truegold Archers", ...
TROOPS_QUANTITY = {  # defaults; jobs.toml [troops_training.quantity] overrides them
    "Barracks": 950,
    "Stable": 950,
    "Range": 820,
}
QTY_BOX = (810, 1892)  # the quantity box


@job(priority=90)  # when the slowest of the three trainings is done (the job returns it)
def troops_training(app: Kingshot, phone: Phone, log: Logger):
    x, y = go_to_building(
        phone,
        log,
        "Barracks",
        view=app.town_from_launch(phone, log),
        unblock=lambda: app.close_popups(phone, log, timeout=5),
    )  # e.g. a late "Welcome back!"
    if abs(x - 540) > 100:  # its tap menu reaches ~300 px right: centre it first
        drag(phone, x - 540, 0)
        m = find_building(phone, "Barracks")
        if not m:
            raise ElementNotFound("lost the Barracks after centring it")
        x, y = m.center
    app.town_view = None
    open_training(phone, x, y)
    log.info("training page open")

    waits = []
    for tab, xy in TRAIN_TABS.items():
        quantity = quantity_for(tab)
        phone.tap_xy(*xy)
        phone.wait_for(text=TROOP_TITLE, region=TRAIN_TITLE, timeout=10)
        time.sleep(1.5)  # the page settles (it can show "Train" for a moment)
        phone.forget_screen()
        if phone.exists(text="Training", region=TRAIN_TIMER):
            log.info("%s: still training", tab)
        elif phone.exists(text="Train", region=TRAIN_BUTTON):
            tier = pick_xi(phone)  # the top tier when it's unlocked (in colour), else the page's own choice
            title = phone.read_text(TRAIN_TITLE)  # over the 3D troop: only its tier word reads reliably
            troop = f"{'Truegold' if 'Truegold' in title else 'Apex'} {TROOP_KIND[tab]}"
            set_quantity(phone, quantity)
            phone.tap(text="Train", region=TRAIN_BUTTON, timeout=5)
            time.sleep(1.5)
            log.info("%s: training %d %s%s", tab, quantity, troop, " (XI)" if tier else "")
        else:
            raise RuntimeError(f"{tab}: neither Training nor a Train button; not touching it")
        wait = training_left(phone)
        if wait:
            waits.append(wait)
    phone.back()  # training page -> town
    if not waits:
        log.info("no training countdown read; looking again in %s", NO_TIMER_WAIT)
        return NO_TIMER_WAIT
    log.info("training left: %s; the slowest is done in %s", ", ".join(str(w) for w in waits), max(waits))
    return max(waits) + timedelta(minutes=1)


def training_left(phone: Phone, tries: int = 6) -> timedelta | None:
    """This building's training countdown ("Training  10:36:26"), once two readings agree (within 5 s)."""
    last = None
    for _ in range(tries):
        phone.forget_screen()
        now = parse_duration(phone.read_text(TRAIN_TIMER))
        if now and last and abs((now - last).total_seconds()) <= 5:
            return now
        last = now
        time.sleep(0.7)
    return None


def pick_xi(phone: Phone) -> bool:
    """Select tier XI when it isn't greyed out (locked: a grey stone portrait, ~10-20 % coloured; unlocked ~66 %).
    True if XI is selected now."""
    img = phone.screen()
    if vision.coloured_share(img, TRAIN_XI) < 0.4:
        return False
    x1, y1, x2, y2 = TRAIN_XI
    phone.tap_xy((x1 + x2) // 2, (y1 + y2) // 2)
    phone.wait_for(text="Truegold", region=TRAIN_TITLE, timeout=5)  # the page now shows the XI troop
    time.sleep(1)
    phone.forget_screen()
    return True


def quantity_for(tab: str) -> int:
    """Troops per training for this building: jobs.toml [troops_training.quantity], else TROOPS_QUANTITY."""
    value = switches.settings("troops_training", "quantity").get(tab, TROOPS_QUANTITY[tab])
    try:
        return int(value)
    except (TypeError, ValueError):
        return TROOPS_QUANTITY[tab]


def open_training(phone: Phone, x: int, y: int) -> None:
    """Tap the building until its menu shows (the first tap may only collect troops), then the menu's Train."""
    for _ in range(5):  # finished troops are collected by the first tap(s); the menu can take a moment
        phone.tap_xy(x, y)
        try:
            m = phone.wait_for(text="Train", region=TRAIN_LABEL, timeout=4)
            break
        except ElementNotFound:
            continue
    else:
        raise ElementNotFound("the Barracks menu (Details / Upgrade / Train) didn't show")
    phone.tap_xy(m.center[0], m.center[1] - 88)  # the hexagon icon above its label
    phone.wait_for(text=TROOP_TITLE, region=TRAIN_TITLE, timeout=10)


def set_quantity(phone: Phone, quantity: int) -> None:
    phone.tap_xy(*QTY_BOX)
    phone.wait_for(text="OK", region=TRAIN_QTY_FIELD, timeout=3)  # !! else OK's spot is the Speedups button
    phone.key("KEYCODE_MOVE_END")
    for _ in range(6):
        phone.key("KEYCODE_DEL")
    phone.type_text(str(quantity))
    phone.tap(text="OK", region=TRAIN_QTY_FIELD, timeout=3)
    time.sleep(1)
    phone.forget_screen()
    read = phone.read_text(TRAIN_QTY).replace(",", "")
    if str(quantity) not in read:
        raise RuntimeError(f"quantity reads {read!r}, not {quantity}; not training")
