import re
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pytesseract

import config
from core.phone import Phone


def resolve_region(region, shape):
    """region = (x1, y1, x2, y2) in pixels, or fractions of the screen if all values are <= 1.

    e.g. (0, 0.8, 1, 1) = bottom 20% of the screen. Returns pixel ints clipped to the screen.
    """
    h, w = shape[:2]
    if region is None:
        return 0, 0, w, h
    x1, y1, x2, y2 = region
    if all(isinstance(v, float) or v in (0, 1) for v in region) and max(region) <= 1:
        x1, x2 = x1 * w, x2 * w
        y1, y2 = y1 * h, y2 * h
    x1, x2 = sorted((max(0, int(x1)), min(w, int(x2))))
    y1, y2 = sorted((max(0, int(y1)), min(h, int(y2))))
    if x2 - x1 < 2 or y2 - y1 < 2:
        raise ValueError(f"Region {region} is empty on a {w}x{h} screen")
    return x1, y1, x2, y2


def crop(img, region):
    x1, y1, x2, y2 = resolve_region(region, img.shape)
    return img[y1:y2, x1:x2], (x1, y1)


def red_dots(img=None, region=None):
    """Centres (x, y) of the small bright-red notification dots in an area, top to bottom, left to right.
    Round blobs of ~20 px only, so red icons, ribbons and "!" badges don't count."""
    img = cv2.imread("logs/failures/kingshot.dailies_20261007-065615.jpg")
    p = Phone(config.DEVICE_SERIAL, config.UNLOCK_PIN, config.LAUNCH_TIMEOUT)
    part, (ox, oy) = crop(p.screen(), (0, 0.1, 1, 0.17))
    success = cv2.imwrite("./cropped.png", part)
    print(f"Saved: {success}")


red_dots()
