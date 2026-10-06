"""Kingshot job: farming. Every 7.5 h.

World map -> magnifying glass (bottom left) -> search panel; for Bread, Wood, Stone and Iron: pick it in the row,
check "Lv.8" and the "Only search for full Resources" tick -> Search -> Gather -> remove heroes 3 and 2 -> Deploy.
"Other Troops are marching toward the same target" -> Cancel, search again. Troops aren't waited for.
Starts on the city screen or world map; after_job backs out to where it started.
"""
import re
import time
from datetime import timedelta

import cv2
import pytesseract

from core import vision
from core.phone import ElementNotFound
from core.task import job
from regions import (
    DEPLOY_BUTTON,
    HERO_MINUS,
    NAV_REGION,
    SAME_TARGET_CANCEL,
    SCREEN_TITLE,
    SEARCH_BUTTON,
    SEARCH_GO,
    SEARCH_LEVEL_BOX,
    SEARCH_LEVEL_LABEL,
    SEARCH_ROW,
    SEARCH_TICK,
    TILE_GATHER,
)

RESOURCES = ("Bread", "Wood", "Stone", "Iron")
LEVEL = 8                                       # 8 is the slider's top, so "Lv.8" always shows in one spot
FIELD_OK = (942, 2125)                          # OK of the text field the number box opens
SEARCH_PANEL_GO = (0.2, 0.9, 0.8, 0.99)          # the search panel's "Search" button (the panel is open)
DEPLOY_TAP = (822, 2240)


@job(timeout=600)   # every 7.5 h (the job returns it); a few re-searches fit in 10 min
def farming(app, phone, log):
    if phone.exists(text="World", region=NAV_REGION):            # on the town: the button names the world map
        phone.tap(text="World", region=NAV_REGION)
        phone.wait_for(text="Town", region=NAV_REGION, timeout=15)
    app.tap_on_main(phone, log, image="search_button", region=SEARCH_BUTTON,
                    then={"text": "Search", "region": (0.2, 0.9, 0.8, 0.99)})
    phone.wait_for(text="Search", region=(0.2, 0.9, 0.8, 0.99), timeout=10)
    log.info("search panel open")
    for kind in RESOURCES:
        gather(phone, log, kind)
    return timedelta(hours=7, minutes=30)


def gather(phone, log, kind, tries=3):
    """One march to a Lv.8 tile of this resource. Starts and ends on the world map."""
    for attempt in range(tries):
        if not phone.exists(text="Search", region=SEARCH_PANEL_GO, timeout=1):
            phone.tap(image="search_button", region=SEARCH_BUTTON, timeout=10)
            phone.wait_for(text="Search", region=SEARCH_PANEL_GO, timeout=10)
        m = phone.find(text=kind, region=SEARCH_ROW)
        if not m:
            swipe_row_to_end(phone)                      # Bread / Wood / Stone / Iron are at the row's right end
            m = phone.find(text=kind, region=SEARCH_ROW)
        if not m:
            raise ElementNotFound(f"{kind} isn't in the search row")
        phone.tap_xy(m.center[0], m.center[1] - 60)      # the tile picture above its name
        time.sleep(1.2)
        set_level(phone, LEVEL)                          # each resource keeps its own level: always set it
        phone.forget_screen()
        level = level_label(phone.screen())
        if level != LEVEL:
            raise RuntimeError(f"{kind}: the search level reads {level}, not {LEVEL}; not searching")
        if vision.coloured_share(phone.last_screen, SEARCH_TICK) < 0.1:
            raise RuntimeError(f"{kind}: 'Only search for full Resources' isn't ticked; not searching")
        phone.tap_xy(*SEARCH_GO)
        phone.tap(text="Gather", region=TILE_GATHER, timeout=10)
        phone.wait_for(text=kind, region=SCREEN_TITLE, timeout=10)   # formation page, titled by the resource
        for hero in (3, 2):                              # right to left, so the cards can't shift under the taps
            phone.tap_xy(*HERO_MINUS[hero])
            time.sleep(1)
        hue = vision.median_hue(phone.screen(DEPLOY_BUTTON), DEPLOY_BUTTON)
        if not 75 <= hue <= 105:
            raise RuntimeError(f"{kind}: Deploy isn't teal (hue {hue:.0f}); not tapping")
        phone.tap_xy(*DEPLOY_TAP)
        time.sleep(2)
        phone.forget_screen()
        cancel = phone.find(text="Cancel", region=SAME_TARGET_CANCEL)
        if cancel:                                       # someone already marches there: another tile
            log.info("%s: tile already targeted; searching again", kind)
            phone.tap_xy(*cancel.center)
            time.sleep(1.5)
            phone.back()                                 # formation page -> world map
            time.sleep(1.5)
            continue
        log.info("%s: deployed (attempt %d)", kind, attempt + 1)
        return
    log.info("%s: no free tile after %d tries", kind, tries)


def swipe_row_to_end(phone):
    """Swipe the search panel's row of targets left until it stops moving."""
    for _ in range(6):
        phone.forget_screen()
        before = phone.screen(SEARCH_ROW)
        phone.swipe(950, 1785, 150, 1785, ms=400)
        time.sleep(1)
        phone.forget_screen()
        if vision.screen_diff(before, phone.screen(SEARCH_ROW), SEARCH_ROW) < 3:
            return


def set_level(phone, level):
    """Type the level into the search panel's number box (a text field with OK opens)."""
    phone.tap_xy(*SEARCH_LEVEL_BOX)
    time.sleep(1)
    phone.key("KEYCODE_MOVE_END")
    for _ in range(3):
        phone.key("KEYCODE_DEL")
    phone.type_text(str(level))
    phone.tap_xy(*FIELD_OK)
    time.sleep(1)


def level_label(img):
    """The number in the search panel's "Lv.N" label, or None."""
    x1, y1, x2, y2 = SEARCH_LEVEL_LABEL
    gray = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    big = cv2.resize(cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1], None, fx=3, fy=3)
    big = cv2.copyMakeBorder(big, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    text = pytesseract.image_to_string(big, config="--psm 7 -c tessedit_char_whitelist=Lv.0123456789")
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else None
