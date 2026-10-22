"""On / off switches for jobs and their parts, from jobs.toml (read on every run, so an edit counts at once).

    [jobs]
    farming = false          # this job doesn't run

    [parts.dailies]
    nomadic_merchant = false # this part of dailies is skipped

Anything not in the file (or no file at all) is on. run.py --job / --part still run what they're asked for.
"""

from __future__ import annotations

import logging
import tomllib

import config

SWITCHES_FILE = config.BASE_DIR / "jobs.toml"
log = logging.getLogger("switches")


def _load() -> dict:
    try:
        with SWITCHES_FILE.open("rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as e:  # a typo must not stop every job: everything stays on
        log.error("%s has a mistake (%s); all jobs and parts are on until it's fixed", SWITCHES_FILE.name, e)
        return {}


def job_on(job: str) -> bool:
    return bool(_load().get("jobs", {}).get(job, True))


def part_on(job: str, part: str) -> bool:
    return bool(_load().get("parts", {}).get(job, {}).get(part, True))


def settings(job: str, name: str) -> dict:
    """A job's own settings table, e.g. settings("troops_training", "quantity") = [troops_training.quantity]."""
    table = _load().get(job, {}).get(name, {})
    return table if isinstance(table, dict) else {}
