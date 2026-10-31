"""Kingshot job: troops training. Runs again when the slowest of the three trainings is done.

World map -> side panel -> Town tab (preselected) -> Troops Training: Infantry's green arrow -> the town, centred
on the Barracks with its menu open -> "Train" (always at the same spot) -> training page. Its bottom
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
from core.task import job
from core.timeparse import parse_duration
from jobs.online_rewards import ROW_BUTTON_X, open_side_panel
from regions import (
    BARRACKS_NAME,
    SIDE_PANEL,
    SIDE_PANEL_TOWN_TAB,
    TRAIN_BUTTON,
    TRAIN_QTY,
    TRAIN_QTY_FIELD,
    TRAIN_TABS,
    TRAIN_TIMER,
    TRAIN_TITLE,
    TRAIN_XI,
)

if TYPE_CHECKING:
    from logging import Logger

    from core.phone import Phone
    from game import Kingshot

NO_TIMER_WAIT = timedelta(hours=1)  # no countdown read at all: look again this soon
TROOP_KIND = {"Barracks": "Infantry", "Stable": "Cavalry", "Range": "Archers"}
# training page title: "Apex Infantry", "Truegold Archers", ... (the helmet over the "d" can hide it: "Truegol")
TROOP_TITLE = re.compile(r"Apex|Truegol")
TROOPS_QUANTITY = {  # defaults; jobs.toml [troops_training.quantity] overrides them
    "Barracks": 950,
    "Stable": 950,
    "Range": 820,
}
QTY_BOX = (810, 1892)  # the quantity box
MENU_TRAIN = (722, 1316)  # the Barracks menu's Train, with the Barracks centred by the side panel's arrow


@job(priority=90)  # when the slowest of the three trainings is done (the job returns it)
def troops_training(app: Kingshot, phone: Phone, log: Logger):
    open_training(app, phone, log)
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
            troop = f"{'Truegold' if 'Truegol' in title else 'Apex'} {TROOP_KIND[tab]}"
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
    phone.wait_for(text="Truegol", region=TRAIN_TITLE, timeout=5)  # the page now shows the XI troop
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


def open_training(app: Kingshot, phone: Phone, log: Logger) -> None:
    """World map -> side panel -> Town tab -> Infantry's green arrow -> Barracks menu -> Train -> training page."""
    open_side_panel(app, phone, log)
    if not phone.exists(text="Troops Training", region=SIDE_PANEL, timeout=2):  # the Town tab is preselected
        phone.tap_xy(*SIDE_PANEL_TOWN_TAB)
        phone.wait_for(text="Troops Training", region=SIDE_PANEL, timeout=5)
    m = phone.wait_for(text="Infantry", region=SIDE_PANEL, timeout=5)
    phone.tap_xy(ROW_BUTTON_X, m.center[1] + 20)  # the row's green arrow (right end)
    app.town_view = None  # the town is now centred on the Barracks
    phone.wait_for(text="Barracks", region=BARRACKS_NAME, timeout=10)
    time.sleep(1)  # the menu pops up after the name
    phone.tap_xy(*MENU_TRAIN)  # highlighted (a hand points at it): neither its icon nor its label read reliably
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
