# ks: Kingshot bot

Plays the timed parts of **Kingshot** (`com.run.tower.defense`) on an Android phone plugged into this server
by USB. It uses **plain adb only**: nothing is installed on the phone. It reads the screen from screenshots
(Tesseract OCR for text, OpenCV for pictures and colours) and taps with `adb shell input`. A systemd timer
starts it every minute; each run does whatever jobs are due, then closes the game.

All commands below are run from `~/projects/ks`.

---

## 1. Everyday commands

```bash
.venv/bin/python run.py --list            # every job: on/off, schedule, next run (IST + UTC), last result
.venv/bin/python run.py --timeline        # what runs next, in order
tail -f logs/runner.log                   # live log (all times UTC)
ls -t logs/failures | head                # screenshot + OCR text of the latest failures
```

Run one job now (works even while the bot is paused by hand):

```bash
.venv/bin/python run.py --job dailies                   # the whole job
.venv/bin/python run.py --job dailies --part vip        # only one part of a job made of parts
.venv/bin/python run.py --job dailies --part gems,deals # several parts
# extras: --keep-open (leave the game open)   --no-sleep (leave the screen on)   -v (debug log)
```

If it says "Another run is still in progress", a timer run is going; try again a minute later.

## 2. Pause, stop, turn off

```bash
.venv/bin/python run.py --pause 2h        # no new runs for 2 h (90m, 12h... ; no value = 1 h)
.venv/bin/python run.py --resume          # end the pause now
```

Playing on your own phone: the game allows one session. If you log in while the bot plays, the bot sees
"logged in on another device", closes its game **without** reconnecting, and pauses itself for 1 h.

Stop the job that is running right now:

```bash
.venv/bin/python run.py --pause 1h              # first, so the timer doesn't start a new run
pkill -f "projects/ks/run.py"                   # stop the running job
adb shell am force-stop com.run.tower.defense   # close the game
rm -f .runner.lock                              # only if a later run says "Another run is still in progress"
```

Turn the automation off for good / back on (needs sudo):

```bash
sudo systemctl disable --now android-cron.timer     # off (also after reboots)
sudo systemctl enable  --now android-cron.timer     # on again
systemctl list-timers android-cron.timer --no-pager # check
```

Nothing is lost when it's off: code, `state.json` and logs stay.

## 3. The jobs

| Job | When (IST) | What it does |
|---|---|---|
| troops_training | 6:00 am, 5:30 pm | Barracks → Train page → Barracks / Stable / Range: 950 each when idle |
| dailies | 6:00 am | parts: gems, vip, deals (+ Bank), nomadic_merchant, cassie_recruit, truegold_crucible |
| collect_stamina | 6:00 am, 5:30 pm | Intel Mission → meat icon → Gourmet Feast when lit |
| intel_mission | 6:00 am, 5:30 pm | claim ticked pins; tent Rescue, swords Conquer, bear/lion Attack (preset M1); never boss |
| journey_supplies | 6:00 am, 5:30 pm | side panel → Realm Journey → "+" → free Claim |
| claim_rewards | 6:00 am, 5:30 pm | parts: mail_rewards, alliance_rewards (chests + big chest), help_members |
| arena | 5:23 am | parts: pan_extra_intel_mission, arena (fights until attempts are 0) |
| farming | every 7.5 h | Bread, Wood, Stone, Iron: Lv.8 tile → Gather (heroes 2 and 3 removed) → Deploy |
| recruit_heroes | on the game's timer | free Advanced / Epic recruit |
| online_rewards | on the chest timer | side panel → Online Rewards chest |
| alliance_tech_contribution | every 250 min | Alliance → Tech → hold Contribute |
| conquest | every 9 h | Conquest → idle income Claim |

Jobs due at the same time share one game launch and run in **priority** order (lower first):
troops_training 90 → dailies 100 → collect_stamina 105 → intel_mission 110 → journey_supplies 112 →
claim_rewards 115.

Rules every job follows:
- **Never** taps anything that costs real money or gems (₹ prices, TOP UP, "Buy", paid refreshes).
  The one exception the user chose: the Nomadic Merchant's **VIP XP** box is bought with gems.
- Checks a button's text and colour before tapping it; if the screen isn't what it expects, it stops.
- A failed job retries after 30 min (never later than its next scheduled time). Otherwise fixed-time jobs run
  only at their times.
- Ends where it started (town or world map); the game is closed after the session.

---

## 4. How the code is laid out

```
run.py              the runner (what the timer starts every minute)
config.py           settings (timeouts, file paths, OCR); secrets go in .env
game.py             Kingshot-wide behaviour: loading, pop-ups, start/end of every job
regions.py          named screen areas and points used by the jobs
town.py             town navigation: drag to a building (screens/town.json) + find its picture
jobs/               ONE FILE PER JOB (jobs/_template.py is the starting point)
core/phone.py       the phone: adb, screenshots, tap/swipe/type, wait_for/find/exists
core/vision.py      reading screenshots: OCR, picture matching, colour checks, red dots
core/task.py        @job decorator, Task base class, run_parts (jobs made of parts)
core/schedule.py    At("00:30", tz="UTC"), Every(hours=4), Cron("0 */2 * * *")
core/state.py       state.json: last run, status, next run per job
core/pause.py       pause.json (--pause / --resume)
core/timeparse.py   "1d 07:59:52" / "2h 5m" -> timedelta
templates/          small pictures the bot looks for (buttons, icons, buildings)
screens/            town.json: positions of the 48 town buildings
tools.py            terminal helpers to build jobs (ocr, find, crop, tap...)
systemd/            the timer + service files (installed by install.sh)
logs/               runner.log, failures/ (screenshot + OCR when a job fails)
state.json          per job: last run (UTC), status, error, next_at  (you can edit next_at by hand)
```

### What happens on every timer tick (`run.py`)

1. Phone not connected or bot paused → do nothing.
2. Read `state.json`; find the jobs whose next time has come.
3. Take `.runner.lock` (only one run at a time), wake the phone.
4. Open the game (`game.Kingshot.on_open`): launch, wait for loading, close pop-ups (any X, Welcome back,
   resource-pack box → Enter Game).
5. For each due job, by priority:
   - `before_job`: back out to the town / world map, note which one it is;
   - the job function itself;
   - `after_job`: Back until the bottom menu shows, return to the view it started from;
   - save its next run time in `state.json`.
6. If the next job is due within 10 s keep the game open, otherwise close it and put the phone to sleep.

A job that fails gets a screenshot in `logs/failures/` and a retry in 30 min; the game is relaunched before the
next job. A job may run at most `timeout` seconds (default 240, set in game.py; long jobs set their own).

### A job file

```python
from datetime import timedelta
from core.schedule import At
from core.task import job
from regions import NAV_Q4, SCREEN_TITLE

@job(schedule=At("00:30", "12:00", tz="UTC"), priority=110, timeout=600, enabled=True)
def my_job(app, phone, log):
    app.tap_on_main(phone, log, text="Alliance", region=NAV_Q4)       # first tap of a job (handles pop-ups)
    phone.wait_for(text="Alliance", region=SCREEN_TITLE, timeout=10)  # check the screen changed
    phone.tap(text="Claim All", region=(0, 0.88, 1, 0.98))
    log.info("claimed")
    return None          # next run: None = next schedule slot, timedelta(...) = that long from now, datetime = then
```

- `@job(...)` options: `schedule=` (At / Every / Cron; leave out if the job returns its own next time),
  `priority=` (order within a session), `timeout=` (seconds), `retry_minutes=` (default 30), `enabled=`.
- `app` is the Kingshot object from game.py, `phone` is core/phone.py's Phone, `log` is a logger.
- The file is picked up automatically (no registration). Files starting with `_` are ignored.
- **Jobs made of parts** (dailies, arena, claim_rewards): one function per part, then
  `run_parts(app, phone, log, {"name": function, ...})`. Each part starts and ends on the main screen.
  Test one with `--part name`.

### The phone helpers you'll use most (core/phone.py)

| Call | Does |
|---|---|
| `phone.tap(text=..., region=...)` / `phone.tap(image="name", region=...)` | find it (waits up to `timeout`) and tap it |
| `phone.tap_xy(x, y)` | tap a point (pixels) |
| `phone.wait_for(text=/image=, region=, timeout=)` | wait until it shows; raises ElementNotFound |
| `phone.exists(..., timeout=0)` | True / False, no error |
| `phone.find(...)` | look once, returns a match or None |
| `phone.wait_any({...}, {...})` | whichever shows first (returns its index) |
| `phone.read_text(region)` / `phone.read_duration(region)` | OCR text / a countdown as timedelta |
| `phone.swipe(x1, y1, x2, y2, ms=)` / `phone.scroll_to(text=, region=)` | drag / scroll a list until text shows |
| `phone.hold_xy(x, y, seconds)` | long press |
| `phone.type_text("950")`, `phone.key("KEYCODE_DEL")`, `phone.back()` | typing and keys |
| `phone.screen(region)` / `phone.forget_screen()` | take a screenshot (strip only = faster) / force a new one |

A **region** is `(x1, y1, x2, y2)`: fractions of the screen (0-1) or pixels. The screen is 1080 x 2340.
Quadrants Q1 (top right), Q2 (top left), Q3 (bottom left), Q4 (bottom right) are in regions.py and
QUADRANTS.md. `text=` matching ignores case and small OCR slips; `image=` looks for `templates/<name>.png`.

Colour / picture checks (core/vision.py): `median_hue(img, region)` (green ≈ 35-85, teal ≈ 75-105,
orange ≈ 8-30), `coloured_share(img, region)` (≈ 0 for a grey button), `red_dots(img, region)`
(notification dots), `find_image` / `find_shape` (picture / outline match).

Shared steps in game.py: `app.tap_on_main(...)` (a job's first tap; closes late pop-ups; `then=` retaps if the
tap was ignored), `app.town_from_launch(...)` (relaunch the game so the town view is centred, for jobs that
go to a building), `app.to_main_screen(...)`.

### Changing something

| You want to… | Edit |
|---|---|
| change when a job runs | the `@job(schedule=...)` line in its file (and, to apply now, `next_at` in state.json) |
| change what a job taps | its file in `jobs/`; positions/areas are named in `regions.py` |
| switch a job off | `@job(enabled=False, ...)` |
| handle a new start-up pop-up | `game.py` → `_close_one_popup` |
| a button moved / looks different | `tools.py crop ...` a new picture into templates/, or fix the area in regions.py |
| add a job | copy `jobs/_template.py` to `jobs/<name>.py` |

After any change:

```bash
.venv/bin/ruff check --fix .   # style / lint: must say "All checks passed!"
.venv/bin/pyright               # types: must say "0 errors, 0 warnings"
```

then test with `run.py --job <name> --keep-open --no-sleep`. The editor (VS Code + Pylance) shows the same type
info while you type: hover a call to see what it takes; `phone.` / `vision.` list what exists. Types used everywhere:
`Phone` (core/phone.py), `Kingshot` (game.py), `Image` (a screenshot), `Region` (x1, y1, x2, y2), `Logger`.

---

## 5. Building a job: tools.py

```bash
.venv/bin/python tools.py ocr [x1 y1 x2 y2]        # all text on screen + tap coordinates
.venv/bin/python tools.py find "Claim" [region]    # where is this text? (same matching as jobs)
.venv/bin/python tools.py shot [file.png]          # save a screenshot
.venv/bin/python tools.py crop x1 y1 x2 y2 NAME    # cut part of the screen into templates/NAME.png
.venv/bin/python tools.py template FILE NAME       # import an icon from any screenshot (PC/Mac, any size)
.venv/bin/python tools.py findimg NAME             # where is templates/NAME.png on screen?
.venv/bin/python tools.py tap X Y | swipe X1 Y1 X2 Y2 [ms] | back | home | text "hello"
.venv/bin/python tools.py app | packages [filter] | wake | sleep
```

Pause the bot first (`run.py --pause 2h`) so a timer run doesn't tap at the same time.

## 6. Setup (already done on this server)

Phone: Developer options → **USB debugging** on, accept "Allow USB debugging" (Always allow), screen lock
**None** or Swipe (a PIN goes in `.env` as `PHONE_PIN=1234`).

```bash
sudo ./install.sh     # apt packages, .venv, systemd timer (every minute), adb server, NTP
adb devices           # the phone must show "device"
```

Notes:
- Logs and state.json are in UTC; `--list` / `--timeline` show IST too.
- `logs/runner.log` rotates at 2 MB (5 copies); `logs/failures/` keeps 7 days / newest 20.
- `systemd/adb-server.service` keeps one adb server running for the timer runs.
