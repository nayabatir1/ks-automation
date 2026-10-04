"""Kingshot job: arena. Daily at 23:53 UTC.

Starts on the city screen or world map (bottom menu visible, no pop-up) — game.py's on_open/before_job
open the game and close all pop-ups first.
"""
import re

import cv2
import numpy as np
import pytesseract

from core import vision
from core.schedule import At
from core.task import job
from regions import (
    ARENA_CHALLENGE,
    ARENA_MY_ROW,
    DAILY_CHALLENGES,
    FREE_REFRESH,
    NAV_REGION,
)
from town import go_to_building


@job(schedule=At("23:53", tz="UTC"))
def arena(app, phone, log):
    # 1. town view (if the world map is showing, its bottom-right button says "Town")
    view = app.town_view                         # (0, 0) right after a fresh launch: no need to look first
    if phone.exists(text="Town", region=NAV_REGION):
        phone.tap(text="Town", region=NAV_REGION)
        phone.wait_for(text="World", region=NAV_REGION, timeout=15)
        view = None

    # 2. find the Arena by the building names and tap it
    x, y = go_to_building(phone, log, "Arena", view=view)
    app.town_view = None
    phone.tap_xy(x, y)
    log.info("tapped the Arena at (%d, %d)", x, y)

    # 3. your standing: the row above Challenge reads "433  [W4R]name  18.8M  1,175"
    phone.wait_for(text="Arena of Glory", region=(0, 0.03, 0.7, 0.1), timeout=10)
    rank, points = my_standing(phone)
    log.info("arena: rank #%s, %s points", rank, points)

    # 4. Challenge (bottom centre)
    phone.tap(text="Challenge", region=ARENA_CHALLENGE, timeout=10)
    phone.wait_for(text="Challenge List", region=LIST_TITLE, timeout=10)
    log.info("challenge list open")
    # !! "+" next to "Daily challenges: N" probably buys attempts (gems): never tap it.

    # 5. attack until the daily attempts are used: the lowest-powered opponent weaker than me (power in green);
    #    none -> Free Refresh (only if it's free). Each fight: Fight -> pause -> Retreat (ends it at once, as a
    #    loss: the user's choice) -> tap anywhere to exit -> back to the Challenge List.
    #    !! Out of attempts the game offers more for gems: we stop at 0 and never tap "+" or anything with gems.
    attack_all(phone, log)

    # 6. leave the arena (Challenge List -> Arena -> town) so the next job can start straight away
    phone.back(2)
    if phone.exists(text="Backpack", region=NAV_REGION, timeout=6):
        log.info("back in town")


def attack_all(phone, log):
    """Fight until the daily attempts are used (see step 5 in arena())."""
    refreshes = 0
    for _ in range(MAX_FIGHTS):
        open_challenge_list(phone)
        left = attempts_left(phone)
        log.info("daily challenges left: %s", left)
        if not left:
            log.info("no attempts left; done for today")
            return
        y = weakest_opponent(phone, log)
        if y is None:
            if refreshes >= MAX_REFRESHES or not free_refresh(phone, log):
                log.info("no weaker opponent and no free refresh; done for now")
                return
            refreshes += 1
            continue
        fight(phone, log, y)
    log.info("stopped after %d fights (safety limit)", MAX_FIGHTS)


MAX_FIGHTS = 10            # safety limit per run (daily attempts are usually 4)
MAX_REFRESHES = 3          # per run, so a refresh can never loop
LIST_TITLE = (0.1, 0.2, 0.9, 0.27)         # "Challenge List" box title
FIGHT_BUTTON = (0.5, 0.9, 0.98, 0.99)      # Squad Settings: green "Fight" (bottom right; "Quick Deploy" is left)
PAUSE_AREA = (0, 0.7, 0.4, 0.88)           # battle: pause button, bottom left (templates/battle_pause.png)
RETREAT_AREA = (0.15, 0.53, 0.5, 0.63)     # paused: "Retreat" (left) / "Continue" (right)
POWER_X = (285, 430)       # the power figure beside the fist icon: green = lower than mine, red = higher
SWORDS_X = (880, 990)      # the teal swords button at the right of each row


def attempts_left(phone):
    """N from "Daily challenges: N" (above Free Refresh)."""
    for m in vision.ocr_lines(phone.screen(DAILY_CHALLENGES), DAILY_CHALLENGES):
        n = re.search(r"challenges\W*(\d+)", m.text, re.IGNORECASE)
        if n:
            return int(n.group(1))
    raise RuntimeError("could not read 'Daily challenges: N'")


def opponents(phone):
    """[(y, green, power_digits)] for the rows in the Challenge List, top to bottom. green = power lower than mine.
    power_digits: the power beside the fist as whole digits (15.9M -> 159; all rows use the same format), or None."""
    img = phone.screen((0, 0.28, 1, 0.74))
    x1, x2, y1, y2 = POWER_X[0], POWER_X[1], 700, 1720
    hsv = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    coloured = (hsv[:, :, 1] > 120) & (hsv[:, :, 2] > 80)
    rows, start = [], None
    for i, on in enumerate([*list(coloured.sum(axis=1) > 3), False]):     # bands of coloured digits = rows
        if on and start is None:
            start = i
        if not on and start is not None:
            if i - start > 15:
                hue = float(np.median(hsv[start:i, :, 0][coloured[start:i]]))
                y = y1 + (start + i) // 2
                green = 35 <= hue <= 85
                rows.append((y, green, power_digits(img, y) if green else None))
            start = None
    return rows


def power_digits(img, y):
    """Coloured power figure as whole digits; reads it two ways and keeps the longest (OCR tends to drop a digit)."""
    part = img[y - 30:y + 30, POWER_X[0] - 10:POWER_X[1] + 10]
    sat = cv2.cvtColor(part, cv2.COLOR_BGR2HSV)[:, :, 1]
    reads = []
    for mask in (sat > 120, sat > cv2.threshold(sat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[0]):
        big = cv2.resize(mask.astype(np.uint8) * 255, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
        big = cv2.copyMakeBorder(255 - big, 30, 30, 60, 30, cv2.BORDER_CONSTANT, value=255)
        for psm in (7, 8):
            text = pytesseract.image_to_string(big, config=f"--psm {psm} -c tessedit_char_whitelist=0123456789.M")
            reads.append(re.sub(r"\D", "", text))
    best = max(reads, key=len)
    return int(best) if best else None


def weakest_opponent(phone, log):
    """y of the lowest-powered green (weaker than me) opponent, or None if there isn't one."""
    rows = opponents(phone)
    log.info("opponents: %s", ", ".join(f"{'green' if g else 'red'} {p if p is not None else '?'}" for _, g, p in rows))
    greens = [(p if p is not None else 10**9, y) for y, g, p in rows if g]       # unreadable power: last choice
    return min(greens)[1] if greens else None


def open_challenge_list(phone):
    """Be on the Challenge List: after a fight we may land on the Arena screen instead."""
    if phone.exists(text="Challenge List", region=LIST_TITLE, timeout=2):
        return
    phone.tap(text="Challenge", region=ARENA_CHALLENGE, timeout=10)
    phone.wait_for(text="Challenge List", region=LIST_TITLE, timeout=10)


def fight(phone, log, y):
    """Swords -> Squad Settings -> Fight -> pause -> Retreat -> result -> tap anywhere to exit."""
    tap_swords(phone, y)
    phone.tap(text="Fight", region=FIGHT_BUTTON, timeout=15)          # Squad Settings: green Fight, bottom right
    pause_and_retreat(phone)
    result = phone.wait_for(text="Tap anywhere", region=(0.15, 0.93, 0.85, 0.99), timeout=15)
    outcome = phone.find(text=re.compile(r"Failed|Victory|Win", re.IGNORECASE), region=(0.1, 0.24, 0.9, 0.32), reuse=True)
    log.info("fight over: %s", outcome.text if outcome else "result shown")
    phone.tap_xy(*result.center)                                     # "Tap anywhere to exit"
    phone.wait_gone(text="Tap anywhere", region=(0.15, 0.93, 0.85, 0.99), timeout=10)


def pause_and_retreat(phone):
    """Battle: pause (bottom left), then Retreat. A pause tap right as the fight starts is ignored, so tap pause
    again until the Retreat / Continue menu shows."""
    phone.wait_for(image="battle_pause", region=PAUSE_AREA, timeout=20)
    for _ in range(8):
        phone.tap(image="battle_pause", region=PAUSE_AREA, timeout=5, pause=0.2)
        if phone.exists(text="Retreat", region=RETREAT_AREA, timeout=1.5):
            phone.tap(text="Retreat", region=RETREAT_AREA, timeout=3)
            return
    raise RuntimeError("the battle didn't pause (no Retreat / Continue menu)")


def tap_swords(phone, y):
    """Tap the swords button of the row at y, after checking it really is the teal button."""
    box = (SWORDS_X[0], y - 45, SWORDS_X[1], y + 45)
    hue = vision.median_hue(phone.screen((0, 0.3, 1, 0.72)), box)
    if not 75 <= hue <= 105:
        raise RuntimeError(f"swords button at y={y} isn't teal (hue {hue:.0f}); not tapping")
    phone.tap_xy((SWORDS_X[0] + SWORDS_X[1]) // 2, y)


def free_refresh(phone, log):
    """Tap Free Refresh only if it says "Free" and is green. Returns True if refreshed."""
    m = phone.find(text="Free", region=FREE_REFRESH)
    if not m:
        log.info("refresh button doesn't say Free (probably costs gems): not tapping")
        return False
    img = phone.last_screen
    box = (m.x - 60, m.y - 20, m.x + m.w + 220, m.y + m.h + 20)
    if not 35 <= vision.median_hue(img, box) <= 85:
        log.info("refresh button isn't green: not tapping")
        return False
    phone.tap_xy(*m.center, pause=1.5)
    log.info("used Free Refresh")
    return True


def my_standing(phone):
    """(rank, points) from your own row: the left-most number is the rank, the right-most the Arena Points."""
    nums = []
    for m in vision.ocr_lines(phone.screen(ARENA_MY_ROW), ARENA_MY_ROW):
        for word in m.text.split():
            if re.fullmatch(r"\d[\d,]*", word):
                nums.append((m.center[0], int(word.replace(",", ""))))
    nums.sort()
    if len(nums) < 2:
        raise RuntimeError(f"could not read the arena rank and points (read {nums})")
    return nums[0][1], nums[-1][1]
