"""Kingshot job: dailies. Daily at 00:10 UTC.

Starts on the city screen or world map (bottom menu visible, no pop-up) — game.py's on_open/before_job
open the game and close all pop-ups first; after_job backs out to where it started.
The Q1 icons (gems, VIP, Events, Deals, Sign-in, ...) show on both the town and the world map.
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
    DEALS_LABEL,
    FREE_COLUMN,
    GEMS_SHOP,
    MERCHANT_PRICES,
    MERCHANT_REFRESH,
    MERCHANT_TIMER,
    NAV_REGION,
    POPUP_CONTINUE,
    SCREEN_TITLE,
    SHOP_BOTTOM_TABS,
    SHOP_FREE_AREA,
    SHOP_NAV,
    SHOP_TAB_DOTS,
    SHOP_TAB_ROW_Y,
    TAB_NAMES,
    TAB_TITLE,
    TOPUP_TITLE,
    VIP_BADGE,
    VIP_BUNDLE_CLAIM,
    VIP_TITLE,
    VIP_XP_CHEST,
)
from town import LABEL_TO_BUILDING, MAP_AREA, TOWN, go_to_building

TAB_SWIPE = (900, 200)          # x from / to: one swipe shows the next ~2.5 tabs
MAX_TAB_PAGES = 8
BUBBLE_SCALES = (0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0, 1.1)   # bubbles are drawn smaller near the town edge
MAX_MERCHANT_ROUNDS = 300      # buys + refreshes per run, so it can never loop (one stock took ~80 buys)
SEARCH_SWIPE = (800, 450)
PRICE_ROWS = (0, 0.45, 1, 0.67)  # merchant: the rows with the 6 price bars
BLANK_SPOT_PX = (540, 300)      # dim area above reward pop-ups (no buttons behind it take the tap)


@job(schedule=At("00:10", tz="UTC"), timeout=1800)   # the merchant alone can take ~12 min
def dailies(app, phone, log):
    """The parts below, in order; each starts and ends on the city / world map.
    Test one part: run.py --job dailies --part vip   (several: --part gems,deals; all: leave --part out)"""
    run_parts(app, phone, log, PARTS)


def gems(app, phone, log):
    """Gems button (cart + gem count, top right) -> Top-up Center: every tab with a red dot has a free chest.
    !! Real-money shop: never tap a ₹ price or "TOP UP". Only the free chest in each tab's header is tapped."""
    app.tap_on_main(phone, log, image="gems_shop", region=GEMS_SHOP)
    phone.wait_for(text="Top-up Center", region=TOPUP_TITLE, timeout=10)
    log.info("top-up center open")
    claimed = claim_shop_tabs(phone, log)
    log.info("top-up center: %d free chest(s) claimed", claimed)
    back_to_main(phone)


def vip(app, phone, log):
    """VIP (orange V badge; the level number changes) -> VIP screen: the daily sign-in VIP XP chest (red dot) and
    the green Claim of "VIP N Daily Free Bundle". !! The "+" by the XP bar, Shop and the ₹ Special Pack: never."""
    app.tap_on_main(phone, log, image="vip_badge", region=VIP_BADGE)
    phone.wait_for(text="VIP", region=VIP_TITLE, timeout=10)
    log.info("vip screen open")
    dots = vision.red_dots(phone.screen(), VIP_XP_CHEST)
    if dots:
        phone.tap_xy(dots[0][0] - 45, dots[0][1] + 45)  # the dot sits at the chest's top right
        dismiss_popup(phone)
        log.info("vip: daily VIP XP claimed")
    m = phone.find(text="Claim", region=VIP_BUNDLE_CLAIM)
    if m and 35 <= vision.median_hue(phone.last_screen, VIP_BUNDLE_CLAIM) <= 85:
        phone.tap_xy(*m.center)
        dismiss_popup(phone)
        log.info("vip: daily free bundle claimed")
    back_to_main(phone)


def deals(app, phone, log):
    """Deals (gift icon): only two tabs give free things, "Sign-in & Earn It" (a reward per day) and "Hero Rally"
    (rewards unlock as tasks earn points). Claim the glowing items of their Free column.
    !! Never the Epic / Path of Honor column, Unlock, Purchase Level, "+" or any ₹ button."""
    app.tap_on_main(phone, log, text="Deals", region=DEALS_LABEL)
    phone.wait_for(text="Deals", region=SCREEN_TITLE, timeout=10)
    log.info("deals open")
    for tab in ("Earn", "Rall"):                        # "Sign-in & Earn It", "Hero Rally" (OCR-safe parts)
        if open_tab(phone, tab):
            log.info("deals, %s: %d free reward(s) claimed", tab, claim_glowing(phone))
        else:
            log.info("deals: no %r tab", tab)
    back_to_main(phone)


def nomadic_merchant(app, phone, log):
    """Shop (bottom menu) -> Nomadic Merchant: buy every box priced in bread / wood / stone / iron until all 6 are
    priced in gems, then Free Refresh and again, until the refresh isn't free.
    !! Never a box priced in gems, never a refresh that isn't free."""
    app.tap_on_main(phone, log, text="Shop", region=SHOP_NAV)
    phone.tap(text="Nomadic", region=SHOP_BOTTOM_TABS, timeout=10)
    phone.wait_for(text="Refreshes in", region=MERCHANT_TIMER, timeout=10)
    log.info("nomadic merchant open")
    bought = refreshes = 0
    for round_no in range(MAX_MERCHANT_ROUNDS):
        # one screenshot of the price bars, all 6 evaluated; then tap each resource-priced one, but re-check that
        # one bar just before its tap (~0.3 s): a buy restocks and reorders the boxes, so a box can turn into gems
        phone.forget_screen()
        img = phone.screen(PRICE_ROWS)
        boxes = [xy for xy in MERCHANT_PRICES if price_bar(img, xy) and not gem_price(img, xy)]
        if boxes:
            for xy in boxes:
                phone.forget_screen()
                now = phone.screen(bar_region(xy))
                if price_bar(now, xy) and not gem_price(now, xy):
                    phone.tap_xy(*xy)
                    bought += 1
                    time.sleep(0.3)
            if round_no % 5 == 4 and not phone.exists(text="Refreshes in", region=MERCHANT_TIMER, timeout=3):
                log.info("merchant: the merchant screen is gone (not enough resources?); stopping")
                phone.back()
                break
            continue
        if not all(price_bar(img, xy) for xy in MERCHANT_PRICES):
            log.info("merchant: price bars not all visible; stopping")
            break
        m = phone.find(text="Free Refresh", region=MERCHANT_REFRESH)
        if not m or not 35 <= vision.median_hue(phone.last_screen, MERCHANT_REFRESH) <= 85:
            break                                        # all boxes cost gems and the refresh isn't free: done
        phone.tap_xy(*m.center)
        refreshes += 1
        time.sleep(1)
    log.info("merchant: %d box(es) bought, %d free refresh(es)", bought, refreshes)
    back_to_main(phone)


def bar_region(xy):
    """Screen rows of one price bar (for a quick strip screenshot)."""
    return 0, (xy[1] - 32) / 2340, 1, (xy[1] + 32) / 2340


def price_bar(img, xy):
    """Is a merchant price bar really there (cream background)? Guards against tapping when something covers it."""
    x, y = xy
    hsv = cv2.cvtColor(img[y - 30:y + 30, x - 160:x + 160], cv2.COLOR_BGR2HSV)
    cream = ((hsv[:, :, 0] >= 10) & (hsv[:, :, 0] <= 30) & (hsv[:, :, 1] >= 15) & (hsv[:, :, 1] <= 80)
             & (hsv[:, :, 2] > 215))
    return 0.35 <= cream.mean() <= 0.75


def gem_price(img, xy):
    """Is this price bar in gems (a blue diamond before the number)?"""
    x, y = xy
    hsv = cv2.cvtColor(img[y - 30:y + 30, x - 160:x + 160], cv2.COLOR_BGR2HSV)
    blue = (hsv[:, :, 0] >= 95) & (hsv[:, :, 0] <= 115) & (hsv[:, :, 1] > 120) & (hsv[:, :, 2] > 150)
    return blue.sum() > 200


def cassie_recruit(app, phone, log):
    """Town: Stable, Barracks, Range and Enlistment Office can each show a bubble with Cassie's picture; tap every
    one (instant, no pop-up). The first three stand together, so one stop often shows several bubbles."""
    if phone.exists(text="Town", region=NAV_REGION):            # on the world map: the button names the town
        phone.tap(text="Town", region=NAV_REGION)
        phone.wait_for(text="World", region=NAV_REGION, timeout=15)
    view, tapped = app.town_view, 0
    for name in ("Stable", "Barracks", "Range", "Enlistment Office"):
        x, y = go_to_building(phone, log, name, view=view)
        view = (TOWN[name][0] - x, TOWN[name][1] + LABEL_TO_BUILDING - y)   # where the view is now
        for _ in range(4):
            phone.forget_screen()
            m = vision.find_image(phone.screen(), "cassie_bubble", MAP_AREA, threshold=0.75, scales=BUBBLE_SCALES)
            if not m:
                break
            phone.tap_xy(*m.center)
            tapped += 1
            time.sleep(1)
    app.town_view = None
    log.info("cassie: %d bubble(s) tapped", tapped)


PARTS = {"gems": gems, "vip": vip, "deals": deals, "nomadic_merchant": nomadic_merchant,
         "cassie_recruit": cassie_recruit}


def back_to_main(phone):
    """One Back from a Q1 icon's screen -> the city / world map."""
    phone.back()
    phone.wait_for(text="Backpack", region=NAV_REGION, timeout=10)


def claim_shop_tabs(phone, log):
    """Visit each red-dot tab (names and pictures change) and claim its free chest. Returns how many."""
    for _ in range(3):                                   # tab row back to its start
        if not swipe_tabs(phone, TAB_SWIPE[1], TAB_SWIPE[0]):
            break
    claimed = 0
    for _ in range(MAX_TAB_PAGES):
        tried = set()
        while True:
            dots = [d for d in vision.red_dots(phone.screen(), SHOP_TAB_DOTS) if d[0] // 60 not in tried]
            if not dots:
                break
            x, _ = dots[0]
            tried.add(x // 60)                           # a dot that stays (nothing free after all) is tried once
            phone.tap_xy(max(40, x - 140), SHOP_TAB_ROW_Y)
            time.sleep(1)
            phone.forget_screen()
            claimed += claim_free_chest(phone, log)
        if not swipe_tabs(phone, *TAB_SWIPE):
            break                                        # end of the tab row
    return claimed


def swipe_tabs(phone, x_from, x_to):
    """Swipe the tab row; False if it didn't move (at its end)."""
    before = phone.screen(SHOP_TAB_DOTS)
    phone.swipe(x_from, SHOP_TAB_ROW_Y, x_to, SHOP_TAB_ROW_Y, ms=600)
    time.sleep(1)
    phone.forget_screen()
    return vision.screen_diff(before, phone.screen(SHOP_TAB_DOTS), SHOP_TAB_DOTS) > 3


def claim_free_chest(phone, log):
    """The open tab's free chest, in the header: a chest with its own red dot (labelled "Claimable"), or one
    labelled "Free" (Daily Deals). Some show a "Claimed" pop-up afterwards. Returns 1 if claimed, else 0."""
    img = phone.screen()
    dots = vision.red_dots(img, SHOP_FREE_AREA)
    if dots:
        x, y = dots[0][0] - 40, dots[0][1] + 25          # the dot sits at the chest's top right
    else:
        label = free_label(img)
        if not label:
            log.info("tab has a red dot but no free chest found")
            return 0
        x, y = label[0], label[1] - 75                   # the chest is just above its label
    phone.tap_xy(x, y)
    log.info("claimed the free chest at (%d, %d)", x, y)
    dismiss_popup(phone, wait=2)                         # "Claimed" pop-up (some tabs only)
    return 1


def dismiss_popup(phone, wait=10):
    """Close a reward pop-up ("Click to continue" / "Tap anywhere to exit") by tapping the dim area above it;
    taps during its opening animation are ignored, so tap until it's gone. No pop-up within `wait` s: nothing to do."""
    if not phone.exists(text=re.compile(r"Click to continue|Tap anywhere", re.IGNORECASE), region=POPUP_CONTINUE, timeout=wait):
        return
    for _ in range(6):
        phone.tap_xy(*BLANK_SPOT_PX)
        if not phone.exists(text=re.compile(r"Click to continue|Tap anywhere", re.IGNORECASE), region=POPUP_CONTINUE,
                            timeout=1.2):
            break
    phone.forget_screen()


def open_tab(phone, name):
    """Swipe the tab row until a tab whose name contains `name` shows, and tap it. False if there's none.
    The open tab shows no name in the row, only its big title."""
    if phone.exists(text=name, region=TAB_TITLE):
        return True
    for _ in range(4):                                   # back to the start of the row
        if not swipe_tabs(phone, TAB_SWIPE[1], TAB_SWIPE[0]):
            break
    for _ in range(MAX_TAB_PAGES * 2):
        m = phone.find(text=name, region=TAB_NAMES)
        if m:
            phone.tap_xy(max(100, m.center[0]), SHOP_TAB_ROW_Y)
            time.sleep(1)
            phone.forget_screen()
            return True
        if not swipe_tabs(phone, *SEARCH_SWIPE):        # short steps: a tab cut off at the edge can't be read
            return False
    return False


def claim_glowing(phone, most=7):
    """Tap each glowing (claimable) item of the Free column until none glows. Returns how many."""
    for n in range(most):
        item = glowing_item(phone.screen())
        if not item:
            return n
        phone.tap_xy(*item)
        dismiss_popup(phone, wait=1.5)
        phone.forget_screen()
    return most


def glowing_item(img):
    """Centre of a claimable item in the Free column: it has a pale glowing frame, i.e. a 100-175 px long pale
    line along its top and another 110-160 px below it (white text on items is much shorter). Or None."""
    x1, y1, x2, y2 = FREE_COLUMN
    hsv = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    pale = (hsv[:, :, 1] < 90) & (hsv[:, :, 2] > 220)
    lines = []
    for y in range(pale.shape[0]):
        edges = np.diff(np.concatenate([[0], pale[y].astype(np.int8), [0]]))
        for start, end in zip(np.where(edges == 1)[0], np.where(edges == -1)[0]):
            if 100 <= end - start <= 175:
                lines.append((y, (start + end) // 2))
    for y, cx in lines:
        for y_low, cx_low in lines:
            if 110 <= y_low - y <= 160 and abs(cx_low - cx) < 12:
                return x1 + int(cx), y1 + (y + y_low) // 2
    return None


def free_label(img):
    """(x, y) of a white "Claimable" / "Free" label in the tab header, or None (normal OCR misses this text)."""
    part, (ox, oy) = vision.crop(img, SHOP_FREE_AREA)
    hsv = cv2.cvtColor(part, cv2.COLOR_BGR2HSV)
    white = (hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 200)
    big = cv2.resize(255 - white.astype(np.uint8) * 255, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    data = pytesseract.image_to_data(big, config="--psm 11", output_type=pytesseract.Output.DICT)
    for text, left, top, w, h in zip(data["text"], data["left"], data["top"], data["width"], data["height"]):
        if re.sub(r"[^a-z]", "", text.lower()) in ("claimable", "free"):
            return ox + (left + w / 2) / 2, oy + (top + h / 2) / 2
    return None
