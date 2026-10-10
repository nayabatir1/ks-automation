"""Town navigation (screens/town.json + templates/town_<name>.png). Day/night is switched off in the game.

After a fresh launch the view is known (Town Center centred), so the bot drags straight to a building using the map,
then finds the building's picture on screen (fast, exact) and centres it if needed. If the picture isn't there or
the position is unknown, a slow "look" drag reads building names (they only show while dragging) to find out where
the view is, then it carries on.

    x, y = go_to_building(phone, log, "Arena", view=app.town_view)   # -> screen point to tap the building
New building: centre it on screen and cut templates/town_<name>.png (building only, no bubbles/labels).
"""
import difflib
import json
import re
import threading
import time
from logging import Logger
from pathlib import Path

import numpy as np

from core import vision
from core.phone import ElementNotFound, Phone

TOWN = {b["name"]: (b["x"], b["y"]) for b in
        json.loads((Path(__file__).parent / "screens/town.json").read_text())["buildings"]}
RATIO = 1.18                   # the view moves ~1.18 x the finger distance
LOOK_PX = 150                  # finger distance of a look (slow, so the names show)
LOOK_MS = 3000
SHOTS = (0.9, 1.5, 2.1)        # when to read names during a look (they fade near its end)
READ_AREA = (0, 0.1, 1, 0.85)  # whole width: names at the screen edges count too
AIM = (540, 1100)              # where to bring a target building's name on screen
LABEL_TO_BUILDING = 140        # the building is this far below its name label
SAFE = (180, 350, 860, 1750)   # only tap a building whose centre is in here: clear of side icons, bars and chat
MAP_AREA = (0, 0.1, 1, 0.85)   # where buildings can be on screen (no top bar / chat / bottom menu)


def snap(text: str) -> str | None:
    """OCR text -> a town building name, or None."""
    t = re.sub(r"[^A-Za-z0-9 ]", "", text).strip().lower().replace(" ", "")
    if len(t) < 4:
        return None
    best, score = None, 0.0
    for name in TOWN:
        r = difflib.SequenceMatcher(None, t, name.lower().replace(" ", "")).ratio()
        if r > score:
            best, score = name, r
    return best if score >= 0.8 else None


def look(phone: Phone, dx: float = -1, dy: float = 0,
         target: str | None = None) -> tuple[dict[str, tuple[int, int]], tuple[float, float]]:
    """Slow drag (finger LOOK_PX towards (dx, dy)) reading names on screenshots taken during it.
    Returns (names, still): {name: (x, y)} from the last screenshot with names (or the first one showing `target`),
    and the view movement still to come after that screenshot (the drag goes on until LOOK_MS)."""
    norm = max(1e-6, (dx * dx + dy * dy) ** 0.5)
    fx, fy = dx / norm * LOOK_PX, dy / norm * LOOK_PX
    sx, sy = 540 - fx / 2, 1000 - fy / 2
    cmd = f"input swipe {int(sx)} {int(sy)} {int(sx + fx)} {int(sy + fy)} {LOOK_MS}"
    t = threading.Thread(target=lambda: phone.shell(cmd, timeout=LOOK_MS / 1000 + 15))
    phone.forget_screen()
    t.start()
    t0 = time.monotonic()
    best, best_at = {}, SHOTS[-1]
    for at in SHOTS:
        time.sleep(max(0.0, at - (time.monotonic() - t0)))
        img = phone.screen()
        names = {}
        for m in vision.ocr_lines(img, READ_AREA):
            name = snap(m.text) if m.score >= 55 else None
            if name and name not in names:
                names[name] = m.center
        if names:
            best, best_at = names, at
        if target in names:
            break                                        # found: no need to read the rest of this look
    t.join()
    phone.forget_screen()
    rest = 1 - best_at * 1000 / LOOK_MS                  # share of the drag after that screenshot
    return best, (-fx * RATIO * rest, -fy * RATIO * rest)


def where(names: dict[str, tuple[int, int]]) -> tuple[float, float] | None:
    """View position (top-left of the screen in town coordinates) from the names on screen, or None."""
    est = [(TOWN[n][0] - x, TOWN[n][1] - y) for n, (x, y) in names.items()]
    if not est:
        return None
    med = np.median(np.array(est), axis=0)
    good = [e for e in est if abs(e[0] - med[0]) < 300 and abs(e[1] - med[1]) < 300]     # drop misreads
    return tuple(np.median(np.array(good), axis=0)) if good else tuple(med)


def drag(phone: Phone, vx: float, vy: float) -> tuple[float, float]:
    """Move the view by about (vx, vy) with one drag, always lifted. The finger stays in the band of the screen
    that has no icons (x 90-990 around y 1000; up to y 500-1500 for vertical moves). Capped at ~1 screen.
    Returns the move actually asked for."""
    fx = max(-900, min(900, -vx / RATIO))
    fy = max(-1000, min(1000, -vy / RATIO))
    sx, sy = 540 - fx / 2, 1000 - fy / 2
    phone.swipe(int(sx), int(sy), int(sx + fx), int(sy + fy), ms=1000)      # slow: glides predictably
    time.sleep(0.5)
    return -fx * RATIO, -fy * RATIO


def template(name: str) -> str:
    return "town_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def find_building(phone: Phone, name: str) -> vision.Match | None:
    """The building's picture on screen right now: vision.Match or None."""
    return vision.find_shape(phone.screen(MAP_AREA), template(name), MAP_AREA, threshold=0.4)   # day or night


def go_to_building(phone: Phone, log: Logger, name: str, view: tuple[float, float] | None = None,
                   tries: int = 6) -> tuple[int, int]:
    """Bring a town building on screen; returns the screen point to tap it. Raises ElementNotFound.

    view: where the view is, if known: (0, 0) right after a fresh launch (Town Center centred)."""
    if name not in TOWN:
        raise ValueError(f"{name!r} is not on the town map (screens/town.json)")
    if not (Path(__file__).parent / f"templates/{template(name)}.png").exists():
        raise ValueError(f"no picture for {name}: cut templates/{template(name)}.png first")
    tx, ty = TOWN[name]
    t0 = time.monotonic()
    for i in range(tries):
        if view is not None:                              # known position: drag straight to the target
            for _ in range(5):
                vx, vy = tx - view[0] - AIM[0], ty - view[1] - AIM[1]
                if abs(vx) < 250 and abs(vy) < 350:
                    break
                mx, my = drag(phone, vx, vy)
                view = (view[0] + mx, view[1] + my)
        m = find_building(phone, name)
        if m:
            x, y = m.center
            if SAFE[0] <= x <= SAFE[2] and SAFE[1] <= y <= SAFE[3]:
                log.info("%s at (%d, %d): %.0fs, %d check(s)", name, x, y, time.monotonic() - t0, i + 1)
                return x, y
            log.info("%s found at (%d, %d), off-centre; centring it", name, x, y)
            drag(phone, x - 540, y - 1170)
            view = None                                   # position now from the picture, not the map
            continue
        # not on screen: find out where we are from the names (slow, only when needed)
        names, still = look(phone, -1, 0)
        seen = where(names)
        if seen is None:
            log.info("%s not on screen and no names read; looking again", name)
            time.sleep(0.5)
            view = None
            continue
        view = (seen[0] + still[0], seen[1] + still[1])
        log.info("%s not on screen; names say the view is at (%d, %d) [%s]", name, view[0], view[1],
                 ", ".join(sorted(names)))
    raise ElementNotFound(f"could not bring {name} on screen in {tries} tries")
