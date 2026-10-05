"""Kingshot job: intel mission. 00:30 + 11:30 UTC (6am + 5pm IST), last job of those sessions.

World map -> compass -> Intel Mission. A finished pin (green tick) is tapped to claim its reward (it disappears);
every open pin is done (new missions can appear, so it goes round until none are left):
    tent           View -> Rescue
    crossed swords View -> Conquer -> Squad Settings: Fight -> battle Rewards: tap to exit
    bear / lion    View -> Attack -> Deploy: squad preset M1 -> Deploy -> wait 2.2 x the march time
    boss (orange hexagon): never.
Pins are told apart by their white icon (templates/intel_pin_*.png), whatever the pin's colour.
Starts on the city screen or world map; after_job backs out to where it started.
"""
import re
import time

import cv2
import numpy as np

from core.phone import ElementNotFound
from core.schedule import At
from core.task import job
from core.timeparse import parse_duration
from core.vision import crop, load_template, median_hue
from regions import (
    COMPASS_BUTTON,
    DEPLOY_BUTTON,
    DEPLOY_PRESETS,
    DEPLOY_TIME,
    INTEL_ACTION,
    INTEL_MAP,
    INTEL_MEAT,
    INTEL_REFRESH,
    INTEL_VIEW,
    NAV_REGION,
    POPUP_EXIT,
    SCREEN_TITLE,
)

PIN_KINDS = ("tent", "swords", "bear", "lion")
ACTIONS = {"tent": "Rescue", "swords": "Conquer", "bear": "Attack", "lion": "Attack"}
BUTTON_HUES = {"tent": (40, 75), "swords": (80, 100), "bear": (5, 22), "lion": (5, 22)}
MIN_MEAT = 20            # stop below this (a mission costs 8-12): never reach a "buy stamina" prompt
MAX_MISSIONS = 25        # per run, so it can never loop
BLANK = (540, 300)       # dim area above pop-ups
DEPLOY_TAP = (822, 2210)  # centre of the Deploy button


@job(schedule=At("00:30", "11:30", tz="UTC"), priority=110, timeout=1200)   # 6am + 5pm IST, last
def intel_mission(app, phone, log):
    if phone.exists(text="World", region=NAV_REGION):            # on the town: the button names the world map
        phone.tap(text="World", region=NAV_REGION)
        phone.wait_for(text="Town", region=NAV_REGION, timeout=15)
    open_intel(app, phone, log)
    done = claims = 0
    skipped = set()
    for _ in range(MAX_MISSIONS * 2):
        open_now, finished = pins(phone.screen())
        finished = [p for p in finished if (p[1] // 40, p[2] // 40) not in skipped]
        if finished:                                     # tap a ticked pin: its reward is claimed, it disappears
            kind, x, y = finished[0]
            phone.tap_xy(x, y)
            time.sleep(1.5)
            tap_to_exit(phone, wait=1.5)                 # a reward pop-up, if one shows
            phone.forget_screen()
            if any(abs(px - x) < 30 and abs(py - y) < 30 for _, px, py in pins(phone.screen())[1]):
                skipped.add((x // 40, y // 40))          # still there: don't keep tapping it
            else:
                claims += 1
            continue
        meat = read_meat(phone)
        if meat is not None and meat < MIN_MEAT:
            log.info("intel: only %d meat left; stopping", meat)
            break
        pin = next((p for p in open_now if (p[1] // 40, p[2] // 40) not in skipped), None)
        if pin is None or done >= MAX_MISSIONS:
            break
        kind, x, y = pin
        if do_mission(phone, log, kind, x, y):
            done += 1
        else:
            skipped.add((x // 40, y // 40))
        open_intel(app, phone, log)
    log.info("intel: %d mission(s) done, %d reward(s) claimed", done, claims)
    phone.back()                                         # Intel Mission -> world map


def open_intel(app, phone, log):
    app.tap_on_main(phone, log, image="compass_button", region=COMPASS_BUTTON)
    phone.wait_for(text="Refreshes In", region=INTEL_REFRESH, timeout=20)   # the mission map takes a while to load
    time.sleep(1)
    phone.forget_screen()


def read_meat(phone):
    digits = re.sub(r"\D", "", phone.read_text(INTEL_MEAT))
    return int(digits) if digits else None


def pins(img):
    """([(kind, x, y)] open pins, [(kind, x, y)] finished pins with a green tick), top to bottom.
    Boss pins aren't matched."""
    part, (ox, oy) = crop(img, INTEL_MAP)
    hsv = cv2.cvtColor(part, cv2.COLOR_BGR2HSV)
    white = (((hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 225)) * 255).astype(np.float32)
    found, finished = [], []
    for kind in PIN_KINDS:
        tpl = cv2.cvtColor(load_template(f"intel_pin_{kind}")[0], cv2.COLOR_BGR2GRAY).astype(np.float32)
        res = cv2.matchTemplate(white, tpl, cv2.TM_CCOEFF_NORMED)
        th, tw = tpl.shape
        while True:
            _, score, _, (mx, my) = cv2.minMaxLoc(res)
            if score < 0.7:                              # other kinds score <= 0.55, a half-hidden pin ~0.8
                break
            res[max(0, my - th):my + th, max(0, mx - tw):mx + tw] = -1
            x, y = ox + mx + tw // 2, oy + my + th // 2
            (finished if ticked(img, x, y) else found).append((kind, x, y))
    return sorted(found, key=lambda p: p[2]), sorted(finished, key=lambda p: p[2])


def ticked(img, x, y):
    """A finished pin has a green tick at its head's top right."""
    hsv = cv2.cvtColor(img[max(0, y - 55):y - 5, x + 10:x + 60], cv2.COLOR_BGR2HSV)
    return ((hsv[:, :, 0] >= 45) & (hsv[:, :, 0] <= 85) & (hsv[:, :, 1] > 120) & (hsv[:, :, 2] > 150)).sum() > 80


def do_mission(phone, log, kind, x, y):
    """One mission from its pin. Returns False if it couldn't be started (then the pin is skipped)."""
    phone.tap_xy(x, y)
    try:
        phone.tap(text="View", region=INTEL_VIEW, timeout=5)
        button = None
        for _ in range(10):                              # the map glides to the target, then the box opens
            time.sleep(0.8)
            phone.forget_screen()
            button = action_button(phone.screen(INTEL_ACTION), kind)
            if button:
                break
        if not button:
            raise ElementNotFound(ACTIONS[kind])
        phone.tap_xy(*button)
    except ElementNotFound:
        log.info("intel: %s at (%d, %d): no View / %s button; skipping it", kind, x, y, ACTIONS[kind])
        back_to_world(phone)
        return False
    if kind == "swords":
        phone.wait_for(text="Squad Settings", region=SCREEN_TITLE, timeout=10)
        phone.tap(text="Fight", region=(0.5, 0.9, 0.98, 0.99), timeout=10)
        phone.wait_for(text="Tap anywhere", region=POPUP_EXIT, timeout=120)
        tap_to_exit(phone)
    elif kind in ("bear", "lion"):
        phone.wait_for(text="Deploy", region=SCREEN_TITLE, timeout=10)
        phone.tap(image="deploy_m1", region=DEPLOY_PRESETS, timeout=5)
        time.sleep(1)
        phone.forget_screen()
        march = parse_duration(phone.read_text(DEPLOY_TIME))
        hue = median_hue(phone.screen(DEPLOY_BUTTON), DEPLOY_BUTTON)   # its white lettering doesn't OCR
        if not 75 <= hue <= 105:
            raise RuntimeError(f"Deploy button isn't teal (hue {hue:.0f}); not tapping")
        phone.tap_xy(*DEPLOY_TAP)
        wait = 2.2 * march.total_seconds() if march else 30
        log.info("intel: %s attacked; waiting %.0f s (2.2 x march %s)", kind, wait, march)
        time.sleep(wait)
    else:
        time.sleep(2)
    log.info("intel: %s mission done", kind)
    back_to_world(phone)
    return True


def action_button(img, kind):
    """Centre of the mission box's button, found by its colour (its white lettering doesn't always OCR):
    green Rescue (tent), teal Conquer (swords), orange Attack (bear / lion). None if it isn't there."""
    lo, hi = BUTTON_HUES[kind]
    part, (ox, oy) = crop(img, INTEL_ACTION)
    hsv = cv2.cvtColor(part, cv2.COLOR_BGR2HSV)
    mask = (hsv[:, :, 0] >= lo) & (hsv[:, :, 0] <= hi) & (hsv[:, :, 1] > 120) & (hsv[:, :, 2] > 175)   # brighter than grass
    if mask.sum() < 15000:                               # the button is ~300 x 90 px
        return None
    ys, xs = np.nonzero(mask)
    return ox + int(np.median(xs)), oy + int(np.median(ys))


def tap_to_exit(phone, wait=0):
    """Reward pop-up: tap the dim area until "Tap anywhere to exit" is gone (taps during the animation are lost)."""
    if wait and not phone.exists(text="Tap anywhere", region=POPUP_EXIT, timeout=wait):
        return
    for _ in range(6):
        phone.tap_xy(*BLANK)
        if not phone.exists(text="Tap anywhere", region=POPUP_EXIT, timeout=1.5):
            return


def back_to_world(phone):
    """Back to the world map (bottom menu says "Town"), whatever is open."""
    for _ in range(4):
        if phone.exists(text="Backpack", region=NAV_REGION, timeout=2):
            return
        phone.back()
