"""Kingshot job: arena. Daily at 23:53 UTC. Parts: pan_extra_intel_mission, then arena.
Test one part: run.py --job arena --part pan_extra_intel_mission

Starts on the city screen or world map (bottom menu visible, no pop-up) — game.py's on_open/before_job
open the game and close all pop-ups first; after_job backs out to where it started.
"""
import re
import time

import cv2
import numpy as np
import pytesseract

from core import vision
from core.schedule import At
from core.task import job, run_parts
from regions import (
    ARENA_CHALLENGE,
    ARENA_MY_ROW,
    COMPASS_BUTTON,
    DAILY_CHALLENGES,
    FREE_REFRESH,
    INTEL_HERO,
    INTEL_REFRESH,
    NAV_REGION,
)
from town import go_to_building


@job(schedule=At("23:53", tz="UTC"))
def arena(app, phone, log):
    run_parts(app, phone, log, {"pan_extra_intel_mission": pan_extra_intel_mission, "arena": fight_arena})


def pan_extra_intel_mission(app, phone, log):
    """World map -> compass button (Q4, right) -> Intel Mission: tap the hero portrait (top left) when it's there,
    which brings new missions. Then close Intel Mission and go to the town view."""
    if phone.exists(text="World", region=NAV_REGION):            # on the town: the button names the world map
        phone.tap(text="World", region=NAV_REGION)
        phone.wait_for(text="Town", region=NAV_REGION, timeout=15)
    app.tap_on_main(phone, log, image="compass_button", region=COMPASS_BUTTON)
    phone.wait_for(text="Refreshes In", region=INTEL_REFRESH, timeout=20)   # the mission map takes a while to load
    log.info("intel mission open")
    if phone.exists(image="intel_hero", region=INTEL_HERO):
        phone.tap(image="intel_hero", region=INTEL_HERO)
        log.info("intel mission: tapped the hero")
        time.sleep(1.5)
    else:
        log.info("intel mission: no hero to tap")
    phone.back()
    phone.wait_for(text="Town", region=NAV_REGION, timeout=10)
    phone.tap(text="Town", region=NAV_REGION)
    phone.wait_for(text="World", region=NAV_REGION, timeout=15)   # the town is shown where it was left


def fight_arena(app, phone, log):
    # 1. town view with a known position (relaunches the game if needed)
    view = app.town_from_launch(phone, log)

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
    #    none -> Free Refresh (only if it's free); refreshes used up -> the lowest-powered red one. Each fight: Fight -> pause -> Retreat (ends it at once, as a
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
            if refreshes < MAX_REFRESHES and free_refresh(phone, log):
                refreshes += 1
                continue
            y = weakest_opponent(phone, log, red=True)             # refreshes used up: the weakest stronger one
            if y is None:
                log.info("no opponent found; done for now")
                return
            log.info("no green opponent and no free refresh: attacking the lowest red")
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
    return read_opponents(phone.screen((0, 0.28, 1, 0.74)))


def read_opponents(img):
    """[(y, green, power)] for the rows in the Challenge List, top to bottom. green = power lower than mine (the
    game's own colour). power: the real value (15.9M -> 15,900,000; 166,500 -> 166,500), or None if unreadable."""
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
                rows.append((y, green, power_value(img, y)))
            start = None
    return rows


def power_value(img, y):
    """The coloured power figure beside the fist, as a real number. Two formats: "15.9M" (1M and up, always one
    decimal) and "166,500" (under 1M, full number). OCR loses the dot and commas, so: digits read + whether there's
    an M. A reading of 1-3 digits can only be the M format (full numbers have 4+ digits)."""
    part = img[y - 30:y + 30, POWER_X[0] - 10:POWER_X[1] + 10]
    hsv = cv2.cvtColor(part, cv2.COLOR_BGR2HSV)
    sat, val = hsv[:, :, 1], hsv[:, :, 2]
    reads = []
    for mask in ((sat > 100) & (val > 150),             # bright fill only, no dark outline: the most exact, so first
                 sat > 120, sat > cv2.threshold(sat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[0]):
        big = cv2.resize(mask.astype(np.uint8) * 255, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
        big = cv2.copyMakeBorder(255 - big, 30, 30, 60, 30, cv2.BORDER_CONSTANT, value=255)
        for psm in (7, 8):
            reads.append(pytesseract.image_to_string(
                big, config=f"--psm {psm} -c tessedit_char_whitelist=0123456789.,M").strip())
    digits = max((re.sub(r"\D", "", r) for r in reads), key=len)    # longest (first on a tie): OCR drops digits
    if not digits:
        return None
    if any("M" in r for r in reads) or len(digits) <= 3:
        return int(digits) * 100_000                                 # 159 -> 15.9M
    return int(digits)


def weakest_opponent(phone, log, red=False):
    """y of the lowest-powered green (weaker than me) opponent, or None if there isn't one.
    red=True: the lowest-powered red one instead (used only once the free refreshes are gone)."""
    rows = opponents(phone)
    log.info("opponents: %s", ", ".join(f"{'green' if g else 'red'} {p:,}" if p else f"{'green' if g else 'red'} ?"
                                        for _, g, p in rows))
    pick = [(p if p is not None else 10**12, y) for y, g, p in rows if g != red]   # unreadable power: last choice
    return min(pick)[1] if pick else None


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
    return read_standing(phone.screen(ARENA_MY_ROW))


def read_standing(img):
    """(rank, points) from your own row: the rank is the number at the far left (None when it says "Unranked"),
    the points the right-most number. Name and power in between are ignored."""
    nums = []
    for m in vision.ocr_lines(img, ARENA_MY_ROW):
        for word in m.text.split():
            if re.fullmatch(r"\d[\d,]*", word):
                nums.append((m.center[0], int(word.replace(",", ""))))
    nums.sort()
    if not nums:
        raise RuntimeError("could not read the arena points")
    rank = nums[0][1] if nums[0][0] < img.shape[1] * 0.2 else None      # left edge only ("Unranked" = None)
    return rank, nums[-1][1]
