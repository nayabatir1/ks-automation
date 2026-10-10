"""The game definition (game.py) subclasses Task; each job is a function marked @job.

Layout in this project, one file per job:

    game.py              class Kingshot(Task): package, on_open/before_job, shared helpers
                         jobs_package = "jobs"
    jobs/chest.py        @job(...)
                         def chest(app, phone, log): ...      (app = the Kingshot instance)

Every file in jobs/ (not starting with "_") is picked up. The app is opened once and every
job that is due runs in that session. A job says when it can run next by returning:
    timedelta(hours=3, minutes=12)   -> 3h12m from now (e.g. a countdown read from the screen)
    a datetime                       -> exactly then (naive = config.SCHEDULE_TZ)
    None                             -> next slot of its schedule= (or retry_minutes if it has none)
A failed job is retried after retry_minutes. A job that never ran is due straight away.

(A Task can also be a simple one-off with run() and schedule=; the runner still supports that.)
"""
from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.phone import Phone
    from core.schedule import Schedule

log = logging.getLogger("task")


def job(schedule: Schedule | None = None, *, priority: int = 100, timeout: int | None = None, retry_minutes: int = 30,
        enabled: bool = True) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark a function in a jobs/ file (or a Task method) as a job. See the module docstring."""
    def deco(func: Any) -> Any:
        func._job = {"schedule": schedule, "priority": priority, "timeout": timeout,
                     "retry_minutes": retry_minutes, "enabled": enabled}
        return func
    return deco


@dataclass
class Job:
    name: str
    func: Callable[..., Any]
    schedule: Schedule | None
    priority: int
    timeout: int | None
    retry_minutes: int
    enabled: bool


class Task:
    # Unique name used on the command line (--task NAME). Defaults to the class name in snake_case.
    name: str | None = None
    # App package to open before run() and close after. None = runner won't launch anything.
    package: str | None = None
    # Optional specific activity to start, e.g. "com.app/.MainActivity" (usually leave None).
    activity: str | None = None
    # Simple tasks: Every(...), At(...) or Cron(...) from core.schedule. None = only when run manually.
    # (Tasks with @job methods ignore this; each job has its own timing.)
    schedule = None
    # When several tasks are due at once, lower numbers run first.
    priority: int = 100
    # Max seconds run() may take (for @job tasks: each job, unless the job sets its own).
    timeout: int | None = None
    # Set False to stop the scheduler picking it (you can still run it with --task).
    enabled: bool = True
    # Force-stop the app after the task (also after a failure).
    close_app: bool = True
    # run.py --part: only these parts of a job made of parts (e.g. jobs/dailies.py); None = all of them.
    parts: list[str] | None = None
    # If the app is already in the foreground, keep using it instead of restarting it.
    # The runner sets self.app_was_open before on_open() so it can skip the loading screens.
    reuse_open_app: bool = False
    app_was_open: bool = False
    # Set by the runner before each job: the next run time that job had stored (None if never run).
    previous_next_at: datetime | None = None
    # @job tasks: after the due jobs, the app stays open only if the next job (any job, or the same one again)
    # is due within this many seconds; otherwise it is closed. A session lasts at most max_session_minutes.
    session_wait_seconds: int = 10
    max_session_minutes: int = 20
    # Max seconds for launching the app + on_open() (loading screens, pop-ups).
    open_timeout: int = 180
    # Package holding one file per job, e.g. f"{__package__}.jobs". None = only @job methods.
    jobs_package: str | None = None

    # ------------------------------------------------------------------ hooks (the runner calls these)
    # Every session:  launch app -> on_open() -> [before_job() -> job -> after_job()] ... -> close app (always)
    def on_open(self, phone: Phone, log: logging.Logger) -> None:
        """Right after every app launch (also after a crash-restart): wait for loading, clear pop-ups.
        Default: nothing. Override per app."""

    def before_job(self, phone: Phone, log: logging.Logger) -> None:
        """Before each job (and before run()): make sure the app is on its main screen.
        Default: nothing. Override per app."""

    def after_job(self, phone: Phone, log: logging.Logger) -> None:
        """After each job that went well: leave the job's pages. Default: nothing. Override per app."""

    def run(self, phone: Phone, log: logging.Logger) -> Any:
        """Simple tasks: do the work. The phone is awake and the app is already open in the foreground.

        phone: core.phone.Phone   (wait_for, tap, wait_any, read_text, ... — see core/phone.py)
        log:   logging.Logger
        Raise any exception to mark the task as failed.
        """
        raise NotImplementedError

    def session_taken(self, phone: Phone) -> bool:
        """Called after a failure: does the screen say the account is now in use on another device?
        If True the runner closes the app, does NOT reconnect, and pauses (see core/pause.py)."""
        return False

    def recover(self, phone: Phone, log: logging.Logger) -> None:
        """Called after a job fails, before the next job: get back to a known screen.
        Default: restart the app (which runs on_open again). Override if the app needs something smarter."""
        self.app_was_open = False
        if self.package:
            phone.launch(self.package, self.activity)
        self.on_open(phone, log)

    # ------------------------------------------------------------------
    @classmethod
    def task_name(cls) -> str:
        return cls.name or re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower()

    @classmethod
    def job_list(cls) -> list[Job]:
        """All jobs (jobs_package files + @job methods), ordered by (priority, name). Empty for simple tasks."""
        if "_jobs" not in cls.__dict__:
            funcs = {}
            for attr in dir(cls):
                fn = getattr(cls, attr, None)
                if callable(fn) and hasattr(fn, "_job"):
                    funcs[attr] = fn
            for name, fn in cls._package_jobs().items():
                if name in funcs:
                    raise RuntimeError(f"{cls.__name__}: job '{name}' is defined twice")
                funcs[name] = fn
            cls._jobs = sorted((Job(name=n, func=f, **f._job) for n, f in funcs.items()),
                               key=lambda j: (j.priority, j.name))
        return cls._jobs

    @classmethod
    def _package_jobs(cls) -> dict:
        """Functions marked @job in the files of jobs_package (files starting with "_" are ignored).
        A file that fails to import is logged and skipped, so one broken job can't stop the others."""
        if not cls.jobs_package:
            return {}
        pkg = importlib.import_module(cls.jobs_package)
        found = {}
        for mod in pkgutil.iter_modules(pkg.__path__):
            if mod.name.startswith("_"):
                continue
            try:
                module = importlib.import_module(f"{cls.jobs_package}.{mod.name}")
            except Exception:
                log.exception("Could not import job file %s/%s.py — skipping it",
                              cls.jobs_package.replace(".", "/"), mod.name)
                continue
            for name, fn in inspect.getmembers(module, inspect.isfunction):
                if hasattr(fn, "_job") and fn.__module__ == module.__name__:
                    if name in found:
                        raise RuntimeError(f"{cls.__name__}: job '{name}' is defined twice")
                    found[name] = fn
        return found


def run_parts(app: Task, phone: Phone, log: logging.Logger, parts: dict[str, Callable[..., Any]]) -> None:
    """Run a job made of parts ({name: function(app, phone, log)}) in order, or only the ones picked with
    run.py --part (app.parts)."""
    unknown = set(app.parts or ()) - set(parts)
    if unknown:
        raise ValueError(f"no part {', '.join(sorted(unknown))}; parts: {', '.join(parts)}")
    for name, part in parts.items():
        if app.parts is None or name in app.parts:
            log.info("part: %s", name)
            part(app, phone, log)
