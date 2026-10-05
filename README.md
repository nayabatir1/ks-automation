# ks: Kingshot bot

Plays the timed parts of **Kingshot** (`com.run.tower.defense`) on an Android phone, on a schedule, from a
Debian server over USB, using **plain adb only**. Nothing is installed on the phone. The screen is read from
screenshots, text with Tesseract OCR and icons with OpenCV template matching. Input goes through
`adb shell input`.

```
game.py           Kingshot: launch/loading/pop-ups (on_open, before_job) + shared helpers
regions.py        screen areas shared by all jobs (Q1-Q4, LEFT_MID, NAV_REGION, ...)
jobs/             one file per job (online_rewards.py, ...); files starting with _ are ignored
templates/        icon images for image= (made with tools.py crop / tools.py template)
screens/          screen maps: town.json (+ panorama, labelled image) — names and positions; see Town layout
tools_map/        scripts that build screen maps from screen recordings
run.py            runner: picks due jobs, wakes phone, opens game, runs jobs, closes game, sleeps phone
tools.py          terminal helpers for building jobs (ocr, find, crop, template, tap, ...)
config.py         settings; secrets/overrides go in .env (see .env.example)
core/             engine: phone.py (adb + screen helpers), vision.py (OCR + template matching),
                  schedule.py (Every/At/Cron with tz=), task.py (@job), state.py, loader.py
systemd/          timer + service units (installed by install.sh)
logs/             runner.log + failures/ (screenshot + OCR text when a job fails)
state.json        per job: last run (UTC), status, error, duration, next_at
```

## Status (2026-10-03)

Phone: Samsung Galaxy M30s (SM-M307F, Android 11, 1080x2340), serial `RZ8M920GS2J`, no lock screen.

- Done: `install.sh` has been run (Tesseract 5.5, `adb-server.service` and `android-cron.timer` are enabled, NTP is on).
  The runner, OCR, taps, and the start of every session (open game, close pop-ups) work on the phone.
- **Live jobs:** `online_rewards`, `alliance_tech_contribution` (every ~4 h, when all 25 attempts are back),
  `conquest` (every 9 h) and `arena` (daily 23:53 UTC).
  The timer runs `online_rewards` on its own (World -> side panel -> Online Rewards ->
  the chest is claimed by opening it -> read countdown -> close the game -> phone to sleep), about 60 s per run.

Progress log, 2026-10-02:
1. Reviewed the first (uiautomator2) version. uiautomator2 doesn't work for this game, so the project was rewritten
   to use plain adb: OCR + OpenCV for reading the screen, `adb shell input` for taps and typing. The uiautomator2
   helper files it had left on the phone (`/data/local/tmp/u2*`) were deleted.
2. Found that `screencap -p` is slow on this phone (4.4 s) and switched to raw `screencap` (1.2 s).
3. Built the runner, tools.py, the schedules with tz=, the systemd timer and install.sh. 22 schedule tests pass.
4. Ran `sudo ./install.sh`. The timer fires every minute and runs cleanly.
5. Tested on the phone: wake/sleep, `tools.py ocr`, taps, and a Settings demo task. Fixed OCR joining
   words out of order in a line.

Progress log, 2026-10-03:
6. Added jobs, each with its own next-run time (see "Jobs" below). Added `run.py --timeline`, `--job`,
   and `phone.read_duration()`. Tested with a fake phone (18 checks).
7. Started Kingshot. Opening the game works: the loading bar shows up after about 8 s and the game is loaded after
   about 21 s, ending on an offer pop-up. Saved the pop-up close button as `templates/close_x.png`.
   Warning: the start-up pop-ups have real-money buttons (e.g. ₹89.00).
8. Closing the start-up pop-ups works: it taps the X (`templates/close_x.png`, Q1) until the city screen's bottom
   menu (`Backpack`) shows with no X left, checked twice 2 s apart. The city screen is animated, so `wait_stable`
   can't be used there. A full open + pop-ups takes about 30 s.
9. Moved the shared start/end into the runner as `on_open` / `before_job` hooks (wrapper), so every job starts
   on the city screen and the game is always closed afterwards. Tested with a fake phone (hook order,
   including failures) and on the real phone.
10. Job `online_rewards` step 1: tap the World icon (`templates/world_icon.png`, Q4), then confirm the world map by
    the bottom-right button changing to "Town". Added `tools.py template FILE NAME`, which imports an icon from any
    screenshot (e.g. a Mac one at a different size), finds it on the phone at the matching scale, and saves the
    phone's own pixels as the template.
11. `online_rewards` step 2: tap the side tab `>` on the left edge (`templates/side_tab.png`, `LEFT_MID`), then confirm
    the side panel by "Building Queue" or "Wilderness". The Mac screenshot didn't match on the world map, so the
    template was cut from the phone screen, leaving out the red notification dot. `tools.py template` now only
    tries scales 1-4x, because tiny scales gave false matches.
12. Restructured for readability: one file per job in `jobs/`, the game in `game.py`, shared areas in `regions.py`.
    Removed the multi-app layer (`tasks/`, the Settings demo and the app templates), because this project is only
    about Kingshot. Quadrants use the normal maths numbering. A full run of `online_rewards` so far takes about 44 s.
13. Added ruff (`.venv/bin/ruff check --fix .`). Sorted the imports in every file and fixed the other lint findings
    (loop-variable closures, broad `except`s narrowed to `PhoneError`, explicit `check=False`, and so on).
14. `online_rewards` steps 3-4: scroll inside the side panel until "Online Rewards" shows (`phone.scroll_to` now
    swipes inside `region=` so the world map behind doesn't move), then tap it. That opens the chest screen with
    "Next Chest Ready In: 00:00:27". `phone.read_duration(region=CHEST_TIMER)` reads that countdown correctly.
15. The game no longer restarts if it's already open (`reuse_open_app = True` in game.py): `on_open` just checks it's
    on the city or world map (closing any pop-up), and restarts it only if it's on a screen it doesn't know.
    `online_rewards` skips the World tap when it's already on the world map. Added `run.py --keep-open`, which leaves
    the game open after a run (for building jobs step by step). A run on the already-open game took 25 s.
16. `online_rewards` is complete: after the chest screen opens it reads "Next Chest Ready In", taps a blank spot
    (`BLANK_SPOT`) to close the screen, and returns the countdown + 10 s as its next run. Real run: 24 s,
    "next chest in 0:01:27".
17. Jobs due at the same time share one session (one launch, one close). After the due jobs, if any job (or the same
    one again) comes due within `session_wait_minutes` (5), the game stays open and the runner waits for it instead of
    closing and reopening. Sessions are capped at `max_session_minutes` (20). `--job` runs don't wait. Tested with a
    fake phone.
18. Changed at the user's request: the game stays open after a session only if the next job (any job) is due
    within 10 s (`session_wait_seconds`); otherwise it is always closed. Tested with a fake phone.
19. Every run first checks that the phone is connected (`adb get-state`). If it isn't, no job runs and no job state
    changes; the log gets one warning when it goes away and one line when it's back.
20. Enabled the game. The first automatic run failed safely: my earlier test had left the side panel open, so the
    side tab was hidden. Fixed: step 2 skips the tap when the panel ("Wilderness") is already open, and step 3 also
    scrolls up. Since then the timer runs it on its own: opening Online Rewards claims a ready chest, and the job
    reads the next countdown and comes back then.
21. New start-up pop-up "Welcome back!" (offline income, shows now and then after the game opens). It made a timer
    run fail ("app did not open"). Now `close_popups` (run by `on_open` for every session, so for every job) taps its
    green **Confirm** (user's choice) inside `WELCOME_CONFIRM`. Tested: offer X -> Welcome back -> Confirm -> job ok.
22. Old failure snapshots are now deleted automatically (7 days / newest 20), saved as JPEG (~10x smaller than PNG),
    and the OCR text file gets the right name (it used to come out as `kingshot.txt` because of the dot in job names).
23. Playing on your own phone (the game allows one session):
    - Pause switch: `run.py --pause [2h|90m]` (default 1 h) and `run.py --resume`, stored in `pause.json`. While
      paused, timer runs do nothing and manual runs refuse. A pause always ends by itself.
    - Kick detection: when opening the game or a job fails, the runner checks for "The account has been logged in on
      another device". If it's there, it closes the bot's game (never taps Reconnect), pauses 1 h
      (`SESSION_TAKEN_PAUSE_MINUTES`), and leaves the jobs as they were, without counting a failure.
    - After a pause/cooldown, the first tick runs **all** pending jobs together. Jobs have no "too late" cutoff.
    Tested with a fake phone (kick during a job, kick while opening, pause mid-session, expiry, pending jobs after it)
    and on the command line.
24. Started job `alliance_tech_contribution` (`jobs/alliance_tech_contribution.py`, `@job(enabled=False)` until done).
    Opening the game and closing pop-ups come from `on_open`, so the job body starts on the city screen.
25. `alliance_tech_contribution` step 1: tap "Alliance" in the bottom menu's Q4 half (`NAV_Q4`, text match, so the
    99+ badge doesn't matter), then confirm the Alliance screen by its title (`ALLIANCE_TITLE`).
26. `alliance_tech_contribution` step 2: tap the Tech button (`templates/tech_button.png`, book icon + label without
    the changing badge, `Q4_TOP`), then confirm the tech screen by "Your Rank" (`TECH_HEADER`; OCR sometimes reads "Your Rankin"). OCR can't read the
    big outlined button labels on the Alliance screen, so this one is matched as an image.
27. `alliance_tech_contribution` step 3: tap the Covenant-Making node (`templates/covenant_making.png`, castle art only,
    `BOTTOM_MID`) -> its contribution box (title checked in `TECH_BOX_TITLE`). **The box's left Contribute button
    costs gems; never tap it.** The right one costs 10,000 bread ("Attempts: 25/25").
28. `alliance_tech_contribution` step 4: hold the RIGHT (bread) Contribute button for 5 s (`phone.hold_xy`); it greys
    out ("Attempts: 0/25"). Safety, because the LEFT button spends gems and its label scores 0.96 on the same
    template: the search covers only the right half (`CONTRIBUTE_RIGHT`), and the button must be teal
    (`vision.median_hue` 75-105; bread button 91, gem button 19) before it's touched. Tested on the phone: attempts
    25 -> 0, gems unchanged. Afterwards the box shows "New Contribution attempt in 00:09:53".
29. `alliance_tech_contribution` is complete and **live**: after the hold it reads "New Contribution attempt in …"
    (`NEXT_ATTEMPT`) and comes back after that + 240 min (24 more attempts x 10 min), when all 25 attempts are back.
    If the button is already grey (no attempts, `vision.coloured_share` < 0.3) it skips the hold and just reads the
    timer. Real run: grey -> "next attempt in 0:06:44" -> next run 4 h 07 m later.
30. Faster UI actions:
    - Taps, holds and Back go through Android's built-in `monkey --port` (started once per session, quit at the
      end): ~0.06 s per tap instead of ~1 s for `input tap` (which starts a Java process each time). It falls back to
      `input` if monkey can't start. Raw `sendevent` touches are blocked on this Samsung (SELinux). Swipes stay on
      `input swipe`, because monkey's "touch move" doesn't drag Unity lists.
    - Checks with a region fetch only those screen rows (~0.3 s instead of ~1.1 s for a full screenshot).
    - Fixed pauses after taps were replaced by waiting for the next screen (or for a pop-up to disappear).
    - `scroll_to` swipes further and faster, and remembers how many swipes it needed (`scroll_memory.json`) so next
      time it does them in one go.
    - Between jobs, `before_job` presses Back until the bottom menu shows (a job may end deep in a menu).
    - `online_rewards`: "Online Rewards" sits just above "Water Essence Gathering" and is only there when a chest is
      ready, so the job scrolls to Water Essence and looks above it. Not there = no reward yet: it keeps the known
      chest time (or checks again in 30 min). That's not a failure.
    Results: `alliance_tech_contribution` 17.8 s -> 6.2 s (11.5 s with the 5 s hold); `online_rewards` with no reward
    ready 75 s -> 14 s.
31. Quicker first tap: `close_popups` returns as soon as the bottom menu shows (no extra "late pop-up" look), monkey is
    started while the game loads, and a check may reuse a screenshot that's under 1 s old if nothing was tapped since.
    Each job's first tap goes through `Kingshot.tap_on_main()`, which taps straight away; if a late pop-up shows up
    instead, it closes that first. Pop-up handling 5-8 s -> 3 s.
32. Keyboards off: every session starts with `phone.disable_keyboards()` (`ime disable` for every enabled keyboard,
    including Samsung Keyboard and Google voice typing), because they come back on after reboots or updates. It logs
    when it finds one switched back on. `DISABLE_KEYBOARDS` in config.py turns this off. To type on the bot phone by
    hand: `adb shell ime enable com.samsung.android.honeyboard/.service.HoneyBoardService` (the next session switches
    it off again).
33. New job `conquest` (`jobs/conquest.py`, disabled until done). Step 1: tap "Conquest" in the bottom menu's Q3 half
    (`NAV_Q3`, via `tap_on_main`), then confirm the Conquest screen by its "Conquer" button (`CONQUER_BUTTON`).
34. `conquest` is complete and **live** (every 9 h): Conquest -> the chest's Claim (only if **green**;
    `coloured_share` > 0.3; grey right after a claim) -> "Idle Income" box -> its Claim -> close the "Rewards" screen
    ("Tap anywhere to exit") -> come back in 9 h ("Max Idle Time: 9 hrs"). After it, the runner does the next due job or
    closes the game. Grey Claim = nothing yet: keep the known time, or 9 h.
35. OCR fix: the white-text pass discarded letters taller than 12% of the area being read, so big button labels
    in small regions vanished ("Claim" in the Idle Income box, "Your Rankin(g)"). The limit is now a fixed 150 px.
36. Screen maps, starting with the town: `screens/town.json` lists 48 buildings with their positions on
    `screens/town_panorama.jpg` (6955x5830, stitched from a 1080x2340 screen recording; `town_labelled.jpg` shows the
    names). Built with `tools_map/town_video.py VIDEO OUT` (tracks the view, stitches, reads the floating name labels)
    and `tools_map/town_clean.py OUT` (snaps readings to known names, merges repeats). Two tower numbers were checked by
    eye. The bot's own survey (panning the phone) was dropped: the town's edges are diagonal cliffs/water, and
    World -> Town doesn't re-centre the view.
37. New job `arena` (`jobs/arena.py`, disabled until done): daily at 23:53 UTC (`@job(schedule=At("23:53", tz="UTC"))`).
    Fixed-schedule jobs that never ran now wait for their first slot instead of running straight away
    (`run.first_run`); jobs without a schedule are still due immediately.
38. Town map v2, made from the bot phone itself: the user panned the town while the bot recorded its screen
    (`screenrecord`, 3 segments, 8 min). `tools_map/town_video.py` now takes several segments as one recording. 48
    buildings including Defense Tower 4, in fresh-launch screen coordinates. Map builds run detached (`setsid nohup`) and at low CPU priority, because a build at
    normal priority slowed a live job enough to fail it.
39. Clean-up: removed the town recordings and build working files (temp/), the first video-based map, the unused
    daytime Arena template, the failed automatic survey script and the bad arena route. Kept: `screens/town.json` +
    images and the two map-building scripts (to rebuild from a new recording if the town changes).
40. `town.py`: `go_to_building(phone, log, name)` navigates the town by building names (a "look" = a slow 150 px drag with
    OCR during it; each name read fixes the view position on `screens/town.json`; drag towards the target; repeat). It
    only returns a tap point when the label is well inside the screen (`SAFE`), otherwise it centres the building first.
    `arena` step 1: town view -> go_to_building("Arena") -> tap -> "Arena of Glory" (ranking, season timer, Challenge
    with an attempts badge, History, Def. Lineup). First run: 7 looks / 85 s, and every 2nd look read no names (to tune).
41. Faster town navigation (`town.go_to_building`): after a fresh launch the view is known (Town Center centred, view
    (0, 0), `Kingshot.town_view`), so it drags straight to the building using the map, then checks the building's
    picture (`templates/town_<name>.png`) with outline matching (`vision.find_shape`), which works day or night. Name
    looks only when the picture isn't where expected or the position is unknown. Drags use the icon-free middle band
    of the screen (up to ~1 screen each). Arena: 85 s / 7 looks -> 9 s / 1 check. Don't switch the phone to grayscale:
    the colour safety checks (teal Contribute, green Claim) need colour.
42. `arena` step 3: read your standing from your own row above Challenge (`ARENA_MY_ROW`, fixed position):
    left-most number = rank, right-most = Arena Points; name/power/stars are ignored, so changing values don't matter.
    Live: rank #433, 1,175 points.
43. `arena` step 4: tap Challenge (`ARENA_CHALLENGE`) -> "Challenge List": My Power, 5 opponents (power green = lower
    than yours / red = higher, points, server, a teal swords button each), "Daily challenges: N" with a "+" (probably
    buys attempts: never tapped) and a green "Free Refresh".
44. `arena` step 5, choosing an opponent (user's rules): read "Daily challenges: N" (0 = stop; the "+" beside it buys
    attempts with gems and is never tapped); attack the first opponent whose power is green (= lower than mine; the
    colour is reliable, the coloured numbers aren't); if none, Free Refresh, but only if the button says "Free" and is
    green (a gem price = stop), at most 3 per run. The swords button is only tapped after a teal check. For now
    `ATTACK = False`: it logs which opponent it would attack. Live check: 4 attempts, row 1 (15.9M) chosen.
45. `arena` is complete and **live** (daily 23:53 UTC): navigate to the Arena (2 s when the game is open on the town),
    read rank/points, open the Challenge List, then until "Daily challenges" is 0: attack the lowest-powered green
    opponent (whole-digit power), Squad Settings -> Fight -> pause (`templates/battle_pause.png`, re-tapped until
    the menu shows: a tap right at the start is ignored) -> Retreat (ends the fight at once; counts as a loss: the user's
    choice) -> tap anywhere to exit. No weaker opponent -> Free Refresh only if free; gems never. Real run: 2 fights,
    attempts 2 -> 0, 49 s. (A fight left alone against a weaker opponent was a Victory, 1,186 -> 1,193 points.)
46. `arena` step 6: when the attempts are used up the job leaves the arena itself (2 Backs: Challenge List -> Arena ->
    town, ~2 s instead of ~25 s for the generic back-out), so the runner can go straight on to the next due job or close
    the game.
47. `arena` power is compared as real values: "15.9M" (1M+, one decimal) -> 15,900,000 and "166,500" (under 1M, full
    number) -> 166,500 (before, 15.9M would have counted as 159 and beaten 147,000). OCR reads the bright fill of the
    digits first (no dark outline; fixed 60,000 being read as 40,000). "Unranked" standing -> rank None. Checked on
    the second account's screenshots ([w4r]Daddy; account switching comes later).
48. `arena`: no green opponent and the free refreshes are used up (or the refresh costs gems) -> attack the
    lowest-powered red opponent instead of stopping (user's rule).
49. `alliance_tech_contribution`: after the attempts are used up, all of them are back exactly 250 min later (user's
    rule), so the job just returns 250 min; it no longer reads the "New Contribution attempt in" countdown (item above
    with + 240 min is replaced).
50. Every job now ends where it started (user's rule): before_job notes the view (world map if the bottom-right
    button says "Town", town if it says "World"); the new runner hook after_job presses Back until the bottom menu
    shows (closing the job's pages) and taps World/Town if the job switched views. online_rewards closes its side
    panel itself with the panel's "<" tab (templates/side_tab_close.png): Back there opens "Quit game?".
51. New job `recruit_heroes` (`jobs/recruit_heroes.py`, disabled until done): navigation built and tested — Heroes
    (bottom menu) -> "Recruit Heroes" (bottom right) -> Hero Recruitment (Advanced: "Daily free recruitments: N",
    green "Recruit x1 Free" / Recruit x10 with keys; Epic: "Next free: 1d 08:06:24", Recruit x1 / x10 with keys).
    Back-out: 2 Backs to the town, ~10 s.
52. `recruit_heroes` complete and **live**: for Advanced and Epic, tap the green "Recruit x1 / Free" only (colour
    check, hue 35-85; every orange button costs keys and is never tapped), tap "Tap anywhere to exit" on the Rewards
    screen until it closes (taps during the chest animation are ignored; never the orange "Recruit x1" above it), then
    read "Next free: ..." of both and come back at the sooner one. Advanced: 5 free a day, 5 min apart; after the 5th
    its timer runs to the daily reset (00:00 UTC). Epic: one free every ~2 days ("1d 07:59:52"). OCR fixes: Epic timer
    region kept tight (the hero art above broke it), only a reading with a whole h:mm:ss counts (re-read up to 3x),
    core/timeparse reads "Id"/"ld" as "1d".
53. New job `dailies` (`jobs/dailies.py`, disabled until done). Part 1, gems / Top-up Center (real-money shop:
    never tap ₹ or TOP UP): tap the cart picture (templates/gems_shop.png; the gem count changes) -> "Top-up
    Center". Tabs (names and pictures change) sit in a swipeable row; a red dot on a tab = a free chest in its header.
    For each dotted tab: tap it, tap the free chest — found by its own red dot ("Claimable") or, failing that, a white
    "Claimable"/"Free" label (Daily Deals: no dot, label "Free", then a "Claimed" pop-up with "Tap anywhere to exit")
    — then swipe the row on until it stops moving. vision.red_dots() finds the notification dots (round ~20 px blobs;
    red icons/ribbons/"!" badges don't count). Hand test: Master's Collection, Hope Market, Custom Forging Set and Daily
    Deals gave +100/+100/+150/+100 gems.
    Part 2, VIP (orange V badge, templates/vip_badge.png; the level number changes) -> "VIP" screen: the daily
    sign-in VIP XP chest under Shop (red dot; +500 XP, "Rewards" pop-up) and the green Claim of "VIP N Daily Free
    Bundle"; both reset at 00:00 UTC. Never: the "+" by the XP bar, Shop, the ₹ "VIP N Special Pack" (it has a red
    dot too). Reward pop-ups ("Click to continue" / "Tap anywhere to exit") ignore taps during their animation:
    dismiss_popup() taps the dim area above them until they're gone.
    Part 3, Deals (gift icon): only two tabs give free things — "Sign-in & Earn It" (one Free reward per day) and
    "Hero Rally" (Free rewards unlock as tasks earn points). open_tab() finds a tab by name (the open tab shows no
    name, so its big title is checked first; short swipes so no tab is read cut off at the edge); claim_glowing()
    taps Free-column items with a pale glowing frame (a 100-175 px pale line on top and another 110-160 px below).
    Never: Epic / Path of Honor column, Unlock, Purchase Level, "+", ₹. Hand test: Sign-in Day 1 = 100 gems.
    Whole job ~95 s when nothing is left to claim.
54. `dailies` is split into parts (PARTS = gems, vip, deals, ... in jobs/dailies.py), each starting and ending on the
    city / world map. Test one part: `run.py --job dailies --part vip` (several: `--part gems,deals`; leave `--part`
    out to test them all together). A `--job` run now also works while the bot is paused by hand (`--pause`); the
    pause still stops timer runs, and the auto-pause after a "logged in on another device" still stops everything.
55. `dailies` part `nomadic_merchant`: Shop (bottom menu) -> Nomadic Merchant tab. Buy any of the 6 boxes priced in
    bread/wood/stone/iron (a bought box is restocked at once, no confirm), one at a time with a fresh screenshot,
    until all 6 are priced in gems (blue diamond in the price bar); then Free Refresh (only while it says Free and is
    green) and again. Never a gem price. One stock took ~80 buys (~4 s each), so the job timeout is now 900 s.
    Live run: 21 buys + 1 free refresh, gems unchanged (32,870).
56. `arena` is now made of parts (core/task.run_parts, shared with dailies): `intel_mission` then `arena`.
    intel_mission: world map -> compass button (Q4 right, templates/compass_button.png) -> "Intel Mission" -> tap
    the hero portrait at the top left when it's there (templates/intel_hero.png; brings new mission pins) -> Back ->
    Town. Switching World -> Town shows the town where it was left (NOT re-centred), and intel_mission doesn't move
    it, so the arena part still knows where it is after a fresh launch. Test: `run.py --job arena --part
    intel_mission`.
57. `dailies` now runs daily at 00:10 UTC (still disabled until all parts are done). New part `cassie_recruit`: on
    the town, go_to_building Stable -> Barracks -> Range -> Enlistment Office (new outline templates
    town_stable/barracks/range/enlistment_office.png, cut by hand while the user panned) and tap every bubble with
    Cassie's picture (templates/cassie_bubble.png, matched at several sizes: bubbles are drawn smaller near the town
    edge). The tap is instant, no pop-up; one tap turned the other buildings' Cassie bubbles into other heroes
    (knight / helmet / archer bubbles are not tapped). The view is carried from building to building (~5 s each).
58. `dailies` part `truegold_crucible`: world map -> side panel -> scroll to "Truegold Crucible" -> tap Refine
    until "Remaining today: 0" (7 a day; instant, no pop-up; the cost doubles each time but is resources only:
    5,000 -> 50,000 of each), then Super Refine x 1 once (costs raw truegold: 10, then 20; "Super Refines This
    Week" resets Mondays 00:00 UTC), then Back. "Super Refine x N" is never tapped. The OCR sometimes reads the N
    of "Remaining today: N" on its own line; unreadable -> stop refining (never treated as 0).
59. The arena job's Intel Mission part is renamed `pan_extra_intel_mission` (taps the hero portrait). New job
    `intel_mission` (jobs/intel_mission.py, disabled until the user says; 00:10 UTC right after dailies + 10:00 UTC):
    world map -> compass -> Intel Mission. Pins are told apart by their white icon whatever the colour
    (templates/intel_pin_tent/bear/swords/lion.png; other kinds score <= 0.55, a match is >= 0.7); the boss is never
    matched. A pin with a green tick is tapped to claim its reward (it disappears; no Claim All). Open pins:
    tent View -> Rescue; swords View -> Conquer -> Squad Settings Fight -> Rewards tap to exit; bear / lion View ->
    Attack -> Deploy: preset M1 -> Deploy -> wait 2.2 x the march time. The mission box buttons are found by colour
    (the white lettering of "Rescue" doesn't OCR): green / teal / orange and brighter than grass. Stops below 20 meat.
    The compass template skips its top-right corner (a red dot shows there).
60. New job `collect_stamina` (jobs/collect_stamina.py, DISABLED until the user gives its schedule): Intel Mission
    -> meat icon -> "Get More": tap Gourmet Feast's button only when it's lit (grey while "Next Supply" counts
    down), then close everything. Never Use / Buy & Use (gems) / Go / "+". No timer reading (the user's choice).

Where to see the next run time: `run.py --timeline` (or `--list`, `state.json` next_at, and the log's "next ..." line).

Next: the next job. Take care when tapping in Kingshot: the start-up pop-ups have purchase
buttons, and the chat screen has a SEND button.

## Town layout (quick reference)

Rough grid of the town; north (the river) at the top. `screens/town.json` has exact positions: screen pixels as seen
right after a **fresh launch** (Town Center centred at about (480, 1145)), extended over the town. So the Arena at
(2978, 2005) is about 2.5 screen-widths right of the Town Center and 0.4 screen-heights down.
`screens/town_labelled.jpg` shows the names on the stitched town. DT = Defense Tower. DT 1 has no number in the game (the devs left it off).

| x≈-396 | x≈409 | x≈1215 | x≈2020 | x≈2826 | x≈3632 |
|---|---|---|---|---|---|
| Clinic, Mill | House 2, Sawmill | Quarry | DT 4, Iron Mine | · | · |
| House 4, House 8, Kitchen | Town Center | DT 2, House 1 | · | · | · |
| House 3, House 6, House 7 | DT 1, Suggestion Box | Alarm Bell, Barricade 1, Hero Hall | Watchtower | Stable | · |
| DT 3, House 5 | · | Conquerors Camp | Barracks, Monument | Arena, Range | DT 6, Dock, Embassy |
| · | Court of Justice | Enlistment Office, Infirmary | Academy | Guard Station | DT 8 |
| · | · | DT 5, Storehouse | Beast Cage, Command Center | · | Truegold Crucible |
| · | · | Master Academy | DT 7 | War Academy | Barricade 2 |

Names only show while the town view is being dragged (a slow 150 px drag over 4 s shows them; a gentle nudge via adb
doesn't). They look the same day or night, unlike the buildings, so navigation goes by names.

## Setup

On the phone: Settings → About phone → Software information → tap **Build number** 7 times →
back to Settings → **Developer options** → turn on **USB debugging**. Plug in USB and accept the
"Allow USB debugging?" prompt (tick *Always allow*). For a bot phone, set the screen lock to **None** or
**Swipe**. If you keep a PIN, put `PHONE_PIN=1234` in `.env`.

On the server, from this folder:

```bash
sudo ./install.sh          # apt packages, venv, systemd timer (every minute), NTP
adb devices                # phone must say "device"
```

Pause it while you play on your own phone (the game allows only one session):

```bash
.venv/bin/python run.py --pause 2h      # or 90m; no duration = 1 h. Ends by itself.
.venv/bin/python run.py --resume        # end it now
```

If you log in on your phone while the bot is playing, the bot sees "logged in on another device", closes its game
without reconnecting, and pauses itself for 1 h. After any pause, all pending jobs run on the next tick.

Check it:

```bash
.venv/bin/python run.py --list                 # jobs, next run (IST + UTC), last status
.venv/bin/python run.py --timeline             # every job, in the order it will run
systemctl list-timers android-cron.timer
sudo journalctl -u android-cron.service -n 50  # timer runs (no sudo needed if you're in group adm)
tail -f logs/runner.log
```

## Turning the automation off / on

The bot is started every minute by the systemd timer `android-cron.timer`.

Turn it off permanently (also after a reboot; a job that is running finishes, nothing new starts):

    sudo systemctl disable --now android-cron.timer

Also stop the adb server (optional; it only keeps the USB link to the phone open):

    sudo systemctl disable --now adb-server.service

Check that it's off:

    systemctl list-timers android-cron.timer --no-pager

Turn it back on:

    sudo systemctl enable --now android-cron.timer
    sudo systemctl enable --now adb-server.service   # if you stopped it

Nothing is deleted: code, job schedules (`state.json`) and logs stay in `~/projects/ks`.

Just a break instead: `.venv/bin/python run.py --pause 12h` (any duration), and `.venv/bin/python run.py --resume`
to end it sooner.

## Jobs

A session always looks like this; the runner does the wrapping, so a job file contains only its own steps:

```
launch game -> on_open()          (loading screen, start-up pop-ups; also after a crash-restart)
  -> before_job() -> job          (for each due job: make sure the city screen is showing)
  -> ...
close game                        (always, even after errors)
```

Every due job runs in one session, lowest `priority` first, so jobs due at the same time share one launch.
Afterwards the runner looks at the next due time across **all** jobs: if it's within `session_wait_seconds` (10 s),
the game stays open for it; otherwise the game is closed. A session lasts at most `max_session_minutes` (20).

Each job returns when it may run next: a `timedelta` (e.g. `phone.read_duration(region=...)` on a countdown
like "03:12:45"), a `datetime`, or `None` to use its `schedule=`. A failed job retries after `retry_minutes`,
and the game is restarted before the next job. The times are kept in `state.json` under keys like
`"kingshot.online_rewards": {..., "next_at": "...UTC"}`. To make a job run again right away, delete its entry.

### Add a job

1. `cp jobs/_template.py jobs/my_job.py` and rename the function to `my_job`.
2. Walk through the screens from the terminal: `tools.py ocr` lists every text with the point to tap.
   For icons: `tools.py template temp/screenshot.png my_icon` (from a Mac/PC screenshot) or
   `tools.py crop x1 y1 x2 y2 my_icon` (straight from the phone), then use `image="my_icon"`.
3. Use `wait_for` / `tap` / `wait_any` with a `region=` from `regions.py`, and after each tap wait for something
   that proves the next screen is really there.
4. `.venv/bin/ruff check --fix .` (import order and lint), then
   `.venv/bin/python run.py --job my_job --no-sleep --keep-open` (`--keep-open` leaves the game open, and the
   next run reuses it instead of restarting). If it fails, `logs/failures/` has a screenshot and OCR text.
5. When all jobs work, set `enabled = True` in `game.py`. The timer picks them up within a minute.

## tools.py commands

```
ocr [x1 y1 x2 y2]          all text + tap coordinates ([light] = found by the white-text pass)
find "text" [x1 y1 x2 y2]  same matching as jobs use
shot [file.png]            save a screenshot (default screen.png)
crop x1 y1 x2 y2 NAME      save part of the screen as templates/NAME.png
template FILE NAME [region] import an icon from any screenshot (Mac/PC, any size) as templates/NAME.png
findimg NAME               where is that template on screen?
tap X Y | swipe X1 Y1 X2 Y2 [ms] | back | home | text "hello"
app | packages [filter] | wake | sleep
```

Coordinates are pixels, or fractions such as `0.5` (x and y from 0 to 1).

## Notes

- Screenshots use raw `screencap`, which takes about 1.2 s on this phone; `screencap -p` takes about 4.4 s.
  If the raw format isn't recognised, the code falls back to PNG.
- `systemd/adb-server.service` keeps one adb server running. Without it, each timer run would start
  its own server, and systemd would kill it at the end of the run.
- Old logs are cleared automatically: `logs/runner.log` rotates at 2 MB and keeps 5 old copies (~12 MB max);
  `logs/failures/` keeps snapshots (JPEG + OCR text) for 7 days and at most the newest 20
  (`FAILURE_KEEP_DAYS` / `FAILURE_KEEP_MAX` in config.py); the systemd journal is capped by journald.
- Logs and `state.json` times are in UTC. `--list` shows next runs in both IST and UTC.
- Fixed-time jobs: `@job(schedule=At("00:05", tz="UTC"))`, `Every(hours=4)`, `Cron("0 */2 * * *")`.
  Without `tz=`, `SCHEDULE_TZ` (default UTC) is used.
