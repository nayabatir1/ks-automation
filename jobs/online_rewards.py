"""Kingshot job: online rewards.

Starts on the city screen or world map (bottom menu visible, no pop-up) — game.py's on_open/before_job
see to that.
"""
import time
from datetime import timedelta

from core.phone import ElementNotFound
from core.schedule import utcnow
from core.task import job
from regions import BLANK_SPOT, CHEST_TIMER, LEFT_MID, NAV_REGION, Q4, SIDE_PANEL

NO_REWARD_RETRY = timedelta(minutes=30)


def no_reward_yet(app, log):
    """No chest ready: keep the chest time we already know if it's still ahead, else look again later."""
    known = app.previous_next_at
    if known and known > utcnow():
        log.info("no online reward ready yet; keeping the known chest time")
        return known
    log.info("no online reward ready yet; checking again in %s", NO_REWARD_RETRY)
    return NO_REWARD_RETRY


@job()
def online_rewards(app, phone, log):
    # 1. World button (Q4) -> world map; the button then reads "Town". Skip if already there.
    if phone.exists(text="Town", region=NAV_REGION):
        log.info("already on the world map")
    else:
        app.tap_on_main(phone, log, image="world_icon", region=Q4)
        phone.wait_for(text="Town", region=NAV_REGION, timeout=15)
        log.info("on the world map")

    # 2. side tab ">" on the left edge, middle of the screen -> side panel (header tabs Town / Wilderness).
    #    Skip if the panel is already open (the tab is hidden then).
    if phone.wait_any({"text": "Wilderness", "region": SIDE_PANEL},
                      {"image": "side_tab", "region": LEFT_MID}, timeout=10) == 0:
        log.info("side panel already open")
    else:
        phone.tap(image="side_tab", region=LEFT_MID, timeout=5)
        phone.wait_for(text="Wilderness", region=SIDE_PANEL, timeout=10)
        log.info("side panel open")

    # 3. "Online Rewards" sits just above "Water Essence Gathering", and is only there while a chest is ready.
    #    So: scroll to Water Essence (always there), then look in the space above it.
    try:
        water = phone.scroll_to(text="Water Essence", region=SIDE_PANEL, max_swipes=8)
    except ElementNotFound:          # panel was left scrolled further down
        water = phone.scroll_to(text="Water Essence", region=SIDE_PANEL, direction="up", max_swipes=8)
    panel_top = int(SIDE_PANEL[1] * phone.height)
    if water.y - panel_top < 300:    # too close to the top: the space above it is cut off, show a bit more
        phone.swipe(water.center[0], water.y, water.center[0], water.y + 300, ms=400)
        time.sleep(0.4)
        water = phone.wait_for(text="Water Essence", region=SIDE_PANEL, timeout=5)
    above_water = (SIDE_PANEL[0], SIDE_PANEL[1], SIDE_PANEL[2], water.y / phone.height)
    m = phone.find(text="Online Rewards", region=above_water)
    if not m:
        return no_reward_yet(app, log)
    log.info("found Online Rewards at %s", m.center)

    # 4. tap the Online Rewards box -> chest screen with "Next Chest Ready In: 00:00:27"
    phone.tap_xy(*m.center)
    phone.wait_for(text="Next Chest Ready", region=CHEST_TIMER, timeout=10)
    log.info("online rewards screen open")

    # 5. record when the next chest is ready, then tap a blank spot to close the chest screen
    wait = phone.read_duration(region=CHEST_TIMER)
    if wait is None:
        raise RuntimeError("could not read the 'Next Chest Ready In' countdown")
    log.info("next chest in %s", wait)
    phone.tap_xy(*BLANK_SPOT)
    phone.wait_gone(text="Next Chest Ready", region=CHEST_TIMER, timeout=10)
    return wait + timedelta(seconds=10)      # a little after it's ready
