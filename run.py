#!/usr/bin/env python3
"""Main runner. The systemd timer starts this every minute; it decides what is due.

Simple task due:  wake + unlock -> launch app -> on_open() -> before_job() -> run() -> close app
@job task due:    wake + unlock -> launch app -> on_open() -> [before_job() -> job -> after_job()] for each due job
                  (lowest priority first) -> close app
                  (the app stays open only if the next job is due within session_wait_seconds = 10 s)
After everything: put phone to sleep

Usage:
    run.py                          run whatever is due now (this is what the timer calls)
    run.py --list                   jobs, schedule, next run (IST + UTC), last result
    run.py --timeline               every job in order of when it runs next
    run.py --dry-run                show what would run now, touch nothing
    run.py --job NAME               run one job now, ignoring its next-run time
    run.py --task kingshot          run all jobs now
    ... --no-sleep                  leave the screen on afterwards (debugging)
    ... --keep-open                 leave the app open afterwards (building jobs step by step)
"""
import argparse
import fcntl
import logging
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo

import config
from core import pause
from core.loader import load_tasks
from core.phone import Phone, PhoneError, device_state
from core.schedule import utcnow
from core.state import State

log = logging.getLogger("runner")
IST = ZoneInfo("Asia/Kolkata")


class TaskTimeout(BaseException):  # BaseException so a task's own `except Exception` can't swallow it
    pass


def setup_logging(verbose):
    config.LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)sZ %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    fmt.converter = time.gmtime   # log times in UTC, like state.json
    file_h = RotatingFileHandler(config.LOG_DIR / "runner.log", maxBytes=2_000_000, backupCount=5)
    file_h.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(file_h)
    root.addHandler(console)
    for noisy in ("PIL", "pytesseract"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def acquire_lock():
    """Only one runner at a time — if a long task is still going, the next tick just exits."""
    fh = open(config.LOCK_FILE, "w")  # noqa: SIM115 — must stay open for the whole run: it *is* the lock
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return None
    return fh


def save_failure(phone, name):
    """Screenshot + all OCR text with coordinates, so you can debug from the terminal. Old ones are pruned."""
    config.FAILURE_DIR.mkdir(parents=True, exist_ok=True)
    base = f"{config.FAILURE_DIR}/{name}_{utcnow():%Y%m%d-%H%M%S}"   # not with_suffix: names contain dots
    try:
        img = phone.screen()            # what the screen shows *now*
        import cv2
        cv2.imwrite(f"{base}.jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        phone.save_ocr(Path(f"{base}.txt"), img)
        log.info("Saved %s.jpg and %s.txt (OCR text with tap coordinates)", base, base)
    except Exception as e:  # noqa: BLE001 — a failure snapshot must never crash the runner
        log.warning("Could not save failure snapshot: %s", e)
    prune_failures()


def prune_failures():
    """Delete failure snapshots older than FAILURE_KEEP_DAYS, and all but the newest FAILURE_KEEP_MAX."""
    files = sorted(config.FAILURE_DIR.glob("*"), key=lambda f: f.stat().st_mtime, reverse=True)
    snapshots = {}                              # snapshot name -> its files (.jpg/.png + .txt)
    for f in files:
        snapshots.setdefault(f.stem, []).append(f)
    cutoff = time.time() - config.FAILURE_KEEP_DAYS * 86400
    for i, group in enumerate(snapshots.values()):  # newest first
        if i >= config.FAILURE_KEEP_MAX or max(f.stat().st_mtime for f in group) < cutoff:
            for f in group:
                f.unlink(missing_ok=True)


def check_session_taken(phone, task, name):
    """After a failure: is the account in use on another device (you're playing)? Then pause and don't fight
    for the session — reconnecting would kick you off. The jobs stay due and run after the pause."""
    try:
        taken = task.session_taken(phone)
    except Exception:  # noqa: BLE001 — this check must never turn into a failure of its own
        taken = False
    if taken:
        until = pause.pause_for(timedelta(minutes=config.SESSION_TAKEN_PAUSE_MINUTES),
                                "account logged in on another device")
        log.warning("=== %s: the account is in use on another device; not reconnecting, paused until %s",
                    name, _fmt_both(until))
    return taken


def phone_connected(manual):
    """First thing every run: is the phone there? If not, no job runs and no job state changes, so everything
    due simply runs once it's back. Timer runs log this once when the phone goes away and once when it returns."""
    state = device_state(config.DEVICE_SERIAL)
    marker = config.LOG_DIR / ".phone_offline"
    if state == "device":
        if marker.exists():
            marker.unlink()
            log.info("Phone is connected again")
        return True
    if manual:
        log.error("Phone not connected (%s). Check `adb devices`.", state)
    elif not marker.exists():
        marker.write_text(state)
        log.warning("Phone not connected (%s); no jobs run until it is back", state)
    return False


def _on_alarm(signum, frame):
    raise TaskTimeout()


def call_with_timeout(seconds, fn, label):
    """Run fn() with a hard time limit. Returns (status, error, result)."""
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(seconds)
    try:
        return "ok", None, fn()
    except TaskTimeout:
        signal.alarm(0)
        log.error("=== %s: TIMEOUT after %ss", label, seconds)
        return "timeout", f"exceeded {seconds}s", None
    except Exception as e:
        signal.alarm(0)
        log.exception("=== %s: FAILED", label)
        return "error", f"{type(e).__name__}: {e}", None
    finally:
        signal.alarm(0)   # before any cleanup, so the alarm can't fire inside it


def close_app(phone, task):
    if task.package and task.close_app:
        try:
            phone.close(task.package)
        except PhoneError as e:
            log.warning("Could not close %s: %s", task.package, e)


def open_app(phone, task, tlog):
    phone.wake()  # again per task: a long previous task may have let the screen time out
    if config.DISABLE_KEYBOARDS:
        phone.disable_keyboards()
    task.app_was_open = bool(task.package and task.reuse_open_app and phone.current_app() == task.package)
    if task.app_was_open:
        log.info("%s is already open; using it as it is", task.package)
    elif task.package:
        phone.launch(task.package, task.activity)
    phone.start_input()          # get fast taps ready while the app loads
    task.on_open(phone, tlog)


# ------------------------------------------------------------------ simple tasks
def run_simple(phone, name, task, state):
    tlog = logging.getLogger(f"task.{name}")
    timeout = task.timeout or config.DEFAULT_TASK_TIMEOUT
    started, t0 = utcnow(), time.monotonic()
    log.info("=== %s: start (timeout %ss)", name, timeout)

    status, error, _ = call_with_timeout(task.open_timeout, lambda: open_app(phone, task, tlog), f"{name}.open")
    if status == "ok":
        def work():
            task.before_job(phone, tlog)
            task.run(phone, tlog)
        status, error, _ = call_with_timeout(timeout, work, name)
    try:
        if status != "ok":
            save_failure(phone, name)
    finally:
        close_app(phone, task)

    secs = time.monotonic() - t0
    state.record(name, started, status, error, secs)
    if status == "ok":
        log.info("=== %s: done in %.1fs", name, secs)
    return status == "ok"


# ------------------------------------------------------------------ @job tasks
def first_run(j, now):
    """When a job that never ran is first due: straight away, or its first slot if it has a fixed schedule."""
    if j.schedule and not j.schedule.is_due(now, None):
        return j.schedule.next_slot(now)
    return datetime.min.replace(tzinfo=timezone.utc)


def due_jobs(name, task, state, now, ahead=timedelta(0)):
    """Enabled jobs whose next_at has come, in run order. Never run = due now, or at its first scheduled slot."""
    def when(j):
        return state.next_at(f"{name}.{j.name}") or first_run(j, now)
    out = [j for j in task.job_list() if j.enabled and when(j) <= now + ahead]
    return sorted(out, key=lambda j: (j.priority, when(j)))


def next_time(job, result):
    """What a job returned -> when it may run next (aware datetime)."""
    now = utcnow()
    if isinstance(result, timedelta):
        return now + result
    if isinstance(result, datetime):
        return result if result.tzinfo else result.replace(tzinfo=ZoneInfo(config.SCHEDULE_TZ))
    if result is not None:
        raise TypeError(f"job {job.name} returned {result!r}; return a timedelta, a datetime or None")
    if job.schedule:
        return job.schedule.next_slot(now)
    log.warning("job %s returned no next time and has no schedule; retrying in %s min",
                job.name, job.retry_minutes)
    return now + timedelta(minutes=job.retry_minutes)


def run_jobs(phone, name, task, state, jobs, wait=True):
    """One app session: open the app and run the due jobs. If the next job (any job) is due within
    session_wait_seconds, keep the app open and run it too; otherwise close the app (max_session_minutes cap)."""
    log.info("=== %s: %d job(s): %s", name, len(jobs), ", ".join(j.name for j in jobs))
    tlog = logging.getLogger(f"task.{name}")
    status, error, _ = call_with_timeout(task.open_timeout, lambda: open_app(phone, task, tlog), f"{name}.open")
    if status != "ok":
        if check_session_taken(phone, task, name):
            close_app(phone, task)
            return True                     # not an error: jobs stay due and run after the pause
        # can't even open the app: push every job back by its retry time (no hammering every minute)
        try:
            save_failure(phone, name)
        finally:
            close_app(phone, task)
        for j in jobs:
            state.record(f"{name}.{j.name}", utcnow(), status, f"app did not open: {error}", 0,
                         utcnow() + timedelta(minutes=j.retry_minutes))
        return False

    ok = True
    session_end = time.monotonic() + task.max_session_minutes * 60
    try:
        while jobs:
            batch_ok, app_lost = run_batch(phone, name, task, state, jobs, tlog)
            ok &= batch_ok
            if app_lost or not wait:
                break
            jobs = wait_for_next_jobs(name, task, state, session_end)
    finally:
        close_app(phone, task)
    return ok


def run_batch(phone, name, task, state, jobs, tlog):
    """Run these jobs one after another. Returns (all ok, app could not be recovered)."""
    ok = True
    for i, j in enumerate(jobs):
        if pause.get():
            log.info("=== %s: paused; stopping this session", name)
            return ok, True
        key = f"{name}.{j.name}"
        jlog = logging.getLogger(f"job.{key}")
        timeout = j.timeout or task.timeout or config.DEFAULT_TASK_TIMEOUT
        started, t0 = utcnow(), time.monotonic()
        log.info("--- %s: start (timeout %ss)", key, timeout)

        task.previous_next_at = state.next_at(key)

        def work(j=j, jlog=jlog):
            task.before_job(phone, jlog)
            result = j.func(task, phone, jlog)
            task.after_job(phone, jlog)
            return next_time(j, result)
        status, error, nxt = call_with_timeout(timeout, work, key)
        secs = time.monotonic() - t0
        if status != "ok" and check_session_taken(phone, task, name):
            return ok, True                 # job state untouched: it runs again after the pause
        if status != "ok":
            ok = False
            nxt = utcnow() + timedelta(minutes=j.retry_minutes)
            save_failure(phone, key)
        state.record(key, started, status, error, secs, nxt)
        log.info("--- %s: %s in %.1fs, next %s", key, status, secs, _fmt_both(nxt))

        if status != "ok" and i < len(jobs) - 1:
            r_status, _, _ = call_with_timeout(task.open_timeout,
                                               lambda: task.recover(phone, tlog), f"{name}.recover")
            if r_status != "ok":
                log.error("=== %s: could not recover the app; remaining jobs wait for the next run", name)
                return False, True
    return ok, False


def wait_for_next_jobs(name, task, state, session_end):
    """Jobs (any of them) due within session_wait_seconds: sleep until the first is due and return what's due
    then. Returns [] (-> the app gets closed) when nothing is due that soon or the session has run long enough."""
    soon = due_jobs(name, task, state, utcnow(), timedelta(seconds=task.session_wait_seconds))
    if not soon or pause.get():
        return []
    first = min(state.next_at(f"{name}.{j.name}") or utcnow() for j in soon)
    wait_s = max(0.0, (first - utcnow()).total_seconds())
    if time.monotonic() + wait_s > session_end:
        log.info("=== %s: session has run %d min; the rest waits for the next run", name, task.max_session_minutes)
        return []
    if wait_s > 0:
        log.info("=== %s: %s due in %.0fs; keeping the app open", name,
                 ", ".join(j.name for j in soon), wait_s)
        time.sleep(wait_s)
    return due_jobs(name, task, state, utcnow()) or soon


# ------------------------------------------------------------------ what's due
def is_due(name, task, state, now):
    if not task.enabled:
        return False
    if task.job_list():
        return bool(due_jobs(name, task, state, now))
    return bool(task.schedule and task.schedule.is_due(now, state.last_run(name)))


def _fmt(dt, tz):
    return dt.astimezone(tz).strftime("%m-%d %H:%M") if dt else "-"


def _fmt_both(dt):
    return f"{_fmt(dt, IST)} IST / {_fmt(dt, timezone.utc)} UTC" if dt else "-"


def _row(label, on, pri, sched, nxt, last, status):
    print(f"{label:30} {on:3} {pri:>3}  {sched:30} {_fmt(nxt, IST):11}  {_fmt(nxt, timezone.utc):11}  "
          f"{_fmt(last, timezone.utc):11}  {status}")


def _status(entry):
    s = entry.get("status", "-")
    return s + (f" ({entry['error'][:60]})" if entry.get("error") else "")


def job_next(name, j, state, now):
    """Next run of a job for display: its next_at, or (never ran) now / its first scheduled slot."""
    return state.next_at(f"{name}.{j.name}") or max(now, first_run(j, now))


def print_list(tasks, state, now):
    print(f"{'TASK / .job':30} {'ON':3} {'PRI':>3}  {'SCHEDULE':30} {'NEXT IST':11}  {'NEXT UTC':11}  "
          f"{'LAST RUN UTC':11}  STATUS")
    for name, t in tasks.items():
        on = "yes" if t.enabled else "no"
        jobs = t.job_list()
        if not jobs:
            nxt = t.schedule.next_slot(now) if (t.schedule and t.enabled) else None
            _row(name, on, t.priority, str(t.schedule or "manual only"), nxt,
                 state.last_run(name), _status(state.data.get(name, {})))
            continue
        _row(name, on, t.priority, f"{len(jobs)} jobs", None, None, "")
        for j in jobs:
            key = f"{name}.{j.name}"
            j_on = "yes" if (t.enabled and j.enabled) else "no"
            sched = str(j.schedule) if j.schedule else "when job says"
            nxt = job_next(name, j, state, now) if j_on == "yes" else None
            _row(f"  .{j.name}", j_on, j.priority, sched, nxt, state.last_run(key),
                 _status(state.data.get(key, {})))
    print(f"\nnow: {_fmt_both(now)}")


def print_timeline(tasks, state, now):
    """Everything enabled, in the order it will run."""
    items = []
    for name, t in tasks.items():
        if not t.enabled:
            continue
        if t.job_list():
            items += [(job_next(name, j, state, now), f"{name}.{j.name}") for j in t.job_list() if j.enabled]
        elif t.schedule:
            items.append((t.schedule.next_slot(now), name))
    items = sorted((i for i in items if i[0]), key=lambda i: i[0])
    print(f"{'WHEN IST':11}  {'WHEN UTC':11}  {'IN':>8}  WHAT")
    for when, what in items:
        mins = max(0, int((when - now).total_seconds() // 60))
        left = "due" if when <= now else (f"{mins // 60}h{mins % 60:02d}m" if mins >= 60 else f"{mins}m")
        print(f"{_fmt(when, IST):11}  {_fmt(when, timezone.utc):11}  {left:>8}  {what}")
    if not items:
        print("(nothing enabled)")


# ------------------------------------------------------------------ main
def set_pause(args):
    if args.resume:
        log.info("Resumed" if pause.resume() else "Was not paused")
        return 0
    from core.timeparse import parse_duration
    duration = parse_duration(args.pause, two_part="hm") if args.pause else \
        timedelta(minutes=config.DEFAULT_PAUSE_MINUTES)
    if not duration:
        log.error("Can't read duration %r; use e.g. 2h, 90m, 1h30m", args.pause)
        return 2
    until = pause.pause_for(duration, "paused by hand")
    log.info("Paused until %s; `run.py --resume` to end it sooner", _fmt_both(until))
    return 0


def main():
    ap = argparse.ArgumentParser(description="Android task runner")
    ap.add_argument("--task", help="run this task now, ignoring schedule")
    ap.add_argument("--job", help="run only this job now")
    ap.add_argument("--list", action="store_true", help="list jobs and exit")
    ap.add_argument("--timeline", action="store_true", help="show what runs next, in order")
    ap.add_argument("--dry-run", action="store_true", help="show what is due, don't run")
    ap.add_argument("--no-sleep", action="store_true", help="leave the screen on afterwards")
    ap.add_argument("--keep-open", action="store_true", help="don't close the app afterwards (building jobs)")
    ap.add_argument("--pause", nargs="?", const="", metavar="DURATION",
                    help=f"start no sessions for DURATION (e.g. 2h, 90m; default {config.DEFAULT_PAUSE_MINUTES}m)")
    ap.add_argument("--resume", action="store_true", help="end a pause now")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    setup_logging(args.verbose)
    if args.pause is not None or args.resume:
        return set_pause(args)
    tasks = load_tasks()
    state = State(config.STATE_FILE)
    now = utcnow()
    if args.keep_open:
        for t in tasks.values():
            t.close_app = False

    paused = pause.get()
    if args.list or args.timeline or args.dry_run:
        if paused:
            print(f"PAUSED until {_fmt_both(paused['until'])} ({paused['reason']}); `run.py --resume` to end it\n")
        if args.list:
            print_list(tasks, state, now)
            return 0
        if args.timeline:
            print_timeline(tasks, state, now)
            return 0
    elif paused:
        if args.task or args.job:
            log.error("Paused until %s (%s). Run `run.py --resume` first.", _fmt_both(paused["until"]),
                      paused["reason"])
            return 1
        return 0                            # timer runs: nothing while paused
    if not args.dry_run and not phone_connected(manual=bool(args.task or args.job)):
        return 1 if (args.task or args.job) else 0   # timer runs: quietly try again next minute

    forced_jobs = None
    if args.job and not args.task:   # --job alone: find the task that has it (there's only Kingshot)
        owners = [n for n, t in tasks.items() if any(j.name == args.job for j in t.job_list())]
        if not owners:
            log.error("No job named '%s'. Jobs: %s", args.job,
                      ", ".join(j.name for t in tasks.values() for j in t.job_list()) or "none")
            return 2
        args.task = owners[0]
    if args.task:
        if args.task not in tasks:
            log.error("No task named '%s'. Known: %s", args.task, ", ".join(tasks) or "none")
            return 2
        t = tasks[args.task]
        if args.job:
            names = [j.name for j in t.job_list()]
            if args.job not in names:
                log.error("Task '%s' has no job '%s'. Its jobs: %s", args.task, args.job,
                          ", ".join(names) or "none (simple task)")
                return 2
        if t.job_list():
            forced_jobs = [j for j in t.job_list() if (j.name == args.job if args.job else True)]
        due = [args.task]
    else:
        due = [n for n, t in tasks.items() if is_due(n, t, state, now)]

    if args.dry_run:
        print("Due now:", ", ".join(due) if due else "nothing")
        for n in due:
            if tasks[n].job_list():
                jobs = forced_jobs or due_jobs(n, tasks[n], state, now)
                print(f"  {n}: " + ", ".join(j.name for j in jobs))
        return 0
    if not due:
        return 0  # quiet exit — the timer calls us every minute

    lock = acquire_lock()
    if lock is None:
        log.info("Another run is still in progress; skipping this tick")
        return 0
    state = State(config.STATE_FILE)  # re-read under the lock: a run that just finished may have updated it
    if not args.task:
        due = [n for n in due if is_due(n, tasks[n], state, now)]
        if not due:
            return 0

    try:
        phone = Phone(config.DEVICE_SERIAL, config.UNLOCK_PIN, config.LAUNCH_TIMEOUT)
    except PhoneError as e:
        log.error(str(e))
        return 1

    ok = True
    try:
        for name in due:
            t = tasks[name]
            if t.job_list():
                jobs = forced_jobs if args.task else due_jobs(name, t, state, utcnow())
                if jobs:
                    ok &= run_jobs(phone, name, t, state, jobs, wait=not args.task)
            else:
                ok &= run_simple(phone, name, t, state)
    finally:
        phone.close_input()
        if config.SLEEP_AFTER_RUN and not args.no_sleep:
            try:
                phone.sleep()
            except PhoneError as e:
                log.warning("Could not put phone to sleep: %s", e)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
