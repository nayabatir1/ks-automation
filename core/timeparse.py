"""Turn countdown text read from the screen into a timedelta.

    parse_duration("03:12:45")        -> 3:12:45
    parse_duration("12:30")           -> 0:12:30   (two parts = mm:ss; two_part="hm" for hh:mm)
    parse_duration("1d 4h 20m")       -> 1 day, 4:20:00
    parse_duration("Next free: 1d 07:59:52") -> 1 day, 7:59:52  ("Id" / "ld" too: OCR)
    parse_duration("Next in 2h 5min") -> 2:05:00
    parse_duration("Ready")           -> None
"""
import re
from datetime import timedelta

_UNITS = {"d": 86400, "day": 86400, "days": 86400,
          "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
          "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
          "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1}

# OCR often reads these letters inside clock-style numbers
_OCR_DIGIT_FIX = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "|": "1"})


def parse_duration(text: str, two_part: str = "ms") -> timedelta | None:
    if not text:
        return None
    total, found = 0, False

    # clock style: 1:02:03 or 12:30 (fix OCR letter/digit mix-ups first)
    clock = re.search(r"[\dOolI|]{1,3}(?:\s*:\s*[\dOolI|]{2}){1,2}", text)
    if clock:
        parts = [int(p) for p in re.sub(r"\s", "", clock.group().translate(_OCR_DIGIT_FIX)).split(":")]
        if len(parts) == 3:
            h, m, s = parts
        elif two_part == "hm":
            h, m, s = parts[0], parts[1], 0
        else:
            h, m, s = 0, parts[0], parts[1]
        total += h * 3600 + m * 60 + s
        found = True
        text = text[:clock.start()] + " " + text[clock.end():]

    # unit style: 1d 4h 20m 5s / 2 hours 5 min
    text = re.sub(r"(?<![A-Za-z])[Il|]d\b", "1d", text)          # OCR reads "1d" as "Id" / "ld"
    for num, unit in re.findall(r"(\d+)\s*([a-zA-Z]+)", text):
        mult = _UNITS.get(unit.lower())
        if mult:
            total += int(num) * mult
            found = True

    return timedelta(seconds=total) if found else None
