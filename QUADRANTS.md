# Screen quadrants

Standard maths numbering, as defined in `regions.py`. Screen is 1080 x 2340 px.

```
            x 0 ........ 540 ........ 1080
  y    0  +---------------+---------------+
          |               |               |
          |      Q2       |      Q1       |
          |   top-left    |   top-right   |
          |               |               |
  y 1170  +---------------+---------------+
          |               |               |
          |      Q3       |      Q4       |
          |  bottom-left  | bottom-right  |
          |               |               |
  y 2340  +---------------+---------------+
```

| Quadrant | Fractions (x1, y1, x2, y2) | Pixels x | Pixels y |
|---|---|---|---|
| Q1 top-right | (0.5, 0, 1, 0.5) | 540–1080 | 0–1170 |
| Q2 top-left | (0, 0, 0.5, 0.5) | 0–540 | 0–1170 |
| Q3 bottom-left | (0, 0.5, 0.5, 1) | 0–540 | 1170–2340 |
| Q4 bottom-right | (0.5, 0.5, 1, 1) | 540–1080 | 1170–2340 |

Use in a job: `from regions import Q4` then `phone.tap(image="world_icon", region=Q4)`.
