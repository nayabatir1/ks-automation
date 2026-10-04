"""Reading the screen: OCR (Tesseract) and template matching (OpenCV).

Everything works on screenshots as OpenCV BGR numpy arrays, and every result is in
full-screen pixel coordinates (also when you pass a region).

OCR runs in two passes:
  normal  - the screenshot in greyscale: dark text on light backgrounds (and most else)
  light   - keeps only white/light low-saturation pixels (white text on coloured buttons),
            drops big blobs and thin frames (button outlines, panels), then OCRs that as
            black-on-white. Words it finds that the normal pass missed are added.
"""
import re
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pytesseract

import config


@dataclass
class Match:
    """Something found on screen. x, y, w, h = bounding box in screen pixels."""
    x: int
    y: int
    w: int
    h: int
    score: float          # OCR confidence 0-100, or template score 0-1
    text: str = ""        # what was read (OCR) or template name (image)
    source: str = ""      # "normal" / "light" (OCR pass) or "image"

    @property
    def center(self):
        return self.x + self.w // 2, self.y + self.h // 2

    @property
    def box(self):
        return self.x, self.y, self.x + self.w, self.y + self.h

    def __str__(self):
        cx, cy = self.center
        x1, y1, x2, y2 = self.box
        sc = f"{self.score:.2f}" if self.source in ("image", "shape") else f"{self.score:.0f}"
        return f"tap ({cx:4d},{cy:4d})  box {x1},{y1}-{x2},{y2}  score {sc:>4}  [{self.source}]  {self.text}"


# ------------------------------------------------------------------ images
def decode_png(data: bytes):
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode screenshot")
    return img


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


# ------------------------------------------------------------------ OCR
def _tesseract_words(gray, offset, source):
    data = pytesseract.image_to_data(gray, lang=config.OCR_LANG, config="--psm 11",
                                     output_type=pytesseract.Output.DICT)
    ox, oy = offset
    words = []
    for i, txt in enumerate(data["text"]):
        txt = txt.strip()
        conf = float(data["conf"][i])
        if not txt or conf < config.OCR_MIN_CONF:
            continue
        if not re.search(r"\w", txt):           # lone punctuation is almost always noise
            continue
        words.append(Match(data["left"][i] + ox, data["top"][i] + oy,
                           data["width"][i], data["height"][i], conf, txt, source))
    return words


def light_text_mask(bgr):
    """Black text on white, made from the light (white-ish) pixels only, outlines removed."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    light = ((hsv[:, :, 2] >= 170) & (hsv[:, :, 1] <= 70)).astype(np.uint8) * 255

    h, w = light.shape
    n, labels, stats, _ = cv2.connectedComponentsWithStats(light, connectivity=8)
    keep = np.zeros(n, bool)
    max_char_h = min(h, 150)                               # letters are < 150 px tall at 1080x2340
    for i in range(1, n):
        _, _, cw, ch, area = stats[i]
        if area < 6:                                       # specks
            continue
        if ch > max_char_h or cw > w * 0.5:                # panels, bars, big shapes
            continue
        if cw > 3 * ch and ch <= 4:                        # thin horizontal line (outline edge)
            continue
        if ch > 3 * cw and cw <= 4 and ch > 40:            # thin vertical line (outline edge)
            continue
        fill = area / float(cw * ch)
        if cw * ch > 2500 and fill < 0.15:                 # hollow frame = button outline
            continue
        keep[i] = True
    mask = keep[labels].astype(np.uint8) * 255
    out = 255 - mask
    return cv2.copyMakeBorder(out, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)


def _overlaps(a: Match, b: Match):
    ix = max(0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
    iy = max(0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
    return ix * iy > 0.3 * min(a.w * a.h, b.w * b.h)


def ocr_words(img, region=None, passes=("normal", "light")):
    """All words on screen (or in region), from the requested OCR passes, de-duplicated."""
    part, (ox, oy) = crop(img, region)
    words = []
    if "normal" in passes:
        gray = cv2.cvtColor(part, cv2.COLOR_BGR2GRAY)
        words += _tesseract_words(gray, (ox, oy), "normal")
    if "light" in passes:
        extra = _tesseract_words(light_text_mask(part), (ox - 10, oy - 10), "light")
        words += [w for w in extra if not any(_overlaps(w, n) for n in words)]
    return words


def group_lines(words):
    """Join words into lines/phrases: same row and close together horizontally."""
    # 1. rows: words whose vertical centres line up
    rows = []
    for w in sorted(words, key=lambda m: m.y + m.h / 2):
        cy = w.y + w.h / 2
        for row in rows:
            r = row[0]
            if abs((r.y + r.h / 2) - cy) < 0.6 * max(r.h, w.h) and r.source == w.source:
                row.append(w)
                break
        else:
            rows.append([w])
    # 2. split each row, left to right, wherever the gap is wider than about a word space
    lines = []
    for row in rows:
        row.sort(key=lambda m: m.x)
        line = [row[0]]
        for w in row[1:]:
            last = line[-1]
            if w.x - (last.x + last.w) < 1.5 * max(last.h, w.h):
                line.append(w)
            else:
                lines.append(line)
                line = [w]
        lines.append(line)
    return lines


def merge(words):
    x1 = min(w.x for w in words)
    y1 = min(w.y for w in words)
    x2 = max(w.x + w.w for w in words)
    y2 = max(w.y + w.h for w in words)
    return Match(x1, y1, x2 - x1, y2 - y1, min(w.score for w in words),
                 " ".join(w.text for w in words), words[0].source)


def ocr_lines(img, region=None, passes=("normal", "light")):
    """OCR result as phrases (one Match per line), sorted top-to-bottom, left-to-right."""
    lines = [merge(l) for l in group_lines(ocr_words(img, region, passes))]
    return sorted(lines, key=lambda m: (m.y, m.x))


def _norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def find_text(img, text, region=None):
    """Find text on screen. Returns the best Match or None.

    text: a string (case-insensitive, matches inside a phrase too: "about" finds "About phone")
          or a compiled regex (re.compile(r"\\d+ coins")).
    Tries the normal OCR pass first and the light-text pass only if that finds nothing.
    """
    for passes in (("normal",), ("light",)):
        best = None
        for line in group_lines(ocr_words(img, region, passes)):
            # shortest run of consecutive words containing the text
            for i in range(len(line)):
                for j in range(i, len(line)):
                    joined = " ".join(w.text for w in line[i:j + 1])
                    hit = (text.search(joined) if isinstance(text, re.Pattern)
                           else _norm(text) in _norm(joined))
                    if hit:
                        m = merge(line[i:j + 1])
                        if best is None or (m.w * m.h < best.w * best.h):
                            best = m
                        break
        if best:
            return best
    return None


# ------------------------------------------------------------------ templates
_template_cache = {}


def load_template(name_or_path):
    p = Path(name_or_path)
    if not p.suffix:
        p = config.TEMPLATE_DIR / f"{name_or_path}.png"
    elif not p.is_absolute() and not p.exists():
        p = config.TEMPLATE_DIR / p
    if p not in _template_cache:
        t = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if t is None:
            raise FileNotFoundError(f"Template image not found: {p}  (make one with: tools.py crop ...)")
        _template_cache[p] = t
    return _template_cache[p], p.stem


def find_image(img, image, region=None, threshold=None, scales=(1.0,)):
    """Find a template image (templates/NAME.png) on screen. Returns Match or None.

    Templates cut from the phone's own screenshots (tools.py crop / tools.py template) match at
    scale 1.0. `scales` lets you search other sizes, e.g. for an image taken from a PC screenshot.
    """
    tmpl, name = load_template(image)
    part, (ox, oy) = crop(img, region)
    gray_part = cv2.cvtColor(part, cv2.COLOR_BGR2GRAY)
    gray_tmpl = cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY)
    best = None
    for s in scales:
        t = gray_tmpl if s == 1.0 else cv2.resize(
            gray_tmpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
        th, tw = t.shape[:2]
        if th < 8 or tw < 8 or gray_part.shape[0] < th or gray_part.shape[1] < tw:
            continue
        _, score, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(gray_part, t, cv2.TM_CCOEFF_NORMED))
        if best is None or score > best.score:
            best = Match(x + ox, y + oy, tw, th, float(score), name, "image")
    if best is None or best.score < (threshold or config.MATCH_THRESHOLD):
        return None
    return best


_CLAHE = cv2.createCLAHE(2.0, (8, 8))


def _outline(img):
    g = _CLAHE.apply(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    return cv2.GaussianBlur(cv2.Canny(g, 40, 120), (7, 7), 0)


def find_shape(img, image, region=None, threshold=0.5):
    """Like find_image, but compares outlines (edges) instead of colours/brightness, so a template cut in daylight
    still matches at night. Scores run lower than find_image (~0.95 same lighting, ~0.75 day vs night, < 0.25 for
    other things), hence the lower threshold."""
    tmpl, name = load_template(image)
    part, (ox, oy) = crop(img, region)
    th, tw = tmpl.shape[:2]
    if part.shape[0] < th or part.shape[1] < tw:
        return None
    _, score, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(_outline(part), _outline(tmpl), cv2.TM_CCOEFF_NORMED))
    if score < threshold:
        return None
    return Match(x + ox, y + oy, tw, th, float(score), name, "shape")


def median_hue(img, region):
    """Typical colour of an area as an OpenCV hue (0-180: red ~0, orange ~15, green ~60, teal ~90, blue ~110).
    Only coloured pixels count (white/grey text is skipped)."""
    part, _ = crop(img, region)
    hsv = cv2.cvtColor(part, cv2.COLOR_BGR2HSV)
    coloured = hsv[:, :, 1] > 80
    return float(np.median(hsv[:, :, 0][coloured])) if coloured.any() else -1.0


def coloured_share(img, region):
    """Fraction of an area that is coloured (saturated) rather than white/grey/black, 0-1.
    A greyed-out button is close to 0."""
    part, _ = crop(img, region)
    return float((cv2.cvtColor(part, cv2.COLOR_BGR2HSV)[:, :, 1] > 80).mean())


def red_dots(img, region=None):
    """Centres (x, y) of the small bright-red notification dots in an area, top to bottom, left to right.
    Round blobs of ~20 px only, so red icons, ribbons and "!" badges don't count."""
    part, (ox, oy) = crop(img, region)
    hsv = cv2.cvtColor(part, cv2.COLOR_BGR2HSV)
    red = ((hsv[:, :, 0] < 8) | (hsv[:, :, 0] > 172)) & (hsv[:, :, 1] > 170) & (hsv[:, :, 2] > 200)
    n, _, stats, centres = cv2.connectedComponentsWithStats(red.astype(np.uint8))
    dots = [(ox + int(centres[k][0]), oy + int(centres[k][1])) for k in range(1, n)
            if 250 < stats[k][4] < 1500 and 0.7 < stats[k][2] / stats[k][3] < 1.4
            and stats[k][4] > 0.6 * stats[k][2] * stats[k][3]]
    return sorted(dots, key=lambda d: (d[1] // 30, d[0]))


def screen_diff(a, b, region=None):
    """Mean pixel difference (0-255) between two screenshots, on a small greyscale version."""
    def small(im):
        part, _ = crop(im, region)
        h, w = part.shape[:2]
        return cv2.resize(cv2.cvtColor(part, cv2.COLOR_BGR2GRAY), (max(1, w // 10), max(1, h // 10)),
                          interpolation=cv2.INTER_AREA).astype(np.int16)
    return float(np.abs(small(a) - small(b)).mean())
