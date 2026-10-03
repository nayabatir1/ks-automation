"""Schedule types a task can use.

    Every(minutes=30)                                   every 30 min (slots :00, :30)
    Every(hours=2, between=("08:00", "22:00"))          08:00, 10:00 ... 22:00
    At("09:00", "21:30")                                fixed times each day
    At("07:45", days=["mon", "tue", "wed", "thu", "fri"])
    Cron("*/15 9-17 * * mon-fri")                       standard 5-field cron

Every schedule takes tz= (e.g. tz="Asia/Kolkata"); without it config.SCHEDULE_TZ is
used. The server's own timezone never matters.

A schedule is a list of *slots* (exact times). A task is due when the latest slot
is at most `grace_minutes` ago and the task hasn't run since that slot — so a slot
missed by a reboot still runs, and no slot ever runs twice.
"""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import config

DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MONTH_NAMES = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def _parse_days(days):
    if days is None:
        return set(range(7))
    if isinstance(days, str):
        days = [days]
    return {d if isinstance(d, int) else DAY_NAMES.index(d.lower()[:3]) for d in days}


def _parse_hhmm(s):
    h, m = s.split(":")
    return time(int(h), int(m))


class Schedule:
    """Base class. Subclasses implement _slots_on(day) -> local datetimes whose slot belongs to `day`."""

    def __init__(self, tz=None, grace_minutes=None):
        self.tz_name = tz or config.SCHEDULE_TZ
        self.tz = ZoneInfo(self.tz_name)
        self.grace = timedelta(minutes=config.DEFAULT_GRACE_MINUTES if grace_minutes is None
                               else grace_minutes)

    def _slots_on(self, day: date) -> list[datetime]:
        raise NotImplementedError

    def _local(self, day: date, t: time) -> datetime:
        return datetime.combine(day, t, tzinfo=self.tz)

    def prev_slot(self, now: datetime, max_days=3) -> datetime | None:
        """Latest slot <= now, looking back at most max_days."""
        today = now.astimezone(self.tz).date()
        best = None
        for back in range(max_days + 1):
            for s in self._slots_on(today - timedelta(days=back)):
                if s <= now and (best is None or s > best):
                    best = s
            # a slot from the day before can still be later (window crossing midnight), so
            # only stop once a full extra day has been checked after the first hit
            if best is not None and back >= 1:
                break
        return best

    def next_slot(self, now: datetime, max_days=1500) -> datetime | None:
        """Earliest slot > now (for --list)."""
        today = now.astimezone(self.tz).date()
        best = None
        for fwd in range(-1, max_days):
            for s in self._slots_on(today + timedelta(days=fwd)):
                if s > now and (best is None or s < best):
                    best = s
            if best is not None and fwd >= 1:
                break
        return best

    def is_due(self, now: datetime, last_run: datetime | None) -> bool:
        slot = self.prev_slot(now)
        if slot is None or now - slot > self.grace:
            return False
        return last_run is None or last_run < slot

    def _tz_suffix(self):
        return f" {self.tz_name}"


class At(Schedule):
    def __init__(self, *times, days=None, tz=None, grace_minutes=None):
        super().__init__(tz, grace_minutes)
        if not times:
            raise ValueError("At() needs at least one 'HH:MM'")
        self.times = sorted(_parse_hhmm(t) for t in times)
        self.days = _parse_days(days)

    def _slots_on(self, day):
        if day.weekday() not in self.days:
            return []
        return [self._local(day, t) for t in self.times]

    def __str__(self):
        s = "at " + ",".join(f"{t:%H:%M}" for t in self.times)
        if self.days != set(range(7)):
            s += " " + ",".join(DAY_NAMES[d] for d in sorted(self.days))
        return s + self._tz_suffix()


class Every(Schedule):
    """Slots start at the window start (or midnight) and repeat every interval until the window end."""

    def __init__(self, minutes=0, hours=0, days=None, between=None, tz=None, grace_minutes=None):
        super().__init__(tz, grace_minutes)
        self.interval = timedelta(minutes=minutes, hours=hours)
        if self.interval <= timedelta(0):
            raise ValueError("Every() needs minutes or hours > 0")
        self.days = _parse_days(days)
        self.between = tuple(_parse_hhmm(t) for t in between) if between else None

    def _slots_on(self, day):
        if day.weekday() not in self.days:
            return []
        if self.between:
            start, end = self.between
            first = self._local(day, start)
            last = self._local(day, end)
            if end < start:                       # window crosses midnight, e.g. 22:00-02:00
                last += timedelta(days=1)
        else:
            first = self._local(day, time(0, 0))
            last = first + timedelta(days=1) - timedelta(seconds=1)
        out, s = [], first
        while s <= last:
            out.append(s)
            s += self.interval
        return out

    def __str__(self):
        mins = int(self.interval.total_seconds() // 60)
        s = f"every {mins // 60}h" if mins % 60 == 0 else f"every {mins}min"
        if self.between:
            s += f" {self.between[0]:%H:%M}-{self.between[1]:%H:%M}"
        if self.days != set(range(7)):
            s += " " + ",".join(DAY_NAMES[d] for d in sorted(self.days))
        return s + self._tz_suffix()


class Cron(Schedule):
    """Standard 5-field cron: minute hour day-of-month month day-of-week.

    Supports *, lists (1,5), ranges (1-5), steps (*/15, 8-18/2), names (jan, mon).
    Day-of-week: 0 or 7 = Sunday. As in real cron, if both day-of-month and day-of-week
    are restricted, a day matches when either one does.
    """

    def __init__(self, expr, tz=None, grace_minutes=None):
        super().__init__(tz, grace_minutes)
        self.expr = expr
        fields = expr.split()
        if len(fields) != 5:
            raise ValueError(f"Cron needs 5 fields, got {len(fields)}: {expr!r}")
        self.minutes = self._field(fields[0], 0, 59)
        self.hours = self._field(fields[1], 0, 23)
        self.dom = self._field(fields[2], 1, 31)
        self.months = self._field(fields[3], 1, 12, MONTH_NAMES, 1)
        dow = self._field(fields[4], 0, 7, ["sun", "mon", "tue", "wed", "thu", "fri", "sat"], 0)
        self.dow = {d % 7 for d in dow}                    # cron numbering: 0 = Sunday
        self.dom_any = fields[2] == "*"
        self.dow_any = fields[4] == "*"
        self.times = sorted(time(h, m) for h in self.hours for m in self.minutes)

    @staticmethod
    def _field(text, lo, hi, names=None, name_base=0):
        def num(s):
            s = s.lower()
            if names and s[:3] in names:
                return names.index(s[:3]) + name_base
            return int(s)

        out = set()
        for part in text.split(","):
            rng, _, step = part.partition("/")
            step = int(step) if step else 1
            if rng == "*":
                a, b = lo, hi
            elif "-" in rng:
                a, b = (num(x) for x in rng.split("-", 1))
            else:
                a = num(rng)
                b = hi if step > 1 else a
            if not (lo <= a <= hi and lo <= b <= hi) or step < 1:
                raise ValueError(f"Cron field {text!r} out of range {lo}-{hi}")
            out.update(range(a, b + 1, step))
        return out

    def _day_matches(self, day):
        if day.month not in self.months:
            return False
        dom_ok = day.day in self.dom
        dow_ok = (day.weekday() + 1) % 7 in self.dow       # python Mon=0 -> cron Mon=1
        if self.dom_any and self.dow_any:
            return True
        if self.dom_any:
            return dow_ok
        if self.dow_any:
            return dom_ok
        return dom_ok or dow_ok

    def _slots_on(self, day):
        if not self._day_matches(day):
            return []
        return [self._local(day, t) for t in self.times]

    def __str__(self):
        return f"cron '{self.expr}'" + self._tz_suffix()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
