"""Kingshot job: alliance tech contribution.

Starts on the city screen or world map (bottom menu visible, no pop-up) — game.py's on_open/before_job
open the game and close all pop-ups first.
"""
from datetime import timedelta

from core.task import job
from core.vision import coloured_share, median_hue
from regions import (
    ALLIANCE_TITLE,
    BOTTOM_MID,
    CONTRIBUTE_RIGHT,
    NAV_Q4,
    Q4_TOP,
    TECH_BOX_TITLE,
    TECH_HEADER,
)


@job()
def alliance_tech_contribution(app, phone, log):
    # 1. "Alliance" in the bottom menu (Q4); its 99+ badge may or may not be there, so match the text
    app.tap_on_main(phone, log, text="Alliance", region=NAV_Q4, then={"text": "Alliance", "region": ALLIANCE_TITLE})
    phone.wait_for(text="Alliance", region=ALLIANCE_TITLE, timeout=10)   # Alliance screen's title (top-left)
    log.info("alliance screen open")

    # 2. Tech button (top section of Q4); matched by its book icon + label, not the changing badge
    phone.tap(image="tech_button", region=Q4_TOP, timeout=10)
    phone.wait_for(text="Your Rank", region=TECH_HEADER, timeout=10)  # tech screen ("Your Ranking: 59"; OCR sometimes drops the g)
    log.info("alliance tech screen open")

    # 3. Covenant-Making node (bottom middle, between Q3 and Q4); matched by its castle art, not the 0/1 count
    phone.tap(image="covenant_making", region=BOTTOM_MID, timeout=10)
    phone.wait_for(text="Covenant-Making", region=TECH_BOX_TITLE, timeout=10)
    log.info("contribution box open")

    # 4. Hold the RIGHT Contribute button (teal, costs bread, "Attempts: 25/25") for 5 s; it greys out when done.
    #    !! The LEFT Contribute button (orange) spends GEMS and looks the same in grey, so: search only the
    #    right half of the box, and check the button really is teal before touching it.
    m = phone.wait_for(image="contribute_label", region=CONTRIBUTE_RIGHT, timeout=10)
    button = (m.x - 40, m.y - 6, m.x + m.w + 40, m.y + m.h + 70)       # whole button around its label
    img = phone.last_screen
    if coloured_share(img, button) < 0.3:
        log.info("Contribute button is grey: no attempts left, nothing to hold")
    else:
        hue = median_hue(img, button)
        if not 75 <= hue <= 105:
            raise RuntimeError(f"right Contribute button isn't teal (hue {hue:.0f}); not touching it")
        cx, cy = (button[0] + button[2]) // 2, (button[1] + button[3]) // 2
        phone.hold_xy(cx, cy, seconds=5)
        log.info("held Contribute (bread) for 5 s")

    # 5. All attempts are back exactly 250 min after they run out
    return timedelta(minutes=250)
