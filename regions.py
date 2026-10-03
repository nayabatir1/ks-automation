"""Screen areas (fractions of the screen: x1, y1, x2, y2) and texts shared by all Kingshot jobs."""
import re

Q1, Q2 = (0.5, 0, 1, 0.5), (0, 0, 0.5, 0.5)
Q3, Q4 = (0, 0.5, 0.5, 1), (0.5, 0.5, 1, 1)
Q4_TOP = (0.5, 0.5, 1, 0.75)                    # top section of Q4
BOTTOM_MID = (0.25, 0.75, 0.75, 1)              # bottom part, between Q3 and Q4

LOADING = re.compile(r"MB|\d\s*%")              # bottom progress text on the loading screen
LOADING_REGION = (0, 0.88, 1, 0.97)
POPUP_X_REGION = Q1                             # pop-up close X
WELCOME_TITLE = (0, 0.2, 1, 0.35)               # "Welcome back!" offline-income pop-up title
WELCOME_CONFIRM = (0.15, 0.7, 0.85, 0.85)       # ...its green Confirm button
NAV_REGION = (0, 0.95, 1, 1)                    # bottom menu: Conquest Heroes Backpack Shop Alliance World/Town
NAV_Q4 = (0.5, 0.95, 1, 1)                      # ...its Q4 half: Shop Alliance World/Town
NAV_Q3 = (0, 0.95, 0.5, 1)                      # ...its Q3 half: Conquest Heroes Backpack
LEFT_MID = (0, 0.33, 0.25, 0.67)                # left edge, middle third of the height
SIDE_PANEL = (0, 0.25, 0.65, 0.7)               # the panel the side tab opens (left side)
CHEST_TIMER = (0.2, 0.78, 0.8, 0.88)            # online rewards: "Next Chest Ready In:" + countdown
BLANK_SPOT = (0.5, 0.12)                        # tap here to close a reward screen (dimmed area, no buttons)
SESSION_TAKEN_TEXT = (0, 0.4, 1, 0.65)          # "The account has been logged in on another device." box
ALLIANCE_TITLE = (0, 0.04, 0.5, 0.1)            # "Alliance" title of the Alliance screen (next to the back arrow)
TECH_HEADER = (0, 0.1, 1, 0.2)                  # alliance tech screen: "Your Contribution" / "Your Ranking"
TECH_BOX_TITLE = (0.1, 0.21, 0.9, 0.27)          # title of a tech's contribution box, e.g. "Covenant-Making"
CONTRIBUTE_RIGHT = (0.5, 0.72, 0.95, 0.82)       # contribution box: RIGHT (bread) Contribute button only
NEXT_ATTEMPT = (0.05, 0.81, 0.95, 0.86)          # under the contribution box: "New Contribution attempt in 00:09:53"
CONQUER_BUTTON = (0.2, 0.9, 0.8, 0.97)          # conquest screen: big "Conquer" button at the bottom
CHEST_CLAIM = (0.65, 0.72, 1, 0.8)              # conquest screen: the chest's green "Claim" button
IDLE_BOX_TOP = (0.1, 0.27, 0.9, 0.4)            # conquest "Idle Income" box: title + "Idle Time 09:00:00 (Max)"
IDLE_CLAIM = (0.15, 0.66, 0.85, 0.75)           # ...its big green "Claim" button
