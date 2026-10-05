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
PANEL_TAB = (0.5, 0.38, 0.8, 0.56)              # the open panel's "<" tab (right edge of the panel)
CHEST_TIMER = (0.2, 0.78, 0.8, 0.88)            # online rewards: "Next Chest Ready In:" + countdown
BLANK_SPOT = (0.5, 0.12)                        # tap here to close a reward screen (dimmed area, no buttons)
SESSION_TAKEN_TEXT = (0, 0.4, 1, 0.65)          # "The account has been logged in on another device." box
ALLIANCE_TITLE = (0, 0.04, 0.5, 0.1)            # "Alliance" title of the Alliance screen (next to the back arrow)
TECH_HEADER = (0, 0.1, 1, 0.2)                  # alliance tech screen: "Your Contribution" / "Your Ranking"
TECH_BOX_TITLE = (0.1, 0.21, 0.9, 0.27)          # title of a tech's contribution box, e.g. "Covenant-Making"
CONTRIBUTE_RIGHT = (0.5, 0.72, 0.95, 0.82)       # contribution box: RIGHT (bread) Contribute button only
CONQUER_BUTTON = (0.2, 0.9, 0.8, 0.97)          # conquest screen: big "Conquer" button at the bottom
CHEST_CLAIM = (0.65, 0.72, 1, 0.8)              # conquest screen: the chest's green "Claim" button
IDLE_BOX_TOP = (0.1, 0.27, 0.9, 0.4)            # conquest "Idle Income" box: title + "Idle Time 09:00:00 (Max)"
IDLE_CLAIM = (0.15, 0.66, 0.85, 0.75)           # ...its big green "Claim" button
ARENA_MY_ROW = (0, 0.83, 1, 0.91)               # Arena of Glory: your own row above Challenge (rank ... points)
ARENA_CHALLENGE = (0.25, 0.92, 0.75, 0.99)      # Arena of Glory: the big teal "Challenge" button (red count badge)
DAILY_CHALLENGES = (0.15, 0.71, 0.85, 0.76)     # Challenge List: "Daily challenges: N" (+ next to it = gems: never)
FREE_REFRESH = (0.25, 0.76, 0.75, 0.81)         # Challenge List: green "Free Refresh" button
HEROES_TITLE = (0, 0.04, 0.5, 0.09)            # Heroes screen: "Heroes" next to the back arrow
RECRUIT_BUTTON = (0.4, 0.92, 1, 1)              # Heroes screen: "Recruit Heroes" (bottom right; "Drill Camp" left)
RECRUIT_TITLE = (0.5, 0.13, 1, 0.19)            # "Hero Recruitment" title, its second line
ADVANCED_TIMER = (0.05, 0.675, 0.5, 0.698)      # Hero Recruitment, Advanced: "Next free: 00:04:25" (or "Daily free recruitments: 5")
ADVANCED_X1 = (0.05, 0.70, 0.47, 0.75)          # ...its left button: green "Recruit x1 / Free", else orange (keys: never)
EPIC_TIMER = (0.08, 0.908, 0.45, 0.925)         # Epic: "Next free: 1d 07:59:52"
EPIC_X1 = (0.05, 0.927, 0.47, 0.975)            # ...its left button, same as Advanced
GEMS_SHOP = (0.75, 0.03, 1, 0.1)                # Q1 top: cart + gems button (the count changes; matched by the cart picture)
TOPUP_TITLE = (0.1, 0.04, 0.6, 0.09)            # "Top-up Center" (real-money shop: never tap a ₹ price / TOP UP)
SHOP_TAB_DOTS = (0, 0.1, 1, 0.13)               # Top-up Center tab row: red dot at each tab's top right = something free
SHOP_TAB_ROW_Y = 330                            # y to tap / swipe the tab row (icons + names, above the content)
SHOP_FREE_AREA = (0, 0.14, 1, 0.35)             # content header: the free chest ("Claimable" / "Free"), above any ₹ button
VIP_BADGE = (0.75, 0.07, 1, 0.12)               # Q1: orange V badge before "VIP 9" (the number changes; templates/vip_badge.png)
VIP_TITLE = (0.1, 0.04, 0.4, 0.09)              # VIP screen title "VIP"
VIP_XP_CHEST = (0.65, 0.17, 1, 0.24)            # VIP screen: daily sign-in VIP XP chest (under Shop); red dot = claimable
VIP_BUNDLE_CLAIM = (0.6, 0.66, 0.95, 0.74)      # VIP screen: "VIP N Daily Free Bundle" green Claim (Special Pack below = ₹: never)
POPUP_CONTINUE = (0.1, 0.9, 0.9, 0.97)          # reward pop-ups: "Click to continue" / "Tap anywhere to exit"
DEALS_LABEL = (0.85, 0.2, 1, 0.25)              # Q1: "Deals" under its gift icon
SCREEN_TITLE = (0.1, 0.04, 0.6, 0.09)           # title next to the back arrow ("VIP", "Deals", ...)
TAB_NAMES = (0, 0.12, 1, 0.17)                  # Top-up Center / Deals: tab names under the tab pictures
FREE_COLUMN = (40, 880, 420, 2300)              # Deals > Sign-in & Earn It / Hero Rally: the "Free" column (pixels)
TAB_TITLE = (0, 0.175, 0.7, 0.22)              # Top-up Center / Deals: big title of the open tab (its tab shows no name)
SHOP_NAV = (0.5, 0.95, 0.65, 1)                 # bottom menu: "Shop"
SHOP_BOTTOM_TABS = (0, 0.93, 1, 1)              # Shop: bottom tabs Nomadic Merchant / Mystery / Arena / VIP...
MERCHANT_TIMER = (0.6, 0.14, 1, 0.2)            # Nomadic Merchant: "Refreshes in: 03:42:39"
MERCHANT_REFRESH = (0.6, 0.19, 1, 0.24)         # ...green "Free Refresh" (costs gems once the free ones are used: never)
MERCHANT_PRICES = [(x, y) for y in (1095, 1529) for x in (192, 540, 888)]   # centres of the 6 price bars (pixels)
COMPASS_BUTTON = (0.75, 0.65, 1, 0.8)           # world map, Q4 right: compass button -> Intel Mission
INTEL_HERO = (0, 0.12, 0.3, 0.26)               # Intel Mission: hero portrait (top left) while there's one to tap
CRUCIBLE_REMAINING = (0.25, 0.555, 0.65, 0.59)  # Truegold Crucible: "Remaining today: 7" (above the Refine button)
CRUCIBLE_REFINE = (0.3, 0.59, 0.7, 0.64)        # Truegold Crucible: teal "Refine" (7 a day, costs resources only)
CRUCIBLE_SUPER_X1 = (0.52, 0.83, 0.95, 0.89)    # ...teal "Super Refine x 1" (bottom right; "x N" is left: never)
