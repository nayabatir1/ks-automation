"""Step 1 of a town map from a screen recording: track the view, stitch a panorama, read building names.

    .venv/bin/python tools_map/town_video.py VIDEO.mp4 [MORE.mp4 ...] OUT_DIR   (segments = one recording)
Video: the phone's own resolution (1080x2340), normal zoom, slow panning over the whole town.
Writes OUT_DIR/panorama.png, detections.json (raw name readings), town.json, panorama_labelled.jpg.
Then run tools_map/town_clean.py OUT_DIR.
"""
import difflib
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from core import vision

VIDEOS, OUT = sys.argv[1:-1], sys.argv[-1]
TRACK_EVERY = 4            # frames between tracking steps
OCR_EVERY = 28             # frames between name reads (~0.5 s)
X1, Y1, X2, Y2 = int(0.10 * 1080), int(0.105 * 2340), int(0.86 * 1080), int(0.83 * 2340)   # map area
W, H = X2 - X1, Y2 - Y1

orb = cv2.ORB_create(2500)
bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)


def features(frame):
    g = cv2.cvtColor(frame[Y1:Y2, X1:X2], cv2.COLOR_BGR2GRAY)
    return orb.detectAndCompute(g, None)


def shift(a, b):
    (ka, da), (kb, db) = a, b
    if da is None or db is None:
        return None
    m = bf.match(da, db)
    if len(m) < 15:
        return None
    pa = np.float32([ka[x.queryIdx].pt for x in m])
    pb = np.float32([kb[x.trainIdx].pt for x in m])
    M, inl = cv2.estimateAffinePartial2D(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=3)
    if M is None or inl.sum() < 15:
        return None
    return float(M[0, 2]), float(M[1, 2])


pos = [0.0, 0.0]
prev = None
frames = []          # (x, y, image) of views kept for the panorama
dets = []            # name readings in view coordinates -> map coordinates
lost = 0
t0 = time.monotonic()
done = 0
for video in VIDEOS:
    v = cv2.VideoCapture(video)
    n = int(v.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = v.get(cv2.CAP_PROP_FPS) or 30
    for i in range(0, n, TRACK_EVERY):
        ok, f = v.read()
        for _ in range(TRACK_EVERY - 1):           # skip frames cheaply
            v.grab()
        if not ok:
            break
        feat = features(f)
        if prev is not None:
            s = shift(prev, feat)
            if s is None:
                lost += 1
            else:
                pos[0] -= s[0]
                pos[1] -= s[1]
        prev = feat
        if i % (TRACK_EVERY * 6) == 0:
            frames.append((pos[0], pos[1], f[Y1:Y2, X1:X2].copy()))
        if i % OCR_EVERY == 0:
            for m in vision.ocr_lines(f, (X1, Y1, X2, Y2)):
                letters = sum(c.isalpha() for c in m.text)
                if m.score < 55 or letters < 3:
                    continue
                x1, y1, x2, y2 = m.box
                inside = x1 > X1 + 12 and x2 < X2 - 12 and y1 > Y1 + 12 and y2 < Y2 - 12   # not cut off
                cx, cy = m.center
                dets.append({"text": m.text, "x": pos[0] + cx - X1, "y": pos[1] + cy - Y1,
                             "score": m.score, "whole": inside, "t": round(done + i / fps, 1)})
        if i % 1000 == 0:
            print(f"{Path(video).name} frame {i}/{n}  view ({pos[0]:.0f},{pos[1]:.0f})  readings {len(dets)}  "
                  f"lost {lost}  {time.monotonic() - t0:.0f}s", flush=True)
    done += n / fps

# ---- panorama
xs = [fx for fx, _, _ in frames]
ys = [fy for _, fy, _ in frames]
minx, miny = int(min(xs)), int(min(ys))
cw, ch = int(max(xs) - minx) + W, int(max(ys) - miny) + H
canvas = np.zeros((ch, cw, 3), np.uint8)
for fx, fy, img in frames:
    x, y = int(fx - minx), int(fy - miny)
    canvas[y:y + H, x:x + W] = img
cv2.imwrite(f"{OUT}/panorama.png", canvas)
for d in dets:
    d["x"] -= minx
    d["y"] -= miny
Path(f"{OUT}/detections.json").write_text(json.dumps(dets, indent=1))


# ---- group readings by place, vote on the name
def clean(s):
    s = re.sub(r"[^A-Za-z0-9' -]", "", s).strip()
    return re.sub(r"\s+", " ", s)


clusters = []
for d in sorted(dets, key=lambda d: -d["score"]):
    for c in clusters:
        if abs(c["x"] - d["x"]) < 140 and abs(c["y"] - d["y"]) < 70:
            c["reads"].append(d)
            break
    else:
        clusters.append({"x": d["x"], "y": d["y"], "reads": [d]})

buildings = []
for c in clusters:
    reads = c["reads"]
    whole = [clean(r["text"]) for r in reads if r["whole"]] or [clean(r["text"]) for r in reads]
    votes = Counter(whole)
    best = max(votes, key=lambda s: (votes[s] + sum(difflib.SequenceMatcher(None, s, o).ratio() > 0.8
                                                     for o in whole) * 0.5, len(s)))
    x = float(np.median([r["x"] for r in reads]))
    y = float(np.median([r["y"] for r in reads]))
    buildings.append({"name": best, "x": round(x), "y": round(y), "seen": len(reads),
                      "readings": dict(votes.most_common(4))})
buildings.sort(key=lambda b: (b["y"], b["x"]))
Path(f"{OUT}/town.json").write_text(json.dumps({"panorama": [cw, ch], "first_view_at": [-minx, -miny],
                                                "buildings": buildings}, indent=1))

# ---- labelled preview
lab = canvas.copy()
for b in buildings:
    if b["seen"] < 2:
        continue
    cv2.circle(lab, (b["x"], b["y"]), 14, (0, 0, 255), -1)
    cv2.putText(lab, b["name"], (b["x"] + 18, b["y"] + 12), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 8)
    cv2.putText(lab, b["name"], (b["x"] + 18, b["y"] + 12), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3)
s = 1800 / max(lab.shape[:2])
cv2.imwrite(f"{OUT}/panorama_labelled.jpg", cv2.resize(lab, None, fx=s, fy=s, interpolation=cv2.INTER_AREA),
            [cv2.IMWRITE_JPEG_QUALITY, 85])
print(f"done in {time.monotonic() - t0:.0f}s: panorama {cw}x{ch} from {len(frames)} views, "
      f"{len(dets)} readings -> {len(buildings)} places ({sum(b['seen'] >= 2 for b in buildings)} seen 2+ times), "
      f"tracking lost {lost}x")
