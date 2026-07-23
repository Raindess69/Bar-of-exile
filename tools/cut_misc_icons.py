#!/usr/bin/env python
"""Cut misc RPG icon sheets from assets/ into assets/icons/<dir>/N.png
at native resolution (downscale only if taller than 128px).

Usage: python tools/cut_misc_icons.py [dir ...]
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.cut_sprites import (background_mask, filter_boxes, find_frames,
                               refine_split, sort_boxes)

SRC = ROOT / "assets"
DST = ROOT / "assets" / "icons"
MAX_H = 128

# dir -> (source glob, merge_px)  merge small for dense sheets so neighbouring
# icons don't fuse; economy has big well-separated icons -> default-ish merge
SHEETS = {
    "artifacts": ("Pixel_art_RPG_artifacts_grid_202607150156.jpeg", 6),
    "consumables": ("Pixel_art_RPG_consumable_icons_202607150154.jpeg", 6),
    "materials": ("Pixel_art_RPG_crafting_materials*_202607150156.jpeg", 6),
    "keys": ("Pixel_art_RPG_items_keys_202607150156.jpeg", 6),
    "economy": ("Pixel_art_loot_economy_icons_202607150203.jpeg", 16),
}


def cut_native(in_path: Path, out_dir: Path, merge_px: int) -> int:
    img = Image.open(in_path).convert("RGB")
    rgb = np.asarray(img)
    h = rgb.shape[0]

    fg = ~background_mask(rgb, 22)
    boxes = filter_boxes(find_frames(fg, merge_px), h)
    boxes = filter_boxes(refine_split(boxes, fg), h)
    boxes = sort_boxes(boxes)

    alpha_full = ndimage.binary_erosion(fg, iterations=1, border_value=1)

    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.png"):
        old.unlink()
    n = 0
    for x0, y0, x1, y1, _ in boxes:
        a = alpha_full[y0:y1, x0:x1] & fg[y0:y1, x0:x1]
        ys, xs = np.nonzero(a)
        if ys.size < 40:
            continue
        ty0, ty1, tx0, tx1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        rgba = np.dstack([
            rgb[y0 + ty0:y0 + ty1, x0 + tx0:x0 + tx1],
            (a[ty0:ty1, tx0:tx1] * 255).astype(np.uint8),
        ])
        frame = Image.fromarray(rgba, "RGBA")
        if frame.height > MAX_H:
            s = MAX_H / frame.height
            frame = frame.resize(
                (max(1, round(frame.width * s)), MAX_H), Image.NEAREST)
        frame.save(out_dir / f"{n}.png")
        n += 1
    return n


def main() -> None:
    only = {s.lower() for s in sys.argv[1:]}
    for name, (pattern, merge_px) in SHEETS.items():
        if only and name not in only:
            continue
        matches = sorted(SRC.glob(pattern))
        if not matches:
            print(f"WARN: no source for {name} ({pattern})", file=sys.stderr)
            continue
        n = cut_native(matches[0], DST / name, merge_px)
        print(f"[{name}] {n} icons <- {matches[0].name}")


if __name__ == "__main__":
    main()
