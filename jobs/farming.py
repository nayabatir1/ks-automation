"""Kingshot job: farming. Every 7.5 h.

World map -> magnifying glass (bottom left) -> search panel; for Bread, Wood, Stone and Iron: pick it in the row,
the highest level (the "+" by the slider is grey; held until it is) and the "Only search for full Resources"
tick -> Search -> Gather -> remove heroes 3 and 2 -> Deploy.
"Other Troops are marching toward the same target" -> Cancel, search again. Troops aren't waited for.
Starts on the city screen or world map; after_job backs out to where it started.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import cv2
import numpy as np
import pytesseract

import config
from core import vision
from core.phone import ElementNotFound
from core.schedule import utcnow
from core.task import job, run_parts
from core.timeparse import parse_duration
from core.vision import load_template
from jobs.online_rewards import close_panel
from regions import (
    AUTO_JOIN_CLOSE,
    AUTO_JOIN_ENABLE,
    AUTO_JOIN_FLAG,
    AUTO_JOIN_MINUS,
    AUTO_JOIN_STOP,
    AUTO_JOIN_TITLE,
    AUTO_JOIN_TRACK,
    DEPLOY_BUTTON,
    HERO_MINUS,
    LEFT_MID,
    MARCH_BADGE,
    MARCH_QUEUE,
    MARCH_RECALL_X,
    MARCH_ROW_STEP,
    MARCH_ROW_Y,
    MARCHING_TITLE,
    NAV_REGION,
    QUEUE_ROW_STEP,
    QUEUE_ROW_Y,
    RECALL_CONFIRM,
    SAME_TARGET_CANCEL,
    SCREEN_TITLE,
    SEARCH_BUTTON,
    SEARCH_GO,
    SEARCH_LEVEL_LABEL,
    SEARCH_LEVEL_PLUS,
    SEARCH_ROW,
    SEARCH_TICK,
    SIDE_PANEL,
    SIDE_PANEL_WILDERNESS_TAB,
    TILE_GATHER,
)

if TYPE_CHECKING:
    from logging import Logger

    from core.phone import Phone
    from core.vision import Image
    from game import Kingshot

RESOURCES = ("Bread", "Wood", "Stone", "Iron")
TILE_KEYS = ("Mill", "Lumber", "Quarry", "ron Mine")  # in their tiles' names (Idle Mill / Lumberyard / ...)
MARCHES = 6  # march slots ("Marching N/6")
EVERY = timedelta(hours=7, minutes=30)  # fallback round time when the gathering timers don't read
FARMING_FILE = config.LOG_DIR / "farming.json"  # next_refresh: the next regular run; march: last march time (s)


@dataclass
class March:
    """A row of the world map's Marching list: status "Gathering" / "Returning" / "Rallying" / coordinates (on its
    way), kind = the resource on its icon (None: not a resource march), secured = white badge on the icon."""

    status: str
    kind: str | None
    secured: bool
    y: int
    timer: timedelta | None  # the countdown under the status: time left gathering / coming home / to the tile


SEARCH_PANEL_GO = (0.2, 0.9, 0.8, 0.99)  # the search panel's "Search" button (the panel is open)
DEPLOY_TAP = (822, 2240)


@job(timeout=900)  # every 7.5 h (the job returns it); waiting for recalled marches can take minutes
def farming(app: Kingshot, phone: Phone, log: Logger):
    """The regular run (when the slowest march of the last round is due home): set_queue_limit, then recall and
    resend everything. A follow-up run (marches still moving, or a resource failed) only sends the resources that
    aren't out, without recalling. Once all marches gather, the next regular run is booked for the longest gathering
    time left + the march time back (see plan_next)."""
    refresh = refresh_due()
    next_run = [EVERY]

    def queue_part(app: Kingshot, phone: Phone, log: Logger) -> None:
        if refresh or app.parts:
            set_queue_limit(app, phone, log)

    def gather_part(app: Kingshot, phone: Phone, log: Logger) -> None:
        next_run[0] = gather_all(app, phone, log, recall=refresh)

    run_parts(app, phone, log, {"set_queue_limit": queue_part, "gather": gather_part})
    return next_run[0]


def refresh_due() -> bool:
    """A regular run: the time booked for it (FARMING_FILE "next_refresh", minus 2 min) has come, or none is booked."""
    data = load_farming()
    try:
        if "next_refresh" in data:
            return utcnow() >= datetime.fromisoformat(data["next_refresh"]) - timedelta(minutes=2)
        if "refreshed" in data:  # the older file: the last full send + EVERY
            return utcnow() - datetime.fromisoformat(data["refreshed"]) >= EVERY - timedelta(minutes=30)
    except ValueError:
        pass
    return True


def load_farming() -> dict:
    try:
        return json.loads(FARMING_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def save_farming(**values: object) -> None:
    FARMING_FILE.write_text(json.dumps({**load_farming(), **values}))


def open_search_panel(app: Kingshot, phone: Phone, log: Logger) -> None:
    """World map -> magnifying glass (bottom left) -> search panel. Skipped if it's already open."""
    if phone.exists(text="Search", region=SEARCH_PANEL_GO, timeout=1):
        return
    if phone.exists(text="World", region=NAV_REGION):  # on the town: the button names the world map
        phone.tap(text="World", region=NAV_REGION)
        phone.wait_for(text="Town", region=NAV_REGION, timeout=15)
    app.tap_on_main(
        phone, log, image="search_button", region=SEARCH_BUTTON, then={"text": "Search", "region": SEARCH_PANEL_GO}
    )
    phone.wait_for(text="Search", region=SEARCH_PANEL_GO, timeout=10)
    log.info("search panel open")


def set_queue_limit(app: Kingshot, phone: Phone, log: Logger) -> None:
    """Search panel -> Terror -> Auto Join (flag, bottom right): Stop it if it runs (orange Stop), hold "-" until the
    Queue Limit is 1 (the slider's track has no green fill), Enable (a fresh 8 h), close the pop-up."""
    open_search_panel(app, phone, log)
    m = phone.find(text="Terror", region=SEARCH_ROW)
    if not m:
        swipe_row_to_start(phone)  # Terror is the row's second target
        m = phone.find(text="Terror", region=SEARCH_ROW)
    if not m:
        raise ElementNotFound("Terror isn't in the search row")
    phone.tap_xy(m.center[0], m.center[1] - 60)  # the tile picture above its name
    time.sleep(1.2)
    phone.tap_xy(*AUTO_JOIN_FLAG)
    phone.wait_for(text="Auto", region=AUTO_JOIN_TITLE, timeout=10)
    time.sleep(1)
    phone.forget_screen()
    if button_is(phone.screen(), AUTO_JOIN_STOP, hues=(5, 25)):  # orange: Auto-Join is on
        phone.tap_xy(*mid(AUTO_JOIN_STOP))
        time.sleep(1.5)
        log.info("auto-join: stopped")
    for _ in range(4):  # Stop puts the Queue Limit back to 6
        phone.forget_screen()
        if queue_limit_is_1(phone.screen()):
            break
        phone.hold_xy(*mid(AUTO_JOIN_MINUS), seconds=3)
        time.sleep(0.5)
    else:
        raise RuntimeError("the Auto-Join Queue Limit isn't 1 after holding -; not enabling")
    if not button_is(phone.screen(), AUTO_JOIN_ENABLE, hues=(75, 105)):  # teal "Enable" (or "Restart")
        raise RuntimeError("Auto-Join: the Enable button isn't teal; not tapping")
    phone.tap_xy(*mid(AUTO_JOIN_ENABLE))
    time.sleep(1.5)
    phone.forget_screen()
    if not button_is(phone.screen(), AUTO_JOIN_STOP, hues=(5, 25)):
        raise RuntimeError("Auto-Join didn't start (Stop isn't orange)")
    log.info("auto-join: enabled with Queue Limit 1")
    phone.tap_xy(*AUTO_JOIN_CLOSE)
    phone.wait_gone(text="Auto", region=AUTO_JOIN_TITLE, timeout=5)


def mid_region(region: tuple[float, float, float, float]) -> tuple[int, int]:
    """Centre of a fractional region, in pixels."""
    return int((region[0] + region[2]) / 2 * 1080), int((region[1] + region[3]) / 2 * 2340)


def mid(box: tuple[int, int, int, int]) -> tuple[int, int]:
    """Centre of a pixel box."""
    return (box[0] + box[2]) // 2, (box[1] + box[3]) // 2


def button_is(img: Image, box: tuple[int, int, int, int], hues: tuple[int, int]) -> bool:
    """The button in this pixel box is coloured (not grey) with its hue in the range."""
    return vision.coloured_share(img, box) > 0.3 and hues[0] <= vision.median_hue(img, box) <= hues[1]


def queue_limit_is_1(img: Image) -> bool:
    """Queue Limit 1 = the slider's handle at the far left: no green fill in its track (6 fills it)."""
    x1, y1, x2, y2 = AUTO_JOIN_TRACK
    hsv = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    green = (hsv[:, :, 0] >= 45) & (hsv[:, :, 0] <= 80) & (hsv[:, :, 1] > 120) & (hsv[:, :, 2] > 150)
    return float(green.mean()) < 0.05


def gather_all(app: Kingshot, phone: Phone, log: Logger, recall: bool = True) -> timedelta:
    """recall=True (the regular run): recall every unsecured gathering march (map's Marching list; secured ones,
    rallies and other marches stay). Then the side panel's Wilderness tab (March Queue: one row per march slot) says
    what's left: marches still coming home or still on their way to a tile aren't waited for, the job comes back when
    the longest of their timers has run out (the game is closed meanwhile). With none: send each resource that isn't
    out into the "Idle" slots. A resource that fails is tried again after RETRY_MINUTES (only that one).
    Returns when the job should run next."""
    to_world_map(phone)
    if recall:
        recall_gathering(phone, log)
        save_farming(next_refresh=(utcnow() + EVERY).isoformat())  # for now; plan_next books the real time
    on_world_map(phone)
    slots = march_queue(phone, log)
    close_panel(phone)
    # wait for marches coming home (they free slots); on a regular run also for ours still on their way (recalled
    # once they gather). A follow-up run doesn't wait for those: they're the ones it sent.
    moving = [q for q in slots if q.moving and (recall or q.returning)]
    if moving:
        timers = [q.timer for q in moving if q.timer]
        wait = (max(timers) if timers else timedelta(minutes=2)) + timedelta(seconds=20)
        log.info("%d march(es) still moving (longest %s); back in %s", len(moving), max(timers, default="?"), wait)
        return wait
    out = {k for q in slots if (k := q.kind)}
    todo = [k for k in RESOURCES if k not in out]
    free = sum(q.idle for q in slots)
    log.info("march queue: %d of %d idle; out: %s; to send: %s", free, len(slots), sorted(out) or "-", todo or "-")
    failed = []
    if todo:
        open_search_panel(app, phone, log)
    for kind in todo[:free]:
        try:
            gather(phone, log, kind)
        except (ElementNotFound, RuntimeError) as e:  # only this one is tried again
            log.info("%s: not sent (%s)", kind, e)
            failed.append(kind)
            back_to_search(app, phone, log)
    if len(todo) > free:
        log.info("no free march for %s", ", ".join(todo[free:]))
    if failed:
        log.info("trying %s again in %d min", ", ".join(failed), config.RETRY_MINUTES)
        return timedelta(minutes=config.RETRY_MINUTES)
    return plan_next(phone, log, sent=bool(todo[:free]))


def plan_next(phone: Phone, log: Logger, sent: bool) -> timedelta:
    """When to run next, from the March Queue. Ours still on their way: when the slowest arrives (right after
    sending, that's also the march time, kept for the way back). All gathering: the next regular run, when the
    slowest is home again = its gathering time left + the march time back. Timers unread: EVERY."""
    to_world_map(phone)
    on_world_map(phone)
    slots = march_queue(phone, log)
    close_panel(phone)
    ours = [q for q in slots if q.kind]
    on_way = [q for q in ours if q.on_way]
    if on_way:
        timers = [q.timer for q in on_way if q.timer]
        wait = max(timers) if timers else timedelta(minutes=2)
        if sent and timers:
            save_farming(march=wait.total_seconds())
        log.info("%d march(es) on their way (longest %s); back when they gather", len(on_way), wait)
        return wait + timedelta(seconds=20)
    gathering = [q.timer for q in ours if q.gathering]
    left = [t for t in gathering if t]
    if left and len(left) == len(gathering):
        march = timedelta(seconds=float(load_farming().get("march", 300)))
        wait = max(left) + march + timedelta(minutes=1)
        save_farming(next_refresh=(utcnow() + wait).isoformat())
        log.info("all gathering (longest %s left) + %s back: next round in %s", max(left), march, wait)
        return wait
    log.info("gathering times not readable; next round in %s", EVERY)
    save_farming(next_refresh=(utcnow() + EVERY).isoformat())
    return EVERY


def back_to_search(app: Kingshot, phone: Phone, log: Logger) -> None:
    """After a failed send: back out (a tile box or the formation page may be open) and reopen the search panel."""
    for _ in range(3):
        if phone.exists(text="Town", region=NAV_REGION, timeout=1):
            break
        phone.back()
        time.sleep(1)
    open_search_panel(app, phone, log)


@dataclass
class Slot:
    """A row of the side panel's March Queue (Wilderness tab): its title ("Gathering Lv.8 Idle Mill", "Great Mill
    gathering" = secured, "Attack Lv.8 Titan Roc", "March Queue 6") and second line (a timer, or "Idle")."""

    title: str
    line2: str

    @property
    def text(self) -> str:
        """Both lines (a march on its way has its timer on the title line: "Go to Lv.8 Idle Iron Mine 00:00:10")."""
        return f"{self.title} {self.line2}"

    @property
    def idle(self) -> bool:
        return "Idle" in self.line2 or self.title.startswith("March Queue")

    @property
    def kind(self) -> str | None:
        """The resource of one of our marches, from its tile's name (OCR reads "Iron" as "lron": the keys skip that
        letter). None for anything else, also a secured gather at an alliance "Great ..." building."""
        if "Great" in self.text:
            return None
        return next((k for k, t in zip(RESOURCES, TILE_KEYS, strict=True) if t in self.text), None)

    @property
    def returning(self) -> bool:
        return "eturn" in self.text

    @property
    def on_way(self) -> bool:
        """One of ours still marching to its tile: "Go to Lv.8 Idle Mill"."""
        return bool(self.kind) and "Go to" in self.text

    @property
    def gathering(self) -> bool:
        """One of ours at its tile: any row of ours that isn't on its way or coming home (OCR can garble "Gathering"
        into "Da ng", so the word itself isn't relied on)."""
        return bool(self.kind) and not self.on_way and not self.returning

    @property
    def moving(self) -> bool:
        """Coming home, or one of ours still on its way to its tile."""
        return self.returning or self.on_way

    @property
    def timer(self) -> timedelta | None:
        return parse_duration(self.line2) if re.search(r"\d:\d\d", self.line2) else None


def march_queue(phone: Phone, log: Logger) -> list[Slot]:
    """Side panel (">" tab, left) -> Wilderness tab -> March Queue: one Slot per march slot, top to bottom."""
    phone.tap(image="side_tab", region=LEFT_MID, timeout=5)
    phone.wait_for(text="Wilderness", region=SIDE_PANEL, timeout=10)
    phone.tap_xy(*SIDE_PANEL_WILDERNESS_TAB)
    phone.wait_for(text="March Queue", region=MARCH_QUEUE, timeout=10)
    time.sleep(1)
    phone.forget_screen()
    lines = vision.ocr_lines(phone.screen(MARCH_QUEUE), MARCH_QUEUE)
    rows: dict[int, list[vision.Match]] = {}
    for m in lines:
        i = (m.center[1] - QUEUE_ROW_Y) // QUEUE_ROW_STEP
        if 0 <= i < MARCHES:
            rows.setdefault(i, []).append(m)
    slots = []
    for i in sorted(rows):
        low = [m for m in rows[i] if re.search(r"\d:\d\d|\bIdle\b", m.text)]  # the timer, or "Idle"
        top = [m for m in rows[i] if m not in low]
        slots.append(Slot(" ".join(m.text for m in sorted(top, key=lambda m: m.x)), " ".join(m.text for m in low)))
    log.info("march queue: %s", "; ".join(f"{q.title} [{q.line2}]" for q in slots))
    return slots


def max_timer_text(rows: list[March]) -> str:
    timers = [m.timer for m in rows if m.timer]
    return str(max(timers)) if timers else "timer unread"


def to_world_map(phone: Phone) -> None:
    if phone.exists(text="World", region=NAV_REGION):  # on the town: the button names the world map
        phone.tap(text="World", region=NAV_REGION)
        phone.wait_for(text="Town", region=NAV_REGION, timeout=15)
        time.sleep(1.5)


def marches_out(phone: Phone) -> int:
    """How many marches are out: the rows of the Marching list (world map, left), counted by the teal button at
    each row's right end (recall / view / speed-up). The "N/6" counter isn't used: it sits on the animated portal
    and misreads. A folded-up list (only its "Marching" title) is opened first."""
    for _ in range(2):
        phone.forget_screen()
        img = phone.screen()
        n = 0
        while n < MARCHES:
            y = MARCH_ROW_Y + MARCH_ROW_STEP * n
            box = (MARCH_RECALL_X - 23, y - 22, MARCH_RECALL_X + 24, y + 22)
            if not (vision.coloured_share(img, box) > 0.5 and 86 <= vision.median_hue(img, box) <= 98):
                break
            n += 1
        if n or not phone.exists(text="Marching", region=MARCHING_TITLE):
            return n
        phone.tap_xy(*mid_region(MARCHING_TITLE))  # folded up: open it
        time.sleep(1)
    return 0


def march_rows(phone: Phone) -> list[March]:
    """The marches in the list, top to bottom (see March)."""
    out = marches_out(phone)
    img = phone.last_screen
    rows = []
    for i in range(out):
        y = MARCH_ROW_Y + MARCH_ROW_STEP * i
        x1, y1, x2, y2 = MARCH_BADGE
        hsv = cv2.cvtColor(img[y + y1 : y + y2, x1:x2], cv2.COLOR_BGR2HSV)
        secured = int(((hsv[:, :, 1] < 40) & (hsv[:, :, 2] > 215)).sum()) > 50
        timer = parse_duration(white_text(img, (85, y + 2, 260, y + 34), "0123456789:"))
        rows.append(March(white_text(img, (85, y - 38, 260, y - 4)), march_kind(img, y), secured, y, timer))
    return rows


def march_kind(img: Image, y: int) -> str | None:
    """The resource on a row's icon (templates/march_<kind>.png), or None (a rally, an attack, ...)."""
    part = img[y - 40 : y + 40, 5:95]
    scores = {
        kind: float(cv2.minMaxLoc(cv2.matchTemplate(part, load_template(f"march_{kind}")[0], cv2.TM_CCOEFF_NORMED))[1])
        for kind in ("bread", "wood", "stone", "iron")
    }
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] >= 0.82 else None  # own icon 0.84-1.0 (secured: badge), others <= 0.79


def recall_gathering(phone: Phone, log: Logger) -> int:
    """Recall every unsecured resource march that is gathering now. Secured ones (white badge), rallies and other
    marches stay; one still marching to its tile is recalled by the next run, once it gathers. The list is read
    again after each recall: rows move up when a march gets home. Returns how many were recalled."""
    recalled = 0
    for _ in range(MARCHES):
        on_world_map(phone)
        gathering = [m for m in march_rows(phone) if m.kind and not m.secured and m.status.startswith("Gather")]
        if not gathering:  # (OCR may cut the end of "Gathering")
            break
        m = gathering[0]
        phone.tap_xy(MARCH_RECALL_X, m.y)  # the teal return arrow at the row's right end
        confirm = phone.wait_for(text="Confirm", region=RECALL_CONFIRM, timeout=5)  # "Recall squad?"
        phone.tap_xy(*confirm.center)
        time.sleep(1.5)
        recalled += 1
        log.info("recalled a %s march", m.kind)
    for m in march_rows(phone):
        if m.secured and m.status.startswith("Gather"):
            log.info("left a secured %s march out", m.kind or "gathering")
    return recalled


def on_world_map(phone: Phone) -> None:
    """The plain world map (bottom menu says "Town"): close whatever is open over it (Back, at most 3 times)."""
    for _ in range(3):
        if phone.exists(text="Town", region=NAV_REGION, timeout=1):
            return
        phone.back()
        time.sleep(1)
    raise RuntimeError("not on the world map")


def white_text(img: Image, box: tuple[int, int, int, int], whitelist: str = "") -> str:
    """OCR of only the white pixels in a pixel box (white text over the moving map)."""
    x1, y1, x2, y2 = box
    hsv = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 200)).astype(np.uint8) * 255
    big = cv2.resize(255 - mask, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
    big = cv2.copyMakeBorder(big, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    config = f"--psm 7 -c tessedit_char_whitelist={whitelist}" if whitelist else "--psm 7"
    return pytesseract.image_to_string(big, config=config).strip()


def gather(phone: Phone, log: Logger, kind: str, tries: int = 3) -> None:
    """One march to a Lv.8 tile of this resource. Starts and ends on the world map."""
    for attempt in range(tries):
        if not phone.exists(text="Search", region=SEARCH_PANEL_GO, timeout=1):
            phone.tap(image="search_button", region=SEARCH_BUTTON, timeout=10)
            phone.wait_for(text="Search", region=SEARCH_PANEL_GO, timeout=10)
        m = phone.find(text=kind, region=SEARCH_ROW)
        if not m:
            swipe_row_to_end(phone)  # Bread / Wood / Stone / Iron are at the row's right end
            m = phone.find(text=kind, region=SEARCH_ROW)
        if not m:
            raise ElementNotFound(f"{kind} isn't in the search row")
        phone.tap_xy(m.center[0], m.center[1] - 60)  # the tile picture above its name
        time.sleep(1.2)
        max_level(phone, log, kind)  # each resource keeps its own level: always check it
        log.info("%s: searching at Lv.%s (the highest)", kind, level_label(phone.last_screen) or "?")
        if vision.coloured_share(phone.last_screen, SEARCH_TICK) < 0.1:
            raise RuntimeError(f"{kind}: 'Only search for full Resources' isn't ticked; not searching")
        phone.tap_xy(*SEARCH_GO)
        gather_button = phone.wait_for(text="Gather", region=TILE_GATHER, timeout=10)
        for _ in range(2):  # a tap while the tile box is still animating in is ignored: tap again
            phone.tap_xy(*gather_button.center)
            if phone.exists(text=kind, region=SCREEN_TITLE, timeout=8):  # formation page, titled by the resource
                break
        else:
            raise ElementNotFound(f"{kind}: the formation page didn't open after Gather")
        for hero in (3, 2):  # right to left, so the cards can't shift under the taps
            phone.tap_xy(*HERO_MINUS[hero])
            time.sleep(1)
        hue = vision.median_hue(phone.screen(DEPLOY_BUTTON), DEPLOY_BUTTON)
        if not 75 <= hue <= 105:
            raise RuntimeError(f"{kind}: Deploy isn't teal (hue {hue:.0f}); not tapping")
        phone.tap_xy(*DEPLOY_TAP)
        time.sleep(2)
        phone.forget_screen()
        cancel = phone.find(text="Cancel", region=SAME_TARGET_CANCEL)
        if cancel:  # someone already marches there: another tile
            log.info("%s: tile already targeted; searching again", kind)
            phone.tap_xy(*cancel.center)
            time.sleep(1.5)
            phone.back()  # formation page -> world map
            time.sleep(1.5)
            continue
        log.info("%s: deployed (attempt %d)", kind, attempt + 1)
        return
    log.info("%s: no free tile after %d tries", kind, tries)


def swipe_row_to_start(phone: Phone) -> None:
    """Swipe the search panel's row of targets right until it stops moving (Beasts, Terror, ... at the left)."""
    for _ in range(6):
        phone.forget_screen()
        before = phone.screen(SEARCH_ROW)
        phone.swipe(150, 1785, 950, 1785, ms=400)
        time.sleep(1)
        phone.forget_screen()
        if vision.screen_diff(before, phone.screen(SEARCH_ROW), SEARCH_ROW) < 3:
            return


def swipe_row_to_end(phone: Phone) -> None:
    """Swipe the search panel's row of targets left until it stops moving."""
    for _ in range(6):
        phone.forget_screen()
        before = phone.screen(SEARCH_ROW)
        phone.swipe(950, 1785, 150, 1785, ms=400)
        time.sleep(1)
        phone.forget_screen()
        if vision.screen_diff(before, phone.screen(SEARCH_ROW), SEARCH_ROW) < 3:
            return


def max_level(phone: Phone, log: Logger, kind: str) -> None:
    """The highest search level: the "+" right of the slider is grey there. Teal: hold it until it's grey."""
    for _ in range(4):
        phone.forget_screen()
        if vision.coloured_share(phone.screen(), SEARCH_LEVEL_PLUS) < 0.2:
            return
        log.info("%s: not at the highest level yet; holding +", kind)
        x1, y1, x2, y2 = SEARCH_LEVEL_PLUS
        phone.hold_xy((x1 + x2) // 2, (y1 + y2) // 2, seconds=3)
        time.sleep(0.5)
    raise RuntimeError(f"{kind}: the level's + button is still not grey; not searching")


def level_label(img: Image) -> int | None:
    """The number in the search panel's "Lv.N" label, or None."""
    x1, y1, x2, y2 = SEARCH_LEVEL_LABEL
    gray = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    big = cv2.resize(cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1], None, fx=3, fy=3)
    big = cv2.copyMakeBorder(big, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    text = pytesseract.image_to_string(big, config="--psm 7 -c tessedit_char_whitelist=Lv.0123456789")
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else None
