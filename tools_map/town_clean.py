"""Step 2: clean the raw name readings from town_video.py: snap to known names, merge repeats, flag unsure ones.

    .venv/bin/python tools_map/town_clean.py OUT_DIR
Writes OUT_DIR/town_clean.json and town_clean.jpg (labelled panorama to check by eye).
"""
import difflib
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np

OUT = sys.argv[1]
NAMES = ["San Oceana", "Sawmill", "Mill", "Quarry", "Iron Mine", "Kitchen", "Clinic", "Town Center", "Alarm Bell",
         "Suggestion Box", "Conquerors Camp", "Court of Justice", "Infirmary", "Enlistment Office", "Storehouse",
         "Beast Cage", "Academy", "Command Center", "Watchtower", "Hero Hall", "Barracks", "Stable", "Range",
         "Monument", "Embassy", "Truegold Crucible", "Arena", "Guard Station", "War Academy", "Master Academy",
         "Dock", "House", "Defense Tower", "Barricade"]
NUMBERED = {"House", "Defense Tower", "Barricade"}
# fragments OCR produces when a two-word label is split or cut off
PARTS = {"Oceana": "San Oceana", "Conq": "Conquerors Camp", "Conquerors": "Conquerors Camp",
         "Camp": "Conquerors Camp", "Court": "Court of Justice", "Court of": "Court of Justice",
         "Justice": "Court of Justice", "Command": "Command Center", "Truegold": "Truegold Crucible",
         "Crucible": "Truegold Crucible", "Guard": "Guard Station", "Station": "Guard Station",
         "Watcht": "Watchtower", "Hero": "Hero Hall", "Hall": "Hero Hall", "Suggestion": "Suggestion Box",
         "Box": "Suggestion Box", "Alarm": "Alarm Bell", "Bell": "Alarm Bell", "Iron": "Iron Mine",
         "War": "War Academy", "Enlistment": "Enlistment Office", "Office": "Enlistment Office",
         "Master": "Master Academy", "Rang": "Range", "Beast": "Beast Cage", "Tower": "Defense Tower",
         "Defense": "Defense Tower", "Glinic": "Clinic"}


def snap(text):
    """Reading -> (canonical name, number or None), or None if it isn't a building name."""
    t = re.sub(r"[^A-Za-z0-9 ]", "", text.replace("'", "")).strip()
    t = re.sub(r"\s+", " ", t)
    num = re.search(r"\b([1-8])\b", t)
    words = re.sub(r"\b\d+\b", "", t).strip()
    words_ns = words.replace(" ", "").lower()
    best, score = None, 0.0
    for name in NAMES:
        r = difflib.SequenceMatcher(None, words_ns, name.replace(" ", "").lower()).ratio()
        if r > score:
            best, score = name, r
    if score < 0.8:
        frag = next((full for part, full in PARTS.items() if part.lower() == words.lower()), None)
        if not frag:
            return None
        best = frag
    n = int(num.group(1)) if num and best in NUMBERED else None
    return best, n


dets = json.loads(Path(f"{OUT}/detections.json").read_text())
groups = []
for d in dets:
    s = snap(d["text"])
    if not s:
        continue
    name, num = s
    for g in groups:
        if g["name"] == name and abs(g["x"] - d["x"]) < 300 and abs(g["y"] - d["y"]) < 300 and (
                num is None or g["nums"].get(num, 0) > 0 or not g["nums"] or name not in NUMBERED):
            g["pts"].append((d["x"], d["y"]))
            if num:
                g["nums"][num] = g["nums"].get(num, 0) + 1
            g["x"], g["y"] = np.median([p[0] for p in g["pts"]]), np.median([p[1] for p in g["pts"]])
            break
    else:
        groups.append({"name": name, "x": d["x"], "y": d["y"], "pts": [(d["x"], d["y"])],
                       "nums": {num: 1} if num else {}})

buildings = []
for g in groups:
    if len(g["pts"]) < 3:                     # seen too rarely: likely noise
        continue
    label = g["name"]
    unsure = False
    if g["name"] == "Defense Tower" and not g["nums"]:
        label = "Defense Tower 1"                 # the game shows no number on Defense Tower 1
    elif g["name"] in NUMBERED:
        if g["nums"]:
            label += f" {max(g['nums'], key=g['nums'].get)}"
        else:
            label += " ?"
            unsure = True
    buildings.append({"name": label, "x": int(g["x"]), "y": int(g["y"]), "seen": len(g["pts"]), "unsure": unsure})
# fixes checked by eye on the video frames
for b in buildings:
    if b["name"] == "Defense Tower ?" and abs(b["x"] - 2951) < 100 and abs(b["y"] - 4732) < 100:
        b["name"], b["unsure"] = "Defense Tower 5", False
    if b["name"] == "Defense Tower ?" and abs(b["x"] - 2336) < 100 and abs(b["y"] - 2997) < 100:
        b["name"], b["unsure"] = "Defense Tower 1", False   # the game shows no number; it is Defense Tower 1


def near(b, name, dist):
    return any(o["name"] == name and abs(o["x"] - b["x"]) < dist and abs(o["y"] - b["y"]) < dist for o in buildings)


# fragments of longer labels: "...rehouse" -> House, "War/Master Academy" -> Academy
buildings = [b for b in buildings if not (b["name"] == "House ?" and near(b, "Storehouse", 150))
             and not (b["name"] == "Academy" and (near(b, "War Academy", 200) or near(b, "Master Academy", 200)))]
buildings.sort(key=lambda b: (b["y"], b["x"]))

pan = json.loads(Path(f"{OUT}/town.json").read_text())["panorama"]
Path(f"{OUT}/town_clean.json").write_text(json.dumps({"panorama": pan, "note": "x, y = name label position in panorama.png pixels; the building is just below it",
           "buildings": buildings}, indent=1))

canvas = cv2.imread(f"{OUT}/panorama.png")
for b in buildings:
    colour = (0, 165, 255) if b["unsure"] else (0, 0, 255)
    cv2.circle(canvas, (b["x"], b["y"]), 16, colour, -1)
    for th, c in ((10, (0, 0, 0)), (4, (255, 255, 255))):
        cv2.putText(canvas, b["name"], (b["x"] + 22, b["y"] + 14), cv2.FONT_HERSHEY_SIMPLEX, 1.6, c, th)
s = 1800 / max(canvas.shape[:2])
cv2.imwrite(f"{OUT}/town_clean.jpg", cv2.resize(canvas, None, fx=s, fy=s, interpolation=cv2.INTER_AREA),
            [cv2.IMWRITE_JPEG_QUALITY, 85])
for b in buildings:
    print(f"{b['name']:20} ({b['x']:5},{b['y']:5})  seen {b['seen']:3}{'   <- number not read' if b['unsure'] else ''}")
print(len(buildings), "buildings")
