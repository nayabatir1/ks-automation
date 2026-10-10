"""Kingshot (com.run.tower.defense): what every job shares.

Launch sequence seen on 2026-10-03 (fresh start, ~25 s total):
    0-2 s   black (Unity starting)
    ~6 s    "WHITE BEAR STUDIO" splash
    9-15 s  loading screen, progress text "0.00 MB / 0.01 MB (0.00%)" near the bottom + tips
    ~20 s   transition, "Skip transition animations"
    25 s+   offer pop-up(s), e.g. "Imperial Consortium", each with a close X somewhere in the
            top-right quarter (templates/close_x.png)
            !! these pop-ups have real-money buttons (e.g. "₹89.00") — never tap blindly !!
"""
import time
from logging import Logger
from typing import Any

import cv2
import numpy as np

from core import vision
from core.phone import ElementNotFound, Phone, PhoneError
from core.task import Task
from core.vision import Image
from regions import (
    LOADING,
    LOADING_REGION,
    NAV_Q4,
    NAV_REGION,
    POPUP_X_REGION,
    RESOURCE_PACK_ENTER,
    SESSION_TAKEN_TEXT,
    WELCOME_CONFIRM,
    WELCOME_TITLE,
)


class Kingshot(Task):
    name = "kingshot"
    package: str = "com.run.tower.defense"
    jobs_package = "jobs"                # jobs/*.py, one file per job
    town_view = None                     # town view position if known: (0, 0) right after a fresh launch
    reuse_open_app = True                # game already open? use it (on_open checks the screen)
    timeout = 240                 # per job
    open_timeout = 240            # launch + loading + pop-ups
    enabled = True

    # ------------------------------------------------------------------ hooks (runner calls these)
    # launch -> on_open -> [before_job -> job] ... -> close app. Jobs start on the city screen.
    def on_open(self, phone: Phone, log: Logger) -> None:
        if self.app_was_open:
            try:   # already running: back out to the city / world map (closing any pop-up)
                self.to_main_screen(phone, log)
                self._just_opened = True
                self.town_view = None                    # the town view could be anywhere
                return
            except ElementNotFound:
                log.info("game is open on a screen I don't know; restarting it")
                phone.launch(self.package, self.activity)
        self.open_game(phone, log)
        self.close_popups(phone, log)
        self._just_opened = True
        self.town_view = (0, 0)                          # fresh launch: town view centred on the Town Center

    def before_job(self, phone: Phone, log: Logger) -> None:
        if getattr(self, "_just_opened", False):   # on_open already left us on the city screen
            self._just_opened = False
        else:
            self.to_main_screen(phone, log)          # the previous job may have ended deep in a menu
            self.town_view = None                        # ...and moved the town view
        self.start_view = self.current_view(phone)

    def town_from_launch(self, phone: Phone, log: Logger) -> tuple[float, float] | None:
        """The town view with a known position, for jobs that go to a building: right after a fresh launch it is
        centred on the Town Center ((0, 0)); otherwise the game is relaunched (the user's choice: more reliable than
        working out where an old view is). Returns the view."""
        if self.town_view is None:
            log.info("town view unknown: relaunching the game")
            self.app_was_open = False
            phone.launch(self.package, self.activity)
            self.on_open(phone, log)
        self._just_opened = False
        return self.town_view

    def after_job(self, phone: Phone, log: Logger) -> None:
        """Close the job's pages and go back to the view the job started from: world map or town."""
        self.to_main_screen(phone, log)
        if self.current_view(phone) != self.start_view:
            button, then = ("World", "Town") if self.start_view == "world" else ("Town", "World")
            phone.tap(text=button, region=NAV_Q4, timeout=5)
            phone.wait_for(text=then, region=NAV_Q4, timeout=15)
            self.town_view = None
        log.info("back on the %s", self.start_view)

    @staticmethod
    def current_view(phone: Phone) -> str:
        """'world' or 'town': the bottom-right button names the other one."""
        return "world" if phone.exists(text="Town", region=NAV_Q4) else "town"

    def session_taken(self, phone: Phone) -> bool:
        """'The account has been logged in on another device.' (Tips box with Contact Us / Reconnect).
        Never tap Reconnect: that would kick the user off their own phone."""
        return phone.exists(text="logged in on another device", region=SESSION_TAKEN_TEXT)

    # ------------------------------------------------------------------ shared steps
    def to_main_screen(self, phone: Phone, log: Logger, max_back: int = 6) -> int | None:
        """Get to the city / world map: close pop-ups, and press Back while the bottom menu isn't showing
        (e.g. a job left a menu or box open). Back is never pressed with the bottom menu visible, so it
        can't reach the game's exit prompt."""
        for i in range(max_back + 1):
            try:
                return self.close_popups(phone, log, timeout=2)
            except ElementNotFound:
                if i == max_back:
                    raise
                log.info("not on the city / world map; pressing Back (%d)", i + 1)
                phone.back()

    def open_game(self, phone: Phone, log: Logger) -> None:
        """The app is launched (runner did that); wait until it has finished loading."""
        t0 = time.monotonic()
        try:   # the loading bar shows up a few seconds after launch (splash first)
            phone.wait_for(text=LOADING, region=LOADING_REGION, timeout=30)
            log.info("loading screen after %.0fs", time.monotonic() - t0)
        except ElementNotFound:
            log.info("no loading bar seen (fast start?)")
        phone.wait_gone(text=LOADING, region=LOADING_REGION, timeout=120)
        phone.wait_stable(region=NAV_REGION, timeout=60, still_for=2)   # bottom menu: event banners animate
        log.info("game loaded after %.0fs", time.monotonic() - t0)

    @staticmethod
    def _wait_gone_quietly(phone: Phone, **target: Any) -> None:
        """After closing a pop-up: wait (up to 3 s) until it has gone, so the same one isn't tapped twice.
        Another pop-up in the same place is fine: the loop handles it next."""
        try:
            phone.wait_gone(timeout=3, **target)
        except PhoneError:
            pass

    def close_popups(self, phone: Phone, log: Logger, max_popups: int = 8, timeout: float = 30) -> int:
        """Close pop-ups until the bottom menu (city or world map) shows with none left:
        offer pop-ups by their X, "Welcome back!" (offline income) by its Confirm button.
        Returns as soon as the menu shows; a pop-up arriving later is handled by tap_on_main().
        (The city is animated, so no wait_stable.) Raises ElementNotFound if nothing known shows."""
        closed = 0
        while self._close_one_popup(phone, log, closed, max_popups, timeout):
            closed += 1
        log.info("closed %d pop-up(s); on the city / world map", closed)
        return closed

    def _close_one_popup(self, phone: Phone, log: Logger, closed: int, max_popups: int, timeout: float,
                         also: dict[str, Any] | None = None) -> bool:
        """Wait for a pop-up, the bottom menu, or `also`; close a pop-up if that's what showed.
        Returns True if a pop-up was closed, False if the menu (or `also`) showed."""
        targets = [{"image": "close_x", "region": POPUP_X_REGION},       # pop-ups first
                   {"image": "close_x_orange", "region": POPUP_X_REGION},  # the same X on an orange sale pop-up
                   {"text": "Welcome back", "region": WELCOME_TITLE},
                   {"text": "Enter Game", "region": RESOURCE_PACK_ENTER},   # after an update (resource pack box)
                   also or {"text": "Backpack", "region": NAV_REGION}]
        try:
            which = phone.wait_any(*targets, timeout=timeout)
        except ElementNotFound:          # nothing known showed: a pop-up with an X of a new colour / size?
            xy = any_close_x(phone.screen())
            if xy is None or closed >= max_popups:
                raise
            log.info("closing pop-up %d (an X found by its shape at %s)", closed + 1, xy)
            phone.tap_xy(*xy)
            time.sleep(1.5)
            return True
        if which == 4:
            return False
        if closed >= max_popups:
            raise RuntimeError(f"still a pop-up after closing {max_popups}; something is off")
        if which in (0, 1):
            m = phone.last_match
            log.info("closing pop-up %d (X at %s, score %.2f)", closed + 1, m.center, m.score)
            phone.tap_xy(*m.center)
            self._wait_gone_quietly(phone, image=m.text, region=POPUP_X_REGION)
        elif which == 3:   # "Resource pack downloading...": always Enter Game (the user's choice, not Download Now)
            log.info("pop-up %d: resource pack -> Enter Game", closed + 1)
            phone.tap_xy(*phone.last_match.center)
            self._wait_gone_quietly(phone, text="Enter Game", region=RESOURCE_PACK_ENTER)
        else:
            log.info("pop-up %d: Welcome back (offline income) -> Confirm", closed + 1)
            phone.tap(text="Confirm", region=WELCOME_CONFIRM, timeout=5)
            self._wait_gone_quietly(phone, text="Welcome back", region=WELCOME_TITLE)
        return True

    def tap_on_main(self, phone: Phone, log: Logger, timeout: float = 15, then: dict[str, Any] | None = None,
                    **target: Any) -> vision.Match:
        """First tap of a job on the city / world map, done straight away (no extra look first).
        If a pop-up turns up instead (they can arrive a moment late), close it, then tap.
        then={text/image, region}: what the tap should open. The game now and then ignores a job's first tap, so
        if that doesn't show within 8 s (and the button is still there) tap once more."""
        closed = 0
        while self._close_one_popup(phone, log, closed, 8, timeout, also=target):
            closed += 1
        m = phone.last_match
        phone.tap_xy(*m.center)
        if then and not phone.exists(**then, timeout=8):
            phone.forget_screen()
            if phone.find(**target):                     # still on the same screen: the tap was ignored
                log.info("first tap ignored; tapping again")
                phone.tap_xy(*m.center)
        return m


def any_close_x(img: Image, min_score: float = 0.78) -> tuple[int, int] | None:
    """A pop-up's close X found by its cross shape alone, whatever its colours: light on dark or dark on light, any
    hue, sizes 0.8-1.25x. Each pixel is compared with its surroundings (brighter / darker than the local average),
    so no colour is assumed. (x, y) or None. Real X buttons score 0.83-0.95, normal screens <= 0.70."""
    part, (ox, oy) = vision.crop(img, POPUP_X_REGION)
    tpl = _contrast_masks(vision.load_template("close_x")[0])[0][6:-6, 6:-6]
    best, at = 0.0, None
    for mask in _contrast_masks(part):
        for scale in (0.8, 0.9, 1.0, 1.1, 1.25):
            t = cv2.resize(tpl, None, fx=scale, fy=scale)
            _, score, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(mask, t, cv2.TM_CCOEFF_NORMED))
            if score > best:
                best, at = score, (ox + x + t.shape[1] // 2, oy + y + t.shape[0] // 2)
    return at if best >= min_score else None


def _contrast_masks(img: Image) -> list[np.ndarray]:
    """[pixels clearly brighter than their surroundings, pixels clearly darker] as 0/255 images."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    local = cv2.blur(g, (45, 45))
    return [((g - local > 15) * 255).astype(np.float32), ((local - g > 15) * 255).astype(np.float32)]
