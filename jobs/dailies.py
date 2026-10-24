"""Kingshot job: dailies. Daily at 00:05 UTC (5:35am IST), after troops_training.

Starts on the city screen or world map (bottom menu visible, no pop-up) — game.py's on_open/before_job
open the game and close all pop-ups first; after_job backs out to where it started.
The Q1 icons (gems, VIP, Events, Deals, Sign-in, ...) show on both the town and the world map.
"""

from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING

import cv2
import numpy as np
import pytesseract

import config
from core import switches, vision
from core.phone import ElementNotFound
from core.schedule import At, utcnow
from core.task import job
from jobs.online_rewards import ROW_BUTTON_X, close_panel, find_daily_row, open_daily_tab
from regions import (
    CRUCIBLE_REFINE,
    CRUCIBLE_REMAINING,
    CRUCIBLE_SUPER_X1,
    DEALS_LABEL,
    FREE_COLUMN,
    GEMS_SHOP,
    MERCHANT_BUY_BUTTON,
    MERCHANT_BUY_ITEM,
    MERCHANT_PRICES,
    MERCHANT_REFRESH,
    MERCHANT_TIMER,
    NAV_REGION,
    POPUP_CONTINUE,
    PURCHASE_CONFIRM,
    PURCHASE_DONT_SHOW,
    PURCHASE_TEXT,
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

if TYPE_CHECKING:
    from logging import Logger

    from core.phone import Phone
    from core.vision import Image, Region
    from game import Kingshot

TAB_SWIPE = (900, 200)  # x from / to: one swipe shows the next ~2.5 tabs
MAX_TAB_PAGES = 8
BUBBLE_SCALES = (0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0, 1.1)  # bubbles are drawn smaller near the town edge
MAX_MERCHANT_ROUNDS = 300  # buys + refreshes per run, so it can never loop (one stock took ~80 buys)
SEARCH_SWIPE = (800, 450)
PRICE_ROWS = (0, 0.32, 1, 0.67)  # merchant: the rows with the 6 boxes (icons and price bars)
BLANK_SPOT_PX = (540, 300)  # dim area above reward pop-ups (no buttons behind it take the tap)


@job(schedule=At("00:05", tz="UTC"), priority=100, timeout=1800)  # 5:35am IST, after troops_training; merchant ~12 min
def dailies(app: Kingshot, phone: Phone, log: Logger):
    """The parts below, in order; each starts and ends on the city / world map.
    Test one part: run.py --job dailies --part vip   (several: --part gems,deals; all: leave --part out)
    A part that fails doesn't stop the others. The parts done today (UTC) are kept in DONE_FILE, so a retry runs
    only the rest: e.g. the merchant (it buys VIP XP with gems) never runs twice a day."""
    unknown = set(app.parts or ()) - set(PARTS)
    if unknown:
        raise ValueError(f"no part {', '.join(sorted(unknown))}; parts: {', '.join(PARTS)}")
    today = utcnow().date().isoformat()
    try:
        saved = json.loads(DONE_FILE.read_text())
        done = saved["done"] if saved.get("date") == today else []
    except (FileNotFoundError, ValueError, KeyError):
        done = []
    failed = []
    for name, part in PARTS.items():
        if app.parts is not None and name not in app.parts:
            continue
        if app.parts is None and name in done:
            log.info("part: %s (already done today)", name)
            continue
        if app.parts is None and not switches.part_on("dailies", name):
            log.info("part: %s (off in jobs.toml)", name)
            continue
        log.info("part: %s", name)
        try:
            part(app, phone, log)
        except (ElementNotFound, RuntimeError) as e:  # the other parts still run; the retry does only this one
            log.warning("part %s failed: %s", name, e)
            failed.append(name)
            app.to_main_screen(phone, log)
            continue
        done.append(name)
        DONE_FILE.write_text(json.dumps({"date": today, "done": done}))
    if failed:
        raise RuntimeError(f"part(s) failed: {', '.join(failed)}; the retry runs only the parts not done today")


def gems(app: Kingshot, phone: Phone, log: Logger):
    """Gems button (cart + gem count, top right) -> Top-up Center: every tab with a red dot has a free chest.
    !! Real-money shop: never tap a ₹ price or "TOP UP". Only the free chest in each tab's header is tapped."""
    app.tap_on_main(phone, log, image="gems_shop", region=GEMS_SHOP)
    phone.wait_for(text="Top-up Center", region=TOPUP_TITLE, timeout=10)
    log.info("top-up center open")
    claimed = claim_shop_tabs(phone, log)
    log.info("top-up center: %d free chest(s) claimed", claimed)
    back_to_main(phone)


def vip(app: Kingshot, phone: Phone, log: Logger):
    """VIP (orange V badge; the level number changes) -> VIP screen: the daily sign-in VIP XP chest (red dot) and
    the green Claim of "VIP N Daily Free Bundle". !! The "+" by the XP bar, Shop and the ₹ Special Pack: never."""
    app.tap_on_main(phone, log, image="vip_badge", region=VIP_BADGE, then={"text": "VIP", "region": VIP_TITLE})
    phone.wait_for(text="VIP", region=VIP_TITLE, timeout=10)
    log.info("vip screen open")
    dots = vision.red_dots(phone.screen(), VIP_XP_CHEST)
    if dots:
        phone.tap_xy(dots[0][0] - 45, dots[0][1] + 45)  # the dot sits at the chest's top right
        dismiss_popup(phone)
        log.info("vip: daily VIP XP claimed")
    m = phone.find(text="Claim", region=VIP_BUNDLE_CLAIM)
    button = (m.x - 80, m.y - 20, m.x + m.w + 80, m.y + m.h + 25) if m else None  # the button only, not the row
    if m and 35 <= vision.median_hue(phone.last_screen, button) <= 85:
        phone.tap_xy(*m.center)
        dismiss_popup(phone)
        log.info("vip: daily free bundle claimed")
    back_to_main(phone)


def deals(app: Kingshot, phone: Phone, log: Logger):
    """Deals (gift icon): only two tabs give free things, "Sign-in & Earn It" (a reward per day) and "Hero Rally"
    (rewards unlock as tasks earn points). Claim the glowing items of their Free column.
    !! Never the Epic / Path of Honor column, Unlock, Purchase Level, "+" or any ₹ button."""
    app.tap_on_main(phone, log, text="Deals", region=DEALS_LABEL)
    phone.wait_for(text="Deals", region=SCREEN_TITLE, timeout=10)
    log.info("deals open")
    log.info("deals: %d free chest(s) claimed", claim_shop_tabs(phone, log, need_label=True))  # e.g. Treasure Cove
    for tab in ("Earn", "Rall"):  # "Sign-in & Earn It", "Hero Rally" (OCR-safe parts)
        if open_tab(phone, tab):
            log.info("deals, %s: %d free reward(s) claimed", tab, claim_glowing(phone))
        else:
            log.info("deals: no %r tab", tab)
    back_to_main(phone)


def nomadic_merchant(app: Kingshot, phone: Phone, log: Logger):
    """Shop (bottom menu) -> Nomadic Merchant: buy every box priced in bread / wood / stone / iron until all 6 are
    priced in gems, then Free Refresh and again, until the refresh isn't free. The VIP XP box (yellow V badge) is
    always bought, also for gems (the user's rule).
    !! No other box priced in gems, never a refresh that isn't free."""
    app.tap_on_main(phone, log, text="Shop", region=SHOP_NAV)
    phone.tap(text="Nomadic", region=SHOP_BOTTOM_TABS, timeout=10)
    phone.wait_for(text="Refreshes in", region=MERCHANT_TIMER, timeout=10)
    log.info("nomadic merchant open")
    bought = refreshes = 0
    vip_ok = True  # every VIP XP box is bought (gems); False once a buy doesn't go through (e.g. not enough gems)
    for round_no in range(MAX_MERCHANT_ROUNDS):
        # one screenshot of the price bars, all 6 evaluated; then tap each resource-priced one, but re-check that
        # one bar just before its tap (~0.3 s): a buy restocks and reorders the boxes, so a box can turn into gems
        for _ in range(4):  # a buy's animation can cover the bars for a moment
            phone.forget_screen()
            img = phone.screen(PRICE_ROWS)
            if all(price_bar(img, xy) for xy in MERCHANT_PRICES):
                break
            time.sleep(1)
        boxes = [
            xy
            for xy in MERCHANT_PRICES
            if price_bar(img, xy) and (not gem_price(img, xy) or (vip_ok and vip_xp(img, xy)))
        ]
        if boxes:
            for xy in boxes:
                phone.forget_screen()
                now = phone.screen(box_region(xy))
                if price_bar(now, xy) and not gem_price(now, xy):
                    phone.tap_xy(*xy)  # resources: bought at once
                    bought += 1
                    time.sleep(0.3)
                elif price_bar(now, xy) and vip_xp(now, xy) and vip_ok:
                    got = buy_vip_xp(phone, log, xy)
                    bought += got
                    if not got:  # didn't go through (not enough gems?): its box now counts as a gem box
                        vip_ok = False
            if round_no % 5 == 4 and not merchant_still_open(phone, log):
                log.info("merchant: the merchant screen is gone; stopping")
                break
            continue
        if not all(price_bar(img, xy) for xy in MERCHANT_PRICES):
            log.info("merchant: price bars not all visible; stopping")
            break
        m = phone.find(text="Free Refresh", region=MERCHANT_REFRESH)
        if not m or not 35 <= vision.median_hue(phone.last_screen, MERCHANT_REFRESH) <= 85:
            log.info("merchant: every box costs gems and the refresh isn't free: done")
            break
        phone.tap_xy(*m.center)
        refreshes += 1
        time.sleep(1)
    else:
        log.warning("merchant: stopped after %d rounds (safety limit)", MAX_MERCHANT_ROUNDS)
    log.info("merchant: %d box(es) bought, %d free refresh(es)", bought, refreshes)
    back_to_main(phone)


def merchant_still_open(phone: Phone, log: Logger) -> bool:
    """The merchant screen is still showing ("Refreshes in"). If not, Back is pressed only to close a dialog over it,
    never on a main screen (Back there opens the game's "Quit game?" prompt; if that shows, Cancel). Still gone: a
    screenshot goes to logs/failures/ and False."""
    for _ in range(2):
        if phone.exists(text="Refreshes in", region=MERCHANT_TIMER, timeout=3):
            return True
        if phone.exists(text="Quit game", region=QUIT_TEXT, timeout=1):
            phone.tap(text="Cancel", region=QUIT_CANCEL, timeout=3)  # never Confirm
            time.sleep(1)
            continue
        if phone.exists(text="Backpack", region=NAV_REGION, timeout=1):  # on the town / world map: the merchant closed
            break
        phone.back()  # a dialog over the merchant
        time.sleep(1.5)
        log.info("merchant: closed something that covered it")
    if phone.exists(text="Refreshes in", region=MERCHANT_TIMER, timeout=2):
        return True
    shot = config.FAILURE_DIR / f"merchant_gone_{utcnow():%Y%m%d-%H%M%S}.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(shot), phone.screen())
    log.info("merchant: screen gone; screenshot %s", shot)
    return False


def buy_vip_xp(phone: Phone, log: Logger, xy: tuple[int, int]) -> int:
    """Gem buys open a "Buy" dialog: check it is VIP XP, then tap its orange gem button. Then a "Purchase" pop-up may
    ask "Confirm to spend N gems ...?": only for the same price, tick "Don't show this again today" (so the next buy
    doesn't ask) and confirm. Returns 1 only once the merchant is back (the buy went through), else 0."""
    time.sleep(1)  # the boxes settle after the last buy (a tap while they restock is ignored)
    for _ in range(2):
        phone.tap_xy(*xy)
        if phone.exists(text="VIP XP", region=MERCHANT_BUY_ITEM, timeout=4):
            break
        if not phone.exists(text="Refreshes in", region=MERCHANT_TIMER, timeout=1):
            break  # something else opened: merchant_still_open deals with it
    else:
        log.info("merchant: the VIP XP box opened no buy dialog (2 taps); not buying it this round")
        return 0
    if not phone.exists(text="VIP XP", region=MERCHANT_BUY_ITEM, timeout=1):
        log.info("merchant: no VIP XP buy dialog; not buying")
        return 0
    price = gem_count(phone.read_text(MERCHANT_BUY_BUTTON))
    hue = vision.median_hue(phone.screen(MERCHANT_BUY_BUTTON), MERCHANT_BUY_BUTTON)
    if not 8 <= hue <= 30:
        raise RuntimeError(f"VIP XP buy button isn't orange (hue {hue:.0f}); not tapping")
    x1, y1, x2, y2 = MERCHANT_BUY_BUTTON
    phone.tap_xy(int((x1 + x2) / 2 * 1080), int((y1 + y2) / 2 * 2340))
    time.sleep(1.5)
    phone.forget_screen()
    confirm = phone.read_text(PURCHASE_TEXT)
    if "Confirm to spend" in confirm:
        asked = gem_count(confirm)
        if price is None or asked != price:
            log.info("merchant: the purchase pop-up asks %s gems, the box said %s; not buying", asked, price)
            phone.back()
            return 0
        img = phone.screen()
        if vision.coloured_share(img, PURCHASE_DONT_SHOW) < 0.2:  # not ticked yet
            phone.tap_xy(
                (PURCHASE_DONT_SHOW[0] + PURCHASE_DONT_SHOW[2]) // 2,
                (PURCHASE_DONT_SHOW[1] + PURCHASE_DONT_SHOW[3]) // 2,
            )
            time.sleep(0.8)
            img = phone.screen()
        if not 8 <= vision.median_hue(img, PURCHASE_CONFIRM) <= 30:
            raise RuntimeError("the purchase pop-up's gem button isn't orange; not tapping")
        phone.tap_xy((PURCHASE_CONFIRM[0] + PURCHASE_CONFIRM[2]) // 2, (PURCHASE_CONFIRM[1] + PURCHASE_CONFIRM[3]) // 2)
        time.sleep(1.5)
        phone.forget_screen()
    if not phone.exists(text="Refreshes in", region=MERCHANT_TIMER, timeout=3):
        log.info("merchant: VIP XP buy didn't finish (something is still open); not counting it")
        return 0
    log.info("merchant: bought VIP XP for %s gems", price if price is not None else "?")
    return 1


def gem_count(text: str) -> int | None:
    """The gem amount in a price text ("19", "Confirm to spend 19 gems ..."), or None."""
    m = re.search(r"(\d[\d,]*)\s*(?:gems|$)", text.strip()) or re.search(r"(\d[\d,]*)", text)
    return int(m.group(1).replace(",", "")) if m else None


def box_region(xy: tuple[int, int]) -> Region:
    """Screen rows of one box, its icon to its price bar (for a quick strip screenshot)."""
    return 0, (xy[1] - 340) / 2340, 1, (xy[1] + 32) / 2340


def vip_xp(img: Image, xy: tuple[int, int]) -> bool:
    """Is the item of the box with this price bar VIP XP (yellow V badge, templates/merchant_vip_xp.png)?"""
    x, y = xy
    return vision.find_image(img, "merchant_vip_xp", (x - 160, y - 330, x + 160, y - 50), threshold=0.8) is not None


def price_bar(img: Image, xy: tuple[int, int]) -> bool:
    """Is a merchant price bar really there (cream background)? Guards against tapping when something covers it."""
    x, y = xy
    hsv = cv2.cvtColor(img[y - 30 : y + 30, x - 160 : x + 160], cv2.COLOR_BGR2HSV)
    cream = (
        (hsv[:, :, 0] >= 10) & (hsv[:, :, 0] <= 30) & (hsv[:, :, 1] >= 15) & (hsv[:, :, 1] <= 80) & (hsv[:, :, 2] > 215)
    )
    return 0.35 <= cream.mean() <= 0.75


def gem_price(img: Image, xy: tuple[int, int]) -> bool:
    """Is this price bar in gems (a blue diamond before the number)?"""
    x, y = xy
    hsv = cv2.cvtColor(img[y - 30 : y + 30, x - 160 : x + 160], cv2.COLOR_BGR2HSV)
    blue = (hsv[:, :, 0] >= 95) & (hsv[:, :, 0] <= 115) & (hsv[:, :, 1] > 120) & (hsv[:, :, 2] > 150)
    return bool(blue.sum() > 200)


def cassie_recruit(app: Kingshot, phone: Phone, log: Logger):
    """Town: Stable, Barracks, Range and Enlistment Office can each show a bubble with Cassie's picture; tap every
    one (instant, no pop-up). The first three stand together, so one stop often shows several bubbles."""
    view, tapped = app.town_from_launch(phone, log), 0
    for name in ("Barracks", "Enlistment Office"):
        x, y = go_to_building(phone, log, name, view=view)
        view = (TOWN[name][0] - x, TOWN[name][1] + LABEL_TO_BUILDING - y)  # where the view is now
        for _ in range(4):
            phone.forget_screen()
            m = vision.find_image(phone.screen(), "cassie_bubble", MAP_AREA, threshold=0.75, scales=BUBBLE_SCALES)
            if not m:
                break
            phone.tap_xy(*m.center)
            tapped += 1
            time.sleep(5)
    app.town_view = None
    log.info("cassie: %d bubble(s) tapped", tapped)


def truegold_crucible(app: Kingshot, phone: Phone, log: Logger):
    """World map -> side panel -> Daily tab -> scroll down to "Truegold Crucible" -> its arrow -> Truegold Crucible.
    The Daily tab hides a row once its task is done ("Hide after mission completion"): no row = done today."""
    open_daily_tab(app, phone, log)
    m = find_daily_row(phone, "Truegold Crucible")
    if m is None:
        log.info("crucible: not in the Daily list (it's hidden once done today); nothing to do")
        close_panel(phone)
        return
    arrow = (ROW_BUTTON_X, m.center[1] + 23)
    box = (arrow[0] - 35, arrow[1] - 30, arrow[0] + 35, arrow[1] + 30)
    hue = vision.median_hue(phone.last_screen, box)
    if not 70 <= hue <= 100:  # its green / teal arrow
        raise RuntimeError(f"Truegold Crucible: no arrow at {arrow} (hue {hue:.0f}); not tapping")
    phone.tap_xy(*arrow)
    phone.wait_for(text="Remaining today", region=CRUCIBLE_REMAINING, timeout=10)
    log.info("truegold crucible open")
    # Refine until "Remaining today: 0" (7 a day; each costs more resources, instant, no pop-up)
    refined = 0
    for _ in range(8):
        left = refines_left(phone)
        if left is None:
            log.info("crucible: can't read 'Remaining today'; not refining")
            break
        if left == 0:
            break
        phone.tap(text="Refine", region=CRUCIBLE_REFINE, timeout=5)
        refined += 1
        time.sleep(1)
        phone.forget_screen()
    log.info("crucible: refined %d time(s); refines left today: %s", refined, refines_left(phone))
    # then Super Refine x 1, once (never "x N")
    phone.tap(text="Super Refine", region=CRUCIBLE_SUPER_X1, timeout=5)
    dismiss_popup(phone, wait=3)
    log.info("crucible: super refine x1 done")
    back_to_main(phone)


def refines_left(phone: Phone, tries: int = 3) -> int | None:
    """N from "Remaining today: N" (OCR sometimes puts the N on its own line), or None if unreadable."""
    for _ in range(tries):
        m = re.search(r"today\D*(\d+)|^(\d+)\b", " ".join(phone.read_text(CRUCIBLE_REMAINING).split()), re.IGNORECASE)
        if m:
            return int(m.group(1) or m.group(2))
        phone.forget_screen()
    return None


QUIT_TEXT = (0.1, 0.38, 0.9, 0.48)  # the game's "Quit game?" prompt (Back on a main screen)
QUIT_CANCEL = (0.08, 0.5, 0.48, 0.58)  # ...its orange Cancel (left; Confirm on the right quits: never)
DONE_FILE = config.LOG_DIR / "dailies.json"  # the parts done today (UTC): a retry skips them
PARTS = {
    "gems": gems,
    "vip": vip,
    "deals": deals,
    "nomadic_merchant": nomadic_merchant,
    "cassie_recruit": cassie_recruit,
    "truegold_crucible": truegold_crucible,
}


def back_to_main(phone: Phone) -> None:
    """One Back from a Q1 icon's screen -> the city / world map."""
    phone.back()
    phone.wait_for(text="Backpack", region=NAV_REGION, timeout=10)


def claim_shop_tabs(phone: Phone, log: Logger, need_label: bool = False) -> int:
    """Visit each red-dot tab (names and pictures change) and claim its free chest. Returns how many."""
    for _ in range(3):  # tab row back to its start
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
            tried.add(x // 60)  # a dot that stays (nothing free after all) is tried once
            phone.tap_xy(max(40, x - 140), SHOP_TAB_ROW_Y)
            time.sleep(1)
            phone.forget_screen()
            claimed += claim_free_chest(phone, log, need_label)
        if not swipe_tabs(phone, *TAB_SWIPE):
            break  # end of the tab row
    return claimed


def swipe_tabs(phone: Phone, x_from: int, x_to: int) -> bool:
    """Swipe the tab row; False if it didn't move (at its end)."""
    before = phone.screen(SHOP_TAB_DOTS)
    phone.swipe(x_from, SHOP_TAB_ROW_Y, x_to, SHOP_TAB_ROW_Y, ms=600)
    time.sleep(1)
    phone.forget_screen()
    return vision.screen_diff(before, phone.screen(SHOP_TAB_DOTS), SHOP_TAB_DOTS) > 3


def claim_free_chest(phone: Phone, log: Logger, need_label: bool = False) -> int:
    """The open tab's free chest, in the header: a chest with its own red dot (labelled "Claimable"), or one
    labelled "Free" (Daily Deals). Some show a "Claimed" pop-up afterwards. Returns 1 if claimed, else 0."""
    for _ in range(5):  # the tab's content can take a few seconds to draw
        img = phone.screen()
        dots = vision.red_dots(img, SHOP_FREE_AREA)
        label = free_label(img) if need_label or not dots else None
        if need_label and not label:  # Deals: a red dot alone isn't enough (Hall of Heroes...)
            dots = []
        if dots or label:
            break
        time.sleep(0.8)
        phone.forget_screen()
    if dots:
        x, y = dots[0][0] - 40, dots[0][1] + 25  # the dot sits at the chest's top right
    elif label:
        x, y = label[0], label[1] - 75  # the chest is just above its label
    else:
        log.info("tab has a red dot but no free chest found")
        return 0
    phone.tap_xy(x, y)
    log.info("claimed the free chest at (%d, %d)", x, y)
    dismiss_popup(phone, wait=2)  # "Claimed" pop-up (some tabs only)
    return 1


def dismiss_popup(phone: Phone, wait: float = 10) -> None:
    """Close a reward pop-up ("Click to continue" / "Tap anywhere to exit") by tapping the dim area above it;
    taps during its opening animation are ignored, so tap until it's gone. No pop-up within `wait` s: nothing to do."""
    if not phone.exists(
        text=re.compile(r"Click to continue|Tap anywhere", re.IGNORECASE), region=POPUP_CONTINUE, timeout=wait
    ):
        return
    for _ in range(6):
        phone.tap_xy(*BLANK_SPOT_PX)
        if not phone.exists(
            text=re.compile(r"Click to continue|Tap anywhere", re.IGNORECASE), region=POPUP_CONTINUE, timeout=1.2
        ):
            break
    phone.forget_screen()


def open_tab(phone: Phone, name: str) -> bool:
    """Swipe the tab row until a tab whose name contains `name` shows, and tap it. False if there's none.
    The open tab shows no name in the row, only its big title."""
    if phone.exists(text=name, region=TAB_TITLE):
        return True
    for _ in range(4):  # back to the start of the row
        if not swipe_tabs(phone, TAB_SWIPE[1], TAB_SWIPE[0]):
            break
    stuck = 0
    for _ in range(MAX_TAB_PAGES * 2):
        m = phone.find(text=name, region=TAB_NAMES)
        if m:
            phone.tap_xy(max(100, m.center[0]), SHOP_TAB_ROW_Y)
            time.sleep(1)
            phone.forget_screen()
            return True
        if swipe_tabs(phone, *SEARCH_SWIPE):  # short steps: a tab cut off at the edge can't be read
            stuck = 0
        else:
            stuck += 1
            if stuck == 2:  # twice: at the end of the row (once can be a swipe lost while the page settles)
                return False
    return False


def claim_glowing(phone: Phone, most: int = 7) -> int:
    """Tap each glowing (claimable) item of the Free column until none glows. Returns how many."""
    for n in range(most):
        for _ in range(5 if n == 0 else 1):  # a freshly opened tab scrolls to today first: wait for it
            item = glowing_item(phone.screen())
            if item:
                break
            time.sleep(0.8)
            phone.forget_screen()
        if not item:
            return n
        phone.tap_xy(*item)
        dismiss_popup(phone, wait=1.5)
        phone.forget_screen()
    return most


def glowing_item(img: Image) -> tuple[int, int] | None:
    """Centre of a claimable item in the Free column: it has a pale glowing frame, i.e. a 100-175 px long pale
    line along its top and another 110-160 px below it (white text on items is much shorter). Or None."""
    x1, y1, x2, y2 = FREE_COLUMN
    hsv = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    pale = (
        (hsv[:, :, 0] >= 18) & (hsv[:, :, 0] <= 40) & (hsv[:, :, 1] < 130) & (hsv[:, :, 2] > 190)
    )  # pale yellow; it pulses
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


def free_label(img: Image) -> tuple[float, float] | None:
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
