"""Talks to the phone with plain adb — nothing is installed on the phone.

Screen is read from screenshots (OCR + template matching, see core/vision.py);
input goes through `adb shell input`.

Device control (used by the runner): wake, unlock, launch, close, sleep.
Screen helpers (used by jobs). Each takes text= OR image=, plus optional region=:
    wait_for, wait_gone, wait_any, exists, find, tap, tap_if_present, scroll_to
Other helpers: tap_xy, hold_xy, swipe, read_text, read_duration, type_text, back, home, key, wait_stable,
               screen, screenshot, save_ocr

    text="About phone"            case-insensitive, also matches inside a longer phrase
    text=re.compile(r"\\d+ coins") regex
    image="claim_button"          templates/claim_button.png (make it with: tools.py crop ...)
    region=(0, 0.8, 1, 1)         only look in the bottom 20% (fractions) ...
    region=(0, 1800, 1080, 2340)  ... or pixels x1, y1, x2, y2
"""
import atexit
import json
import logging
import re
import shlex
import socket
import subprocess
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal, TextIO

import numpy as np

import config
from core import vision
from core.vision import Image, Region, TextTarget

log = logging.getLogger("phone")

KEY_HOME, KEY_BACK, KEY_ENTER, KEY_MENU = 3, 4, 66, 82
KEY_SLEEP, KEY_WAKEUP = 223, 224
REUSE_SECONDS = 1.0       # a screenshot this fresh (and with no input since) may be reused by the next check


class PhoneError(Exception):
    pass


class ElementNotFound(PhoneError):
    pass


def _describe(text: TextTarget | None = None, image: str | None = None, region: Region | None = None) -> str:
    s = f"text={text.pattern if isinstance(text, re.Pattern) else text!r}" if text is not None \
        else f"image={image!r}"
    return s + (f" region={region}" if region else "")


def device_state(serial: str | None = None) -> str:
    """'device' when the phone is connected and authorised; otherwise what adb says
    ('unauthorized', 'offline', 'no devices/emulators found', ...)."""
    cmd = ["adb"] + (["-s", serial] if serial else []) + ["get-state"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=15, check=False)
    except subprocess.TimeoutExpired:
        return "adb not responding"
    out = (r.stdout if r.returncode == 0 else r.stderr).decode(errors="replace").strip()
    return out.removeprefix("error: ") or "no device"


class Phone:
    def __init__(self, serial: str | None = None, pin: str | None = None, launch_timeout: float = 20) -> None:
        self.serial = serial
        self.pin = pin
        self.launch_timeout = launch_timeout
        self._last_screen: Image | None = None   # last screenshot taken (numpy BGR), used for failure reports
        state = device_state(serial)
        if state != "device":
            raise PhoneError(f"Phone not available ({state}). Check `adb devices`: it must "
                             f"say 'device' (not 'unauthorized'/'offline'); replug USB / accept the prompt.")
        if not self.serial:
            self.serial = self._adb("get-serialno").stdout.decode().strip()
        self.width, self.height = self._screen_size()
        self._monkey: TextIO | Literal[False] | None = None   # fast input connection (see tap_xy); False = monkey unusable, use `input`
        self._raw: tuple[int, int, int] | None = None   # (header, w, h) of raw screenshots, once known (for strip screenshots)
        self._shot: tuple[float, int, int] | None = None   # (time, y1, y2) of last_screen, while it still shows the screen
        log.info("Connected to %s (%dx%d)", self.serial, self.width, self.height)

    # ------------------------------------------------------------------ adb
    def _adb(self, *args: str, check: bool = True, timeout: float = 30) -> subprocess.CompletedProcess[bytes]:
        cmd = ["adb"] + (["-s", self.serial] if self.serial else []) + list(args)
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise PhoneError(f"adb timed out after {timeout}s: {' '.join(args)}")
        if check and r.returncode != 0:
            raise PhoneError(f"adb {' '.join(args)} failed: {r.stderr.decode(errors='replace').strip()}")
        return r

    def shell(self, cmd: str, timeout: float = 30) -> str:
        return self._adb("shell", cmd, timeout=timeout).stdout.decode(errors="replace").strip()

    def key(self, code: str | int) -> None:
        self._screen_changed()
        self.shell(f"input keyevent {code}")

    def _screen_size(self):
        out = self.shell("wm size")
        m = re.search(r"Override size: (\d+)x(\d+)", out) or re.search(r"(\d+)x(\d+)", out)
        if not m:
            raise PhoneError(f"Can't read screen size: {out!r}")
        return int(m.group(1)), int(m.group(2))

    # ------------------------------------------------------------------ device
    def is_screen_on(self) -> bool:
        out = self.shell("dumpsys power")
        return "mWakefulness=Awake" in out or "Display Power: state=ON" in out

    def is_locked(self) -> bool:
        out = self.shell("dumpsys window")
        return bool(re.search(r"(mDreamingLockscreen|isKeyguardShowing|mShowingLockscreen)=true", out))

    def wake(self):
        if not self.is_screen_on():
            log.info("Waking screen")
            self.key(KEY_WAKEUP)
            time.sleep(1)
        if self.is_locked():
            self.unlock()

    def unlock(self):
        log.info("Unlocking")
        for attempt in range(3):
            self.swipe(0.5, 0.85, 0.5, 0.25, ms=300)
            time.sleep(1)
            if self.pin:
                self.shell(f"input text {shlex.quote(self.pin)}")
                self.key(KEY_ENTER)
                time.sleep(1.5)
            if not self.is_locked():
                return
            log.warning("Still locked after attempt %d", attempt + 1)
            self.key(KEY_WAKEUP)
        raise PhoneError("Could not unlock the phone (wrong PHONE_PIN, or lock type not supported)")

    def sleep(self):
        log.info("Putting phone to sleep")
        self.key(KEY_HOME)
        if self.is_screen_on():
            self.key(KEY_SLEEP)

    def disable_keyboards(self):
        """Switch off every on-screen keyboard, including voice typing (`ime disable`), so no keyboard can pop
        up over the game. Android or app updates switch them back on now and then, so this runs every
        session. Undo by hand with: adb shell ime enable com.samsung.android.honeyboard/.service.HoneyBoardService"""
        enabled = [line.strip() for line in self.shell("ime list -s").splitlines() if "/" in line]
        for ime in enabled:
            self.shell(f"ime disable {shlex.quote(ime)}")
            log.info("Keyboard was switched on again; disabled it: %s", ime)
        return enabled

    def current_app(self) -> str:
        """Package of the app in the foreground ('' if unknown)."""
        out = self.shell("dumpsys window")
        for key in ("mCurrentFocus", "mFocusedApp"):
            m = re.search(key + r"=.*? u\d+ ([\w.]+)/", out)
            if m:
                return m.group(1)
        return ""

    def packages(self, contains: str = "") -> list[str]:
        out = self.shell("pm list packages")
        return sorted(p[8:] for p in out.splitlines() if p.startswith("package:") and contains in p)

    def launch(self, package: str, activity: str | None = None) -> None:
        """Fresh start: force-stop, start via the launcher intent, wait until it's in front."""
        log.info("Launching %s", package)
        self._screen_changed()
        self.shell(f"am force-stop {package}")
        if activity:
            out = self.shell(f"am start -n {shlex.quote(activity)}")
        else:
            out = self.shell(f"monkey -p {package} -c android.intent.category.LAUNCHER 1")
        if "No activities found" in out or "Error" in out:
            raise PhoneError(f"Could not launch {package}: {out}")
        end = time.time() + self.launch_timeout
        while time.time() < end:
            if self.current_app() == package:
                time.sleep(0.5)
                return
            time.sleep(0.5)
        raise PhoneError(f"{package} did not come to the foreground in {self.launch_timeout}s "
                         f"(foreground: {self.current_app() or 'unknown'})")

    def close(self, package: str) -> None:
        log.info("Closing %s", package)
        self.shell(f"am force-stop {package}")

    # ------------------------------------------------------------------ screen capture
    def screen(self, region: Region | None = None) -> Image:
        """Take a screenshot now; returns an OpenCV BGR image (also kept as self.last_screen).

        With region=, only those rows are sent over USB (~0.3 s instead of ~1.1 s for a full screen);
        everything outside them is black, and coordinates stay full-screen.
        """
        if region is not None and self._raw:
            img = self._screen_rows(region)
            if img is not None:
                _, y1, _, y2 = vision.resolve_region(region, img.shape)
                self._keep(img, y1, y2)
                return img
        raw = self._adb("exec-out", "screencap", timeout=30).stdout   # raw is ~4x faster than -p
        img = None
        if len(raw) >= 12:
            w, h = (int(v) for v in np.frombuffer(raw[:8], "<u4"))
            header = len(raw) - w * h * 4
            if header in (12, 16):
                rgba = np.frombuffer(raw, np.uint8, offset=header).reshape(h, w, 4)
                img = np.ascontiguousarray(rgba[:, :, 2::-1])           # RGBA -> BGR
                self._raw = (header, w, h)
        if img is None:                                                 # unknown format: use PNG
            img = vision.decode_png(self._adb("exec-out", "screencap", "-p", timeout=30).stdout)
        self._keep(img, 0, img.shape[0])
        return img

    def _keep(self, img: Image, y1: int, y2: int) -> None:
        self._last_screen = img
        self._shot = (time.monotonic(), y1, y2)

    def _screen_for(self, region: Region | None, reuse: bool) -> Image:
        """A screenshot covering region: the last one if reuse=True, it's under REUSE_SECONDS old, covers
        those rows and nothing was tapped/swiped since (input clears it); otherwise a new one."""
        if reuse and self._shot:
            taken, y1, y2 = self._shot
            _, ry1, _, ry2 = vision.resolve_region(region, (self.height, self.width))
            if self._last_screen is not None and time.monotonic() - taken < REUSE_SECONDS and y1 <= ry1 and ry2 <= y2:
                return self._last_screen
        return self.screen(region)

    @property
    def last_screen(self) -> Image:
        """The last screenshot taken (what the last find / wait_for looked at); a new one if there's none yet."""
        return self._last_screen if self._last_screen is not None else self.screen()

    def forget_screen(self):
        """The next check takes a new screenshot (every input action does this by itself)."""
        self._shot = None

    _screen_changed = forget_screen

    def _screen_rows(self, region: Region | None) -> Image | None:
        if self._raw is None:
            return None
        header, w, h = self._raw
        _, y1, _, y2 = vision.resolve_region(region, (h, w))
        row = w * 4
        cmd = f"screencap | tail -c +{header + y1 * row + 1} | head -c {(y2 - y1) * row}"
        raw = self._adb("exec-out", cmd, timeout=30).stdout
        if len(raw) != (y2 - y1) * row:
            return None                                                 # odd size (rotated?): full screenshot
        img = np.zeros((h, w, 3), np.uint8)
        img[y1:y2] = np.frombuffer(raw, np.uint8).reshape(y2 - y1, w, 4)[:, :, 2::-1]
        return img

    def _rows_for(self, regions: list[Region | None]) -> Region | None:
        """One area covering all these regions (for a single strip screenshot); None = full screen."""
        if any(r is None for r in regions):
            return None
        boxes = [vision.resolve_region(r, (self.height, self.width)) for r in regions]
        return 0, min(b[1] for b in boxes), self.width, max(b[3] for b in boxes)

    def screenshot(self, path: str | Path) -> None:
        import cv2
        cv2.imwrite(str(path), self.screen())

    def save_ocr(self, path: Path, img: Image | None = None) -> None:
        """Write every piece of text on screen with its coordinates to a text file."""
        img = self._last_screen if img is None else img
        lines = vision.ocr_lines(img if img is not None else self.screen())
        path.write_text("\n".join(str(m) for m in lines) + "\n")

    # ------------------------------------------------------------------ finding things
    def _locate(self, img: Image, text: TextTarget | None = None, image: str | None = None,
                region: Region | None = None) -> vision.Match | None:
        if (text is None) == (image is None):
            raise ValueError("pass exactly one of text= or image=")
        if text is not None:
            return vision.find_text(img, text, region)
        assert image is not None
        return vision.find_image(img, image, region)

    def find(self, text: TextTarget | None = None, image: str | None = None, region: Region | None = None,
             reuse: bool = False) -> vision.Match | None:
        """Look once. Returns a vision.Match (with .center) or None. reuse=True may use a screenshot from
        just now (see _screen_for) instead of taking a new one."""
        return self._locate(self._screen_for(region, reuse), text, image, region)

    def exists(self, text: TextTarget | None = None, image: str | None = None, region: Region | None = None,
               timeout: float = 0) -> bool:
        try:
            self.wait_for(text=text, image=image, region=region, timeout=timeout)
            return True
        except ElementNotFound:
            return False

    def wait_for(self, text: TextTarget | None = None, image: str | None = None, region: Region | None = None,
                 timeout: float = 15) -> vision.Match:
        """Wait until it appears; returns the Match. Raises ElementNotFound."""
        end, first = time.time() + timeout, True
        while True:
            m = self.find(text, image, region, reuse=first)
            first = False
            if m:
                log.debug("Found %s at %s", _describe(text, image, region), m.center)
                return m
            if time.time() >= end:
                raise ElementNotFound(f"Not found after {timeout}s: {_describe(text, image, region)}")
            time.sleep(config.POLL_INTERVAL)

    def wait_gone(self, text: TextTarget | None = None, image: str | None = None, region: Region | None = None,
                  timeout: float = 30) -> None:
        """Wait until it disappears (e.g. a 'Loading' label)."""
        end, first = time.time() + timeout, True
        while self.find(text, image, region, reuse=first):
            first = False
            if time.time() >= end:
                raise PhoneError(f"Still visible after {timeout}s: {_describe(text, image, region)}")
            time.sleep(config.POLL_INTERVAL)

    def wait_any(self, *targets: dict[str, Any], timeout: float = 15) -> int:
        """Wait until any of several things appears. Returns the index of the one found.

        idx = phone.wait_any({"text": "Home"}, {"image": "login_btn", "region": (0, .5, 1, 1)})
        The Match is available afterwards as phone.last_match.
        """
        end, first = time.time() + timeout, True
        while True:
            img = self._screen_for(self._rows_for([t.get("region") for t in targets]), reuse=first)
            first = False
            for i, t in enumerate(targets):
                m = self._locate(img, **t)
                if m:
                    self.last_match = m
                    return i
            if time.time() >= end:
                raise ElementNotFound(f"None of {[_describe(**t) for t in targets]} appeared within {timeout}s")
            time.sleep(config.POLL_INTERVAL)

    # ------------------------------------------------------------------ input
    def _xy(self, x: float, y: float) -> tuple[int, int]:
        """Pixels, or fractions of the screen if both are floats <= 1."""
        if isinstance(x, float) and isinstance(y, float) and x <= 1 and y <= 1:
            return int(x * self.width), int(y * self.height)
        return int(x), int(y)

    # Input goes through Android's built-in `monkey` in command mode (`monkey --port`): started once, then
    # each tap is a line over a socket (~0.06 s). Plain `input tap` starts a Java process per tap (~1 s);
    # it's the fallback if monkey can't be used. Nothing is installed on the phone.
    def _monkey_cmd(self, line: str) -> bool:
        """Send one command to monkey; returns False (and switches to `input`) if monkey isn't usable."""
        if self._monkey is False:
            return False
        try:
            if self._monkey is None:
                self._start_monkey()
            if not self._monkey_cmd_raw(line):
                raise OSError(f"monkey said no to {line!r}")
            return True
        except (OSError, PhoneError) as e:
            log.warning("fast input (monkey) not available, using `input` instead: %s", e)
            self.close_input()
            self._monkey = False
            return False

    def _start_monkey(self):
        port = config.MONKEY_PORT
        self._adb("shell", "for p in $(pidof com.android.commands.monkey); do kill $p; done",
                  check=False)                                          # a leftover from a crashed run
        self._monkey_proc = subprocess.Popen(
            ["adb"] + (["-s", self.serial] if self.serial else []) + ["shell", "monkey", "--port", str(port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._adb("forward", f"tcp:{port}", f"tcp:{port}")
        end = time.time() + 10
        while True:                                                         # monkey takes ~1.5 s to start
            try:
                sock = socket.create_connection(("127.0.0.1", port), timeout=10)
                self._monkey = sock.makefile("rw")
                self._monkey_sock = sock
                if self._monkey_cmd_raw("wake"):
                    atexit.register(self.close_input)            # never leave monkey running on the phone
                    return
            except OSError:
                pass
            if time.time() > end:
                raise OSError("monkey did not start")
            time.sleep(0.3)

    def _monkey_cmd_raw(self, line: str) -> bool:
        if not self._monkey:
            raise OSError("monkey is not connected")
        self._monkey.write(line + "\n")
        self._monkey.flush()
        return self._monkey.readline().strip() == "OK"

    def close_input(self):
        """Stop monkey (call at the end of a run). Safe to call more than once."""
        if self._monkey:
            try:
                self._monkey_cmd_raw("quit")
            except OSError:
                pass
        for attr in ("_monkey_sock",):
            sock = getattr(self, attr, None)
            if sock:
                sock.close()
        proc = getattr(self, "_monkey_proc", None)
        if proc:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            self._adb("forward", "--remove", f"tcp:{config.MONKEY_PORT}", check=False)
        self._monkey, self._monkey_sock, self._monkey_proc = None, None, None

    def start_input(self):
        """Get fast input ready now (e.g. while an app loads) instead of at the first tap."""
        self._monkey_cmd("wake")

    def tap_xy(self, x: float, y: float, pause: float = 0.3) -> None:
        self._screen_changed()
        x, y = self._xy(x, y)
        log.debug("tap %d,%d", x, y)
        if not self._monkey_cmd(f"tap {x} {y}"):
            self.shell(f"input tap {x} {y}")
        time.sleep(pause)

    def tap(self, text: TextTarget | None = None, image: str | None = None, region: Region | None = None,
            timeout: float = 10, offset: tuple[int, int] = (0, 0), pause: float = 0.3) -> vision.Match:
        """Wait for it, then tap its centre (+ offset pixels). Returns the Match."""
        m = self.wait_for(text, image, region, timeout)
        cx, cy = m.center
        self.tap_xy(cx + offset[0], cy + offset[1], pause)
        return m

    def tap_if_present(self, text: TextTarget | None = None, image: str | None = None, region: Region | None = None,
                       timeout: float = 2) -> bool:
        """Tap it if it shows up (handy for random pop-ups). Returns True if tapped."""
        try:
            self.tap(text, image, region, timeout)
            return True
        except ElementNotFound:
            return False

    def hold_xy(self, x: float, y: float, seconds: float) -> None:
        """Press and hold at a point (long press) for this many seconds."""
        self._screen_changed()
        x, y = self._xy(x, y)
        log.debug("hold %d,%d for %ss", x, y, seconds)
        if self._monkey_cmd(f"touch down {x} {y}"):
            try:
                time.sleep(seconds)
            finally:
                self._monkey_cmd(f"touch up {x} {y}")      # always lift the finger, even on a timeout
        else:
            self.shell(f"input swipe {x} {y} {x} {y} {int(seconds * 1000)}", timeout=seconds + 15)

    def swipe(self, x1: float, y1: float, x2: float, y2: float, ms: int = 300) -> None:
        # `input swipe`, not monkey: monkey's step-by-step "touch move" doesn't drag Unity lists.
        self._screen_changed()
        x1, y1 = self._xy(x1, y1)
        x2, y2 = self._xy(x2, y2)
        self.shell(f"input swipe {x1} {y1} {x2} {y2} {int(ms)}")

    def scroll_to(self, text: TextTarget | None = None, image: str | None = None, region: Region | None = None,
                  direction: str = "down", max_swipes: int = 10, ms: int = 400) -> vision.Match:
        """Swipe through a list until it's visible; returns the Match. With region=, both the search
        and the swipes stay inside that area (e.g. a panel over an animated map).

        Remembers how many swipes it took (scroll_memory.json): next time it does that many straight
        away without looking in between, then carries on one swipe at a time if needed. Stops when the
        list stops moving (its end)."""
        x1, y1, x2, y2 = vision.resolve_region(region, (self.height, self.width))
        cx, top, bottom = (x1 + x2) // 2, y1 + (y2 - y1) // 5, y1 + (y2 - y1) * 4 // 5
        start, finish = (bottom, top) if direction == "down" else (top, bottom)
        key = f"{direction}:{_describe(text, image, region)}"
        memory = self._scroll_memory()

        def swipe():
            self.swipe(cx, start, cx, finish, ms=ms)

        swipes, prev = 0, None
        img = self.screen(region)
        m = self._locate(img, text, image, region)
        if not m and memory.get(key):
            for _ in range(memory[key]):                  # the usual distance, in one go
                swipe()
            swipes = memory[key]
            time.sleep(0.4)
            img = self.screen(region)
            m = self._locate(img, text, image, region)
        while not m and swipes < max_swipes:
            if prev is not None and vision.screen_diff(prev, img, region) < 1.0:
                break                                     # list didn't move: end of the list
            prev = img
            swipe()
            swipes += 1
            time.sleep(0.4)                               # let the list settle
            img = self.screen(region)
            m = self._locate(img, text, image, region)
        if not m:
            raise ElementNotFound(f"Scrolled {direction} but did not find {_describe(text, image, region)}")
        if memory.get(key) != swipes:
            memory[key] = swipes
            config.SCROLL_MEMORY_FILE.write_text(json.dumps(memory, indent=2))
        log.debug("found %s after %d swipe(s)", _describe(text, image, region), swipes)
        return m

    def _scroll_memory(self):
        try:
            return json.loads(config.SCROLL_MEMORY_FILE.read_text())
        except (FileNotFoundError, ValueError):
            return {}

    def type_text(self, text: str) -> None:
        """Type into the focused field (ASCII only; spaces are fine)."""
        self.shell("input text " + shlex.quote(text.replace(" ", "%s")))

    def back(self, times: int = 1) -> None:
        self._screen_changed()
        for _ in range(times):
            if not self._monkey_cmd("press KEYCODE_BACK"):
                self.key(KEY_BACK)
            time.sleep(0.4)

    def home(self):
        self.key(KEY_HOME)

    # ------------------------------------------------------------------ reading
    def read_text(self, region: Region | None = None) -> str:
        """All text on screen (or in region), one line per row."""
        return "\n".join(m.text for m in vision.ocr_lines(self.screen(region), region))

    def read_duration(self, region: Region | None = None, two_part: str = "ms") -> timedelta | None:
        """Read a countdown like '03:12:45' or '2h 5m' from the screen -> timedelta, or None.
        Two-part clocks are mm:ss unless two_part="hm"."""
        from core.timeparse import parse_duration
        text = self.read_text(region)
        d = parse_duration(text, two_part)
        log.debug("read_duration %r -> %s", text, d)
        return d

    def wait_stable(self, region: Region | None = None, timeout: float = 15, still_for: float = 1.0,
                    tolerance: float = 1.5) -> None:
        """Wait until the screen (or region) stops changing for `still_for` seconds."""
        end = time.time() + timeout
        prev = self.screen(region)
        still_since = time.time()
        while True:
            time.sleep(config.POLL_INTERVAL)
            cur = self.screen(region)
            if vision.screen_diff(prev, cur, region) > tolerance:
                still_since = time.time()
            elif time.time() - still_since >= still_for:
                return
            prev = cur
            if time.time() >= end:
                raise PhoneError(f"Screen still changing after {timeout}s" + (f" in {region}" if region else ""))
