"""Kingshot job: alliance tech contribution.

Starts on the city screen or world map (bottom menu visible, no pop-up) — game.py's on_open/before_job
open the game and close all pop-ups first.
"""

from __future__ import annotations

import json
import re
import time
from datetime import timedelta
from typing import TYPE_CHECKING

import config
from core import vision
from core.task import job
from core.vision import coloured_share, median_hue
from regions import (
    ALLIANCE_TITLE,
    BOTTOM_MID,
    CONTRIBUTE_ATTEMPTS,
    CONTRIBUTE_RIGHT,
    NAV_Q4,
    Q4_TOP,
    RANKING_BUTTON,
    RANKING_DAILY_TAB,
    RANKING_MY_ROW,
    RANKING_TOP_ROW,
    SCREEN_TITLE,
    TECH_BOX_TITLE,
    TECH_HEADER,
    TECH_STANDING,
)

if TYPE_CHECKING:
    from logging import Logger

    from core.phone import Phone
    from core.vision import Region
    from game import Kingshot

RANKING_FILE = config.LOG_DIR / "alliance_ranking.json"  # rank 1's daily score at the last run
POINTS_PER_ATTEMPT = 120  # before the bonus multiplier: 100, +20% on the alliance's preferred tech
TAP_GAP = 0.4  # seconds between Contribute taps
MAX_ROUNDS = 4  # rounds of taps per run, so it can never loop (normally 1: an attempt may refill meanwhile)


@job()
def alliance_tech_contribution(app: Kingshot, phone: Phone, log: Logger):
    # 1. "Alliance" in the bottom menu (Q4); its 99+ badge may or may not be there, so match the text
    app.tap_on_main(phone, log, text="Alliance", region=NAV_Q4, then={"text": "Alliance", "region": ALLIANCE_TITLE})
    phone.wait_for(text="Alliance", region=ALLIANCE_TITLE, timeout=10)  # Alliance screen's title (top-left)
    log.info("alliance screen open")

    # 2. Tech button (top section of Q4); matched by its book icon + label, not the changing badge
    phone.tap(image="tech_button", region=Q4_TOP, timeout=10)
    phone.wait_for(
        text="Your Rank", region=TECH_HEADER, timeout=10
    )  # tech screen ("Your Ranking: 59"; OCR sometimes drops the g)
    score_before, rank_before = standing(phone)
    log.info("alliance tech screen open; contribution %s, ranking %s", show(score_before), show(rank_before))
    _, daily_before = daily_scores(phone)
    log.info("daily contribution before: me %s", show(daily_before))

    # 3. Covenant-Making node (bottom middle, between Q3 and Q4); matched by its castle art, not the 0/1 count
    phone.tap(image="covenant_making", region=BOTTOM_MID, timeout=10)
    phone.wait_for(text="Covenant-Making", region=TECH_BOX_TITLE, timeout=10)
    log.info("contribution box open")

    # 4. Tap the RIGHT Contribute button (teal, costs bread, "Attempts: 25/25") once per attempt, TAP_GAP apart,
    #    until the attempts are 0. It is tapped exactly as many times as the attempts read (never on a grey
    #    button). !! The LEFT Contribute button (orange) spends GEMS and looks the same in grey, so: search only the
    #    right half of the box, and check the button really is teal before each round of taps.
    m = phone.wait_for(image="contribute_label", region=CONTRIBUTE_RIGHT, timeout=10)
    button = (m.x - 40, m.y - 6, m.x + m.w + 40, m.y + m.h + 70)  # whole button around its label
    cx, cy = (button[0] + button[2]) // 2, (button[1] + button[3]) // 2
    left = first_left = attempts_left(phone)
    log.info("attempts left: %s", left if left is not None else "unreadable")
    for _ in range(MAX_ROUNDS):
        if left == 0:
            break
        img = phone.screen()
        if coloured_share(img, button) < 0.3:
            log.info("Contribute button is grey: no attempts left")
            break
        hue = median_hue(img, button)
        if not 75 <= hue <= 105:
            raise RuntimeError(f"right Contribute button isn't teal (hue {hue:.0f}); not touching it")
        taps = left if left is not None else 1  # attempts unreadable: one tap, then read again
        for _ in range(taps):
            phone.tap_xy(cx, cy, pause=TAP_GAP)
        time.sleep(1)
        phone.forget_screen()
        before, left = left, attempts_left(phone)
        log.info("tapped Contribute (bread) %d time(s): attempts %s -> %s", taps, before, left)
        if left is not None and before is not None and left >= before:
            raise RuntimeError(f"attempts didn't go down ({before} -> {left}); stopping")
    else:
        log.warning("attempts still %s after %d rounds of taps", left, MAX_ROUNDS)

    # 5. close the box (Back) and read the new contribution and ranking on the tech screen
    phone.back()
    phone.wait_for(text="Your Rank", region=TECH_HEADER, timeout=10)
    time.sleep(1)
    phone.forget_screen()
    score, rank = standing(phone)
    log.info("after contributing: contribution %s, ranking %s", show(score), show(rank))
    used = first_left - left if first_left is not None and left is not None else None
    gained_total = score - score_before if score is not None and score_before is not None else None
    if used and score is not None and score_before is not None and score >= score_before:
        gained = score - score_before
        log.info("gained %s from %d attempts (avg x%.2f)", f"{gained:,}", used, gained / (used * POINTS_PER_ATTEMPT))

    # 6. the daily ranking again: my score now, and rank 1's (with its rise since the last run, kept in RANKING_FILE)
    top, daily = daily_scores(phone)
    try:
        last_top = json.loads(RANKING_FILE.read_text()).get("top")
    except (FileNotFoundError, ValueError):
        last_top = None
    log.info(
        "daily contribution after: me %s%s; #1 %s%s",
        show(daily),
        rise(daily, daily_before),
        show(top),
        rise(top, last_top, "since the last run"),
    )
    if (
        gained_total is not None
        and daily is not None
        and daily_before is not None
        and daily - daily_before != gained_total
    ):
        log.warning(
            "daily contribution doesn't add up: %s -> %s, but the total rose by %s",
            show(daily_before),
            show(daily),
            show(gained_total),
        )
    RANKING_FILE.write_text(json.dumps({"top": top}))

    # 7. All attempts are back exactly 250 min after they run out
    return timedelta(minutes=250)


def standing(phone: Phone) -> tuple[int | None, int | None]:
    """(contribution, ranking) from the tech screen's top-right box ("Your Contribution: 39,720",
    "Your Ranking: 19"); None for a number that doesn't read."""
    text = phone.read_text(TECH_STANDING)
    score = re.search(r"Contribution\W*(\d[\d,./ ]*\d|\d)", text)  # OCR reads the comma as "," "." or "/"
    rank = re.search(r"Ranki?n?g?\W*(\d+)", text)
    return (int(re.sub(r"\D", "", score.group(1))) if score else None, int(rank.group(1)) if rank else None)


def show(n: int | None) -> str:
    return f"{n:,}" if n is not None else "?"


def daily_scores(phone: Phone) -> tuple[int | None, int | None]:
    """Tech screen -> Ranking (top right) -> Contribution, Daily: (rank 1's score, my score), then back to the tech
    screen. None for a score that doesn't read."""
    phone.tap_xy(*RANKING_BUTTON)
    phone.wait_for(text="Ranking", region=SCREEN_TITLE, timeout=10)
    phone.tap_xy(*RANKING_DAILY_TAB)
    time.sleep(1.5)
    top, mine = steady_score(phone, RANKING_TOP_ROW), steady_score(phone, RANKING_MY_ROW)
    phone.back()  # Alliance Ranking -> tech screen
    phone.wait_for(text="Your Rank", region=TECH_HEADER, timeout=10)
    return top, mine


def steady_score(phone: Phone, region: Region, tries: int = 6) -> int | None:
    """A row's score once two readings in a row agree: right after the Daily tab opens the list is still loading
    or moving, and a single reading can be wrong ("65" for 0). None if it never settles."""
    last = None
    for _ in range(tries):
        phone.forget_screen()
        now = row_score(phone, region)
        if now is not None and now == last:
            return now
        last = now
        time.sleep(0.7)
    return None


def row_score(phone: Phone, region: Region) -> int | None:
    """The score at the right end of a ranking row (rank 1's row, or my row pinned at the bottom)."""
    numbers = [m for m in vision.ocr_lines(phone.screen(region), region) if re.fullmatch(r"[\d,./]*\d", m.text.strip())]
    score = max(numbers, key=lambda m: m.center[0], default=None)
    return int(re.sub(r"\D", "", score.text)) if score else None


def rise(now: int | None, before: int | None, since: str = "") -> str:
    """ " (+1,320)" (or " (+1,320 since the last run)"); "" if either is unknown or the score went down (the
    daily ranking was reset)."""
    if now is None or before is None or now < before:
        return ""
    return f" (+{now - before:,}{' ' + since if since else ''})"


def attempts_left(phone: Phone) -> int | None:
    """N from "Attempts: N/25" above the bread button, or None if it doesn't read."""
    m = re.search(r"(\d+)\s*/\s*25", phone.read_text(CONTRIBUTE_ATTEMPTS))
    return int(m.group(1)) if m else None
