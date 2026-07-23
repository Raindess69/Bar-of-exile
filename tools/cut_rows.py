#!/usr/bin/env python
"""Cut a label-free sheet row by row: find row gutters, then column gutters
inside each row strip (columns don't align across rows on these sheets).

Usage:
  python tools/cut_rows.py <input> <out_dir> <target_h> [--row-thr 0.98] [--col-thr 0.97]
Saves <out_dir>/r<R>_<i>.png per row in reading order.
"""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image

from cut_grid import _bands, _cells_from_gutters, _sprite_alpha


def cut_rows(in_path, out_dir, target_h, row_thr=0.98, col_thr=0.97,
             erode=0, label_frac=0.03):
    img = Image.open(in_path).convert("RGB")
    rgb8 = np.asarray(img)
    rgb = rgb8.astype(np.int16)
    H, W = rgb.shape[:2]
    blankish = rgb.min(axis=2) >= 196
    row_gut = _bands(blankish.mean(axis=1), row_thr, max(6, H // 300))
    row_spans = _cells_from_gutters(H, row_gut)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result = {}
    for r, (y0, y1) in enumerate(row_spans):
        strip_blank = blankish[y0:y1]
        col_gut = _bands(strip_blank.mean(axis=0), col_thr, 4)
        col_spans = _cells_from_gutters(W, col_gut)
        frames = []
        for (x0, x1) in col_spans:
            fg = _sprite_alpha(rgb[y0:y1, x0:x1], erode=erode,
                               label_frac=label_frac)
            if fg is None:
                continue
            ys, xs = np.nonzero(fg)
            if ys.size < 200:
                continue
            ty0, ty1, tx0, tx1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
            cell = rgb8[y0:y1, x0:x1]
            rgba = np.dstack([
                cell[ty0:ty1, tx0:tx1],
                (fg[ty0:ty1, tx0:tx1] * 255).astype(np.uint8),
            ])
            frame = Image.fromarray(rgba, "RGBA")
            scale = target_h / frame.height
            frame = frame.resize(
                (max(1, round(frame.width * scale)), target_h), Image.NEAREST)
            p = out / f"r{r}_{len(frames)}.png"
            frame.save(p)
            frames.append(p)
        result[r] = frames
        print(f"row {r}: {len(frames)} frames  (y {y0}-{y1})")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("out_dir")
    ap.add_argument("target_h", type=int)
    ap.add_argument("--row-thr", type=float, default=0.98)
    ap.add_argument("--col-thr", type=float, default=0.97)
    a = ap.parse_args()
    cut_rows(a.input, a.out_dir, a.target_h, a.row_thr, a.col_thr)
