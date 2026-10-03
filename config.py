"""Global settings. Edit these, or override with environment variables (see .env.example)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Load .env (KEY=value lines) so manual runs and the systemd timer see the same settings.
try:
    for _line in (BASE_DIR / ".env").read_text().splitlines():
        _k, _sep, _v = _line.strip().partition("=")
        if _sep and not _k.startswith("#"):
            os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))
except FileNotFoundError:
    pass

# adb serial of the phone (see `adb devices`). None = the only connected device.
DEVICE_SERIAL = os.environ.get("PHONE_SERIAL") or None

# Lock-screen PIN/password. Keep it out of this file: put PHONE_PIN=1234 in .env.
# Leave unset if the phone uses Swipe / None lock (recommended for a bot phone).
UNLOCK_PIN = os.environ.get("PHONE_PIN") or None

# Timezone for schedules that don't pass tz=. Independent of the server's own clock/timezone.
SCHEDULE_TZ = os.environ.get("SCHEDULE_TZ") or "UTC"

# A slot missed (reboot, phone unplugged, previous task overran) still runs if we're
# at most this many minutes late. Each schedule can override with grace_minutes=.
DEFAULT_GRACE_MINUTES = 10

# Seconds to wait for an app to come to the foreground after launch.
LAUNCH_TIMEOUT = 20

# Default per-task time limit in seconds (a task can override with `timeout`).
DEFAULT_TASK_TIMEOUT = 300

# Put the phone back to sleep after the run.
SLEEP_AFTER_RUN = True

# Switch off all on-screen keyboards (incl. voice typing) at the start of every session; they come back on
# after reboots / app updates. Set False to keep them.
DISABLE_KEYBOARDS = True

# --- screen reading -----------------------------------------------------------
OCR_LANG = "eng"          # tesseract language(s), e.g. "eng+hin" (needs tesseract-ocr-hin)
OCR_MIN_CONF = 40         # ignore OCR words below this confidence (0-100)
MATCH_THRESHOLD = 0.85    # template-match score needed to count as found (0-1)
POLL_INTERVAL = 0.3       # seconds between screenshots while waiting for something
MONKEY_PORT = 1080        # local port for fast input (Android's built-in `monkey --port`)

LOG_DIR = BASE_DIR / "logs"
FAILURE_DIR = LOG_DIR / "failures"   # screenshot + OCR text saved here when a job fails
FAILURE_KEEP_DAYS = 7                # failure snapshots older than this are deleted
FAILURE_KEEP_MAX = 20                # ...and only the newest this many are kept
TEMPLATE_DIR = BASE_DIR / "templates"  # icon/button images for image= (make them with tools.py crop)
STATE_FILE = BASE_DIR / "state.json"   # last-run times per task
LOCK_FILE = BASE_DIR / ".runner.lock"
SCROLL_MEMORY_FILE = BASE_DIR / "scroll_memory.json"   # how many swipes each scroll_to needed last time
PAUSE_FILE = BASE_DIR / "pause.json"   # while it exists (and hasn't expired) no sessions start

# Pause lengths: `run.py --pause` without a duration, and after the game says the account
# was logged in on another device (you're playing on your own phone).
DEFAULT_PAUSE_MINUTES = 60
SESSION_TAKEN_PAUSE_MINUTES = 60
