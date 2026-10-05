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

from core.phone import ElementNotFound, PhoneError
from core.task import Task
from regions import (
    LOADING,
    LOADING_REGION,
    NAV_Q4,
    NAV_REGION,
    POPUP_X_REGION,
    SESSION_TAKEN_TEXT,
    WELCOME_CONFIRM,
    WELCOME_TITLE,
)


class Kingshot(Task):
    name = "kingshot"
    package = "com.run.tower.defense"
    jobs_package = "jobs"                # jobs/*.py, one file per job
    town_view = None                     # town view position if known: (0, 0) right after a fresh launch
    reuse_open_app = True                # game already open? use it (on_open checks the screen)
    timeout = 240                 # per job
    open_timeout = 240            # launch + loading + pop-ups
    enabled = True

    # ------------------------------------------------------------------ hooks (runner calls these)
    # launch -> on_open -> [before_job -> job] ... -> close app. Jobs start on the city screen.
    def on_open(self, phone, log):
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

    def before_job(self, phone, log):
        if getattr(self, "_just_opened", False):   # on_open already left us on the city screen
            self._just_opened = False
        else:
            self.to_main_screen(phone, log)          # the previous job may have ended deep in a menu
            self.town_view = None                        # ...and moved the town view
        self.start_view = self.current_view(phone)

    def after_job(self, phone, log):
        """Close the job's pages and go back to the view the job started from: world map or town."""
        self.to_main_screen(phone, log)
        if self.current_view(phone) != self.start_view:
            button, then = ("World", "Town") if self.start_view == "world" else ("Town", "World")
            phone.tap(text=button, region=NAV_Q4, timeout=5)
            phone.wait_for(text=then, region=NAV_Q4, timeout=15)
            self.town_view = None
        log.info("back on the %s", self.start_view)

    @staticmethod
    def current_view(phone):
        """'world' or 'town': the bottom-right button names the other one."""
        return "world" if phone.exists(text="Town", region=NAV_Q4) else "town"

    def session_taken(self, phone):
        """'The account has been logged in on another device.' (Tips box with Contact Us / Reconnect).
        Never tap Reconnect: that would kick the user off their own phone."""
        return phone.exists(text="logged in on another device", region=SESSION_TAKEN_TEXT)

    # ------------------------------------------------------------------ shared steps
    def to_main_screen(self, phone, log, max_back=6):
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

    def open_game(self, phone, log):
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
    def _wait_gone_quietly(phone, **target):
        """After closing a pop-up: wait (up to 3 s) until it has gone, so the same one isn't tapped twice.
        Another pop-up in the same place is fine: the loop handles it next."""
        try:
            phone.wait_gone(timeout=3, **target)
        except PhoneError:
            pass

    def close_popups(self, phone, log, max_popups=8, timeout=30):
        """Close pop-ups until the bottom menu (city or world map) shows with none left:
        offer pop-ups by their X, "Welcome back!" (offline income) by its Confirm button.
        Returns as soon as the menu shows; a pop-up arriving later is handled by tap_on_main().
        (The city is animated, so no wait_stable.) Raises ElementNotFound if nothing known shows."""
        closed = 0
        while self._close_one_popup(phone, log, closed, max_popups, timeout):
            closed += 1
        log.info("closed %d pop-up(s); on the city / world map", closed)
        return closed

    def _close_one_popup(self, phone, log, closed, max_popups, timeout, also=None):
        """Wait for a pop-up, the bottom menu, or `also`; close a pop-up if that's what showed.
        Returns True if a pop-up was closed, False if the menu (or `also`) showed."""
        targets = [{"image": "close_x", "region": POPUP_X_REGION},       # pop-ups first
                   {"text": "Welcome back", "region": WELCOME_TITLE},
                   also or {"text": "Backpack", "region": NAV_REGION}]
        which = phone.wait_any(*targets, timeout=timeout)
        if which == 2:
            return False
        if closed >= max_popups:
            raise RuntimeError(f"still a pop-up after closing {max_popups}; something is off")
        if which == 0:
            m = phone.last_match
            log.info("closing pop-up %d (X at %s, score %.2f)", closed + 1, m.center, m.score)
            phone.tap_xy(*m.center)
            self._wait_gone_quietly(phone, image="close_x", region=POPUP_X_REGION)
        else:
            log.info("pop-up %d: Welcome back (offline income) -> Confirm", closed + 1)
            phone.tap(text="Confirm", region=WELCOME_CONFIRM, timeout=5)
            self._wait_gone_quietly(phone, text="Welcome back", region=WELCOME_TITLE)
        return True

    def tap_on_main(self, phone, log, timeout=15, **target):
        """First tap of a job on the city / world map, done straight away (no extra look first).
        If a pop-up turns up instead (they can arrive a moment late), close it, then tap."""
        closed = 0
        while self._close_one_popup(phone, log, closed, 8, timeout, also=target):
            closed += 1
        m = phone.last_match
        phone.tap_xy(*m.center)
        return m
