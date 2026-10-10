#!/usr/bin/env python3
"""Helpers for building Kingshot jobs over SSH (the phone's own screen is not needed).

    tools.py ocr [x1 y1 x2 y2]        all text on screen with tap coordinates (region optional)
    tools.py find "text" [x1 y1 x2 y2] where is this text? (same matching as jobs use)
    tools.py shot [file.png]          save a screenshot (default screen.png)
    tools.py crop x1 y1 x2 y2 NAME    cut a piece of the screen into templates/NAME.png
    tools.py template FILE NAME [x1 y1 x2 y2]
                                      import an icon from any screenshot (e.g. a PC/Mac one): find it on
                                      the live screen at any size and save the phone's own pixels as
                                      templates/NAME.png
    tools.py findimg NAME             where is templates/NAME.png on screen?
    tools.py tap X Y                  tap a point
    tools.py swipe X1 Y1 X2 Y2 [ms]   swipe
    tools.py back | home              press Back / Home
    tools.py text "hello"             type into the focused field
    tools.py app                      package in the foreground
    tools.py packages [filter]        installed packages
    tools.py wake | sleep             screen on (and unlock) / off

Coordinates are pixels; fractions like 0.5 also work (x 0-1, y 0-1).
"""
import sys
import time

import config
from core import vision
from core.phone import Phone, PhoneError
from core.vision import Region


def _num(s: str) -> float:
    return float(s) if "." in s else int(s)


def _region(argv: list[str]) -> Region | None:
    if len(argv) < 4:
        return None
    x1, y1, x2, y2 = (_num(v) for v in argv[:4])
    return x1, y1, x2, y2


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, args = argv[0], argv[1:]
    try:
        p = Phone(config.DEVICE_SERIAL, config.UNLOCK_PIN, config.LAUNCH_TIMEOUT)
    except PhoneError as e:
        print(e)
        return 1

    if cmd == "ocr":
        t = time.monotonic()
        lines = vision.ocr_lines(p.screen(), _region(args))
        for m in lines:
            print(m)
        print(f"-- {len(lines)} lines in {time.monotonic() - t:.1f}s  "
              f"([light] = found by the white-text pass)  screen {p.width}x{p.height}")
    elif cmd == "find":
        if not args:
            print('usage: tools.py find "text" [x1 y1 x2 y2]')
            return 2
        m = vision.find_text(p.screen(), args[0], _region(args[1:]))
        print(m if m else f"not found: {args[0]!r}")
        return 0 if m else 1
    elif cmd == "shot":
        path = args[0] if args else "screen.png"
        p.screenshot(path)
        print(f"saved {path} ({p.width}x{p.height})")
    elif cmd == "crop":
        if len(args) != 5:
            print("usage: tools.py crop x1 y1 x2 y2 NAME")
            return 2
        import cv2
        shot = p.screen()
        part, _ = vision.crop(shot, _region(args))
        config.TEMPLATE_DIR.mkdir(exist_ok=True)
        out = config.TEMPLATE_DIR / f"{args[4]}.png"
        cv2.imwrite(str(out), part)
        m = vision.find_image(shot, out)
        print(f"saved {out} ({part.shape[1]}x{part.shape[0]}); self-check: {m or 'NOT matched'}")
    elif cmd == "template":
        if len(args) < 2:
            print("usage: tools.py template FILE NAME [x1 y1 x2 y2]")
            return 2
        import cv2
        import numpy as np
        img = p.screen()
        scales = tuple(np.round(np.arange(1.0, 4.01, 0.05), 2))   # PC screenshots are smaller than the phone; tiny scales give false hits
        m = vision.find_image(img, args[0], _region(args[2:]), threshold=0.01, scales=scales)
        if not m or m.score < 0.6:
            print(f"could not find {args[0]} on screen (best score {m.score if m else 0:.2f}); "
                  f"is the right screen showing?")
            return 1
        part, _ = vision.crop(img, m.box)
        out = config.TEMPLATE_DIR / f"{args[1]}.png"
        config.TEMPLATE_DIR.mkdir(exist_ok=True)
        cv2.imwrite(str(out), part)
        src = cv2.imread(args[0])
        src_w = src.shape[1] if src is not None else m.w
        print(f"found at {m.center} (scale x{m.w / src_w:.2f}, score {m.score:.2f})")
        print(f"saved {out} ({m.w}x{m.h}, phone pixels); self-check: {vision.find_image(img, out)}")
    elif cmd == "findimg":
        if not args:
            print("usage: tools.py findimg NAME [x1 y1 x2 y2]")
            return 2
        m = vision.find_image(p.screen(), args[0], _region(args[1:]), threshold=0.01)
        if m and m.score >= config.MATCH_THRESHOLD:
            print(m)
        else:
            print(f"not found (best score {m.score:.2f} < {config.MATCH_THRESHOLD})" if m else "not found")
            return 1
    elif cmd == "tap":
        p.tap_xy(_num(args[0]), _num(args[1]))
        print("tapped", p._xy(_num(args[0]), _num(args[1])))
    elif cmd == "swipe":
        p.swipe(*(_num(a) for a in args[:4]), ms=int(args[4]) if len(args) > 4 else 300)
    elif cmd == "back":
        p.back()
    elif cmd == "home":
        p.home()
    elif cmd == "text":
        p.type_text(args[0])
    elif cmd == "app":
        print(p.current_app() or "unknown")
    elif cmd == "packages":
        print("\n".join(p.packages(args[0] if args else "")))
    elif cmd == "wake":
        p.wake()
        print("screen on:", p.is_screen_on(), "| locked:", p.is_locked())
    elif cmd == "sleep":
        p.sleep()
        print("screen on:", p.is_screen_on())
    else:
        print(f"unknown command {cmd!r}\n{__doc__}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))   # (Phone stops its fast-input helper on exit by itself)
