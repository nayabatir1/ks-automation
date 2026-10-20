"""Kingshot job: alliance tech contribution.

Starts on the city screen or world map (bottom menu visible, no pop-up) — game.py's on_open/before_job
open the game and close all pop-ups first.
"""

from __future__ import annotations

import re
import time
from datetime import timedelta
from typing import TYPE_CHECKING

from core.task import job
from core.vision import coloured_share, median_hue
from regions import (
    ALLIANCE_TITLE,
    BOTTOM_MID,
    CONTRIBUTE_ATTEMPTS,
    CONTRIBUTE_RIGHT,
    NAV_Q4,
    Q4_TOP,
    TECH_BOX_TITLE,
    TECH_HEADER,
    TECH_STANDING,
)

if TYPE_CHECKING:
    from logging import Logger

    from core.phone import Phone
    from game import Kingshot

MAX_HOLDS = 6  # per run, so it can never loop (one 5 s hold used all 24 attempts on 2026-10-20)


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
    log.info("alliance tech screen open; %s", standing(phone))

    # 3. Covenant-Making node (bottom middle, between Q3 and Q4); matched by its castle art, not the 0/1 count
    phone.tap(image="covenant_making", region=BOTTOM_MID, timeout=10)
    phone.wait_for(text="Covenant-Making", region=TECH_BOX_TITLE, timeout=10)
    log.info("contribution box open")

    # 4. Hold the RIGHT Contribute button (teal, costs bread, "Attempts: 25/25") until the attempts are 0: one hold
    #    may not use them all. !! The LEFT Contribute button (orange) spends GEMS and looks the same in grey, so:
    #    search only the right half of the box, and check the button really is teal before touching it.
    m = phone.wait_for(image="contribute_label", region=CONTRIBUTE_RIGHT, timeout=10)
    button = (m.x - 40, m.y - 6, m.x + m.w + 40, m.y + m.h + 70)  # whole button around its label
    cx, cy = (button[0] + button[2]) // 2, (button[1] + button[3]) // 2
    left = attempts_left(phone)
    log.info("attempts left: %s", left if left is not None else "unreadable")
    for _ in range(MAX_HOLDS):
        if left == 0:
            break
        img = phone.screen()
        if coloured_share(img, button) < 0.3:
            log.info("Contribute button is grey: no attempts left")
            break
        hue = median_hue(img, button)
        if not 75 <= hue <= 105:
            raise RuntimeError(f"right Contribute button isn't teal (hue {hue:.0f}); not touching it")
        phone.hold_xy(cx, cy, seconds=5)
        time.sleep(1)
        phone.forget_screen()
        before, left = left, attempts_left(phone)
        log.info("held Contribute (bread) for 5 s: attempts %s -> %s", before, left)
        if left is not None and before is not None and left >= before:
            raise RuntimeError(f"attempts didn't go down ({before} -> {left}); stopping")
    else:
        log.warning("attempts still %s after %d holds", left, MAX_HOLDS)

    # 5. close the box (Back) and read the new contribution and ranking on the tech screen
    phone.back()
    phone.wait_for(text="Your Rank", region=TECH_HEADER, timeout=10)
    time.sleep(1)
    phone.forget_screen()
    log.info("after contributing: %s", standing(phone))

    # 6. All attempts are back exactly 250 min after they run out
    return timedelta(minutes=250)


def standing(phone: Phone) -> str:
    """ "contribution 39,720, ranking 19" from the tech screen's top-right box ("Your Contribution: 39,720",
    "Your Ranking: 19"); "?" for a number that doesn't read."""
    text = phone.read_text(TECH_STANDING)
    score = re.search(r"Contribution\W*(\d[\d,./ ]*\d|\d)", text)  # OCR reads the comma as "," "." or "/"
    rank = re.search(r"Ranki?n?g?\W*(\d+)", text)
    points = f"{int(re.sub(r'\D', '', score.group(1))):,}" if score else "?"
    return f"contribution {points}, ranking {rank.group(1) if rank else '?'}"


def attempts_left(phone: Phone) -> int | None:
    """N from "Attempts: N/25" above the bread button, or None if it doesn't read."""
    m = re.search(r"(\d+)\s*/\s*25", phone.read_text(CONTRIBUTE_ATTEMPTS))
    return int(m.group(1)) if m else None
