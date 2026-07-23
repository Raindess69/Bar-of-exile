#!/usr/bin/env python
"""Cut assets/talents/*.jpeg talent-icon sheets into assets/icons/talents/<sheet>_<i>.png.

All sheets are 5x5 grids on white background, so each cell is cut independently
(no cross-cell merging possible). Text labels under icons (one sheet has them)
are dropped: short components sitting in the bottom band of a cell.

Usage: python tools/cut_talents.py
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.cut_sprites import background_mask, find_frames

SRC = ROOT / "assets" / "talents"
DST = ROOT / "assets" / "icons" / "talents"
GRID = 5
TARGET_H = 32
MERGE_PX = 12          # joins gaps <= 24px inside a cell (letters, sparks)
TOL = 22

# sheet stem -> short prefix (by content: int=mage blue, void=chaos, holy=cleric,
# rng=archer labeled, str=strength red, arm=warrior grey, hunt=archery brown,
# mag=magic purple, brb=barbarian blood)
def sheet_prefix(stem: str) -> str:
    if stem.startswith("Passive_talent_icons"):
        return "int"
    if stem.startswith("Pixel_art"):
        return "void"
    if stem.startswith("Sprite_sheet_of"):
        return "holy"
    tail = stem.rsplit("_", 1)[-1]           # e.g. "202607150113(1)"
    return {
        "202607150113(1)": "rng",
        "202607150113": "str",
        "202607150114(1)": "arm",
        "202607150114(2)": "hunt",
        "202607150114": "mag",
        "202607150115": "brb",
    }[tail]


def cut_sheet(jpeg: Path) -> int:
    prefix = sheet_prefix(jpeg.stem)
    img = Image.open(jpeg).convert("RGB")
    rgb = np.asarray(img)
    h, w = rgb.shape[:2]
    fg = ~background_mask(rgb, TOL)
    alpha_full = ndimage.binary_erosion(fg, iterations=1, border_value=1) & fg

    saved = 0
    for r in range(GRID):
        for c in range(GRID):
            y0, y1 = round(r * h / GRID), round((r + 1) * h / GRID)
            x0, x1 = round(c * w / GRID), round((c + 1) * w / GRID)
            cell = fg[y0:y1, x0:x1]
            cell_h = y1 - y0
            boxes = find_frames(cell, MERGE_PX)
            if not boxes:
                print(f"WARN: empty cell {prefix} r{r} c{c}", file=sys.stderr)
                continue
            max_pix = max(b[4] for b in boxes)
            keep = []
            for b in boxes:
                bh = b[3] - b[1]
                cy = (b[1] + b[3]) / 2
                if b[4] < 0.01 * max_pix:                    # jpeg speckle
                    continue
                if bh < 0.2 * cell_h and cy > 0.68 * cell_h:  # label text band
                    continue
                keep.append(b)
            if not keep:
                keep = [max(boxes, key=lambda b: b[4])]
            bx0 = min(b[0] for b in keep)
            by0 = min(b[1] for b in keep)
            bx1 = max(b[2] for b in keep)
            by1 = max(b[3] for b in keep)
            a = alpha_full[y0 + by0:y0 + by1, x0 + bx0:x0 + bx1]
            ys, xs = np.nonzero(a)
            if ys.size == 0:
                continue
            ty0, ty1 = ys.min(), ys.max() + 1
            tx0, tx1 = xs.min(), xs.max() + 1
            rgba = np.dstack([
                rgb[y0 + by0 + ty0:y0 + by0 + ty1, x0 + bx0 + tx0:x0 + bx0 + tx1],
                (a[ty0:ty1, tx0:tx1] * 255).astype(np.uint8),
            ])
            frame = Image.fromarray(rgba, "RGBA")
            scale = TARGET_H / frame.height
            frame = frame.resize(
                (max(1, round(frame.width * scale)), TARGET_H), Image.NEAREST)
            idx = r * GRID + c
            frame.save(DST / f"{prefix}_{idx}.png")
            saved += 1
    print(f"[{prefix}] {saved} icons <- {jpeg.name}")
    return saved


def main() -> None:
    DST.mkdir(parents=True, exist_ok=True)
    for old in DST.glob("*.png"):
        old.unlink()
    total = 0
    for jpeg in sorted(SRC.glob("*.jpeg")):
        total += cut_sheet(jpeg)
    print(f"{total} talent icons -> {DST}")


if __name__ == "__main__":
    main()
