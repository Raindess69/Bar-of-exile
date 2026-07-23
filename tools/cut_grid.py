#!/usr/bin/env python
"""Cut a *labelled grid* sprite sheet (gray gridlines + tiny number labels per cell)
into transparent PNG frames, in reading order.

These AI sheets are a clean R x C grid: each cell holds one sprite plus a small
digit label in a corner. The generic blob cutter (cut_sprites.py) fails here
because the faint gray gridlines register as foreground and weld every sprite
into one component. This tool instead:

  1. Finds the grid by locating blank bands (rows/cols that are almost entirely
     near-white OR faint-gray line) and slicing the sheet into cells.
  2. Inside each cell, builds a white/gray background mask, keeps the largest
     foreground component as the sprite, and drops small components (the number
     label, stray noise).
  3. Crops tight, adds alpha, NEAREST-downscales to target_h, saves
     <out>/<prefix>_<i>.png in row-major order.

Usage:
  python tools/cut_grid.py <input> <out_dir> <prefix> <target_h>
        [--rows R] [--cols C] [--erode 1] [--label-frac 0.06] [--max N]
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


def _bands(blank_frac, thr=0.85, min_gap=6):
    """Return (start, end) index ranges where blank_frac >= thr (grid gutters)."""
    idx = np.where(blank_frac >= thr)[0]
    if len(idx) == 0:
        return []
    groups, s, p = [], idx[0], idx[0]
    for x in idx[1:]:
        if x == p + 1:
            p = x
        else:
            groups.append((s, p))
            s = p = x
    groups.append((s, p))
    return [g for g in groups if g[1] - g[0] + 1 >= min_gap]


def _cells_from_gutters(length, gutters):
    """Given gutter bands along an axis, return content spans between them."""
    spans, cur = [], 0
    for a, b in gutters:
        if a - cur > 4:
            spans.append((cur, a))
        cur = b + 1
    if length - cur > 4:
        spans.append((cur, length))
    return spans


def _sprite_alpha(cell_rgb, tol=18, erode=1, label_frac=0.06):
    """Foreground alpha for one cell: background = near-white/gray touching the
    cell border; keep components that aren't tiny labels."""
    g = cell_rgb.min(axis=2)
    bg_like = g >= (255 - tol)
    # also treat faint gray gridline remnants as background
    bg_like |= (g >= 196) & (cell_rgb.max(axis=2) - cell_rgb.min(axis=2) <= 12)
    labels, n = ndimage.label(bg_like)
    border = np.unique(np.concatenate(
        [labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    border = border[border != 0]
    bg = np.isin(labels, border)
    fg = ~bg
    # component filtering: drop small blobs (number labels, noise)
    lab, m = ndimage.label(fg)
    if m == 0:
        return None
    sizes = ndimage.sum_labels(np.ones_like(lab), lab, range(1, m + 1))
    keep = np.zeros(m + 1, bool)
    biggest = sizes.max()
    for i, s in enumerate(sizes, start=1):
        keep[i] = s >= max(label_frac * biggest, 40)
    fg = keep[lab]
    if not fg.any():
        return None
    if erode > 0:
        fg = ndimage.binary_erosion(fg, iterations=erode, border_value=0)
        if not fg.any():
            fg = keep[lab]
    return fg


def cut(in_path, out_dir, prefix, target_h, rows=None, cols=None,
        erode=1, label_frac=0.06, max_frames=None):
    img = Image.open(in_path).convert("RGB")
    rgb = np.asarray(img).astype(np.int16)
    H, W = rgb.shape[:2]
    g = rgb.min(axis=2)
    blankish = g >= 196
    col_gut = _bands(blankish.mean(axis=0), 0.85, max(6, W // 300))
    row_gut = _bands(blankish.mean(axis=1), 0.85, max(6, H // 300))
    col_spans = _cells_from_gutters(W, col_gut)
    row_spans = _cells_from_gutters(H, row_gut)
    if cols:
        col_spans = col_spans[:cols]
    if rows:
        row_spans = row_spans[:rows]
    if not col_spans or not row_spans:
        print(f"WARN: no grid found in {in_path}", file=sys.stderr)
        return []

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rgb8 = np.asarray(img)
    saved = []
    for (y0, y1) in row_spans:
        for (x0, x1) in col_spans:
            if max_frames and len(saved) >= max_frames:
                break
            cell = rgb8[y0:y1, x0:x1]
            fg = _sprite_alpha(rgb[y0:y1, x0:x1], erode=erode,
                               label_frac=label_frac)
            if fg is None:
                continue
            ys, xs = np.nonzero(fg)
            if ys.size < 60:
                continue
            ty0, ty1, tx0, tx1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
            rgba = np.dstack([
                cell[ty0:ty1, tx0:tx1],
                (fg[ty0:ty1, tx0:tx1] * 255).astype(np.uint8),
            ])
            frame = Image.fromarray(rgba, "RGBA")
            scale = target_h / frame.height
            frame = frame.resize(
                (max(1, round(frame.width * scale)), target_h), Image.NEAREST)
            path = out_dir / f"{prefix}_{len(saved)}.png"
            frame.save(path)
            saved.append(path)
            print(f"  {path}  {frame.width}x{frame.height}")
    print(f"{len(saved)} frame(s) from {in_path}")
    return saved


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("input")
    p.add_argument("out_dir")
    p.add_argument("prefix")
    p.add_argument("target_h", type=int)
    p.add_argument("--rows", type=int, default=None)
    p.add_argument("--cols", type=int, default=None)
    p.add_argument("--erode", type=int, default=1)
    p.add_argument("--label-frac", type=float, default=0.06)
    p.add_argument("--max", type=int, default=None)
    a = p.parse_args()
    cut(a.input, a.out_dir, a.prefix, a.target_h, rows=a.rows, cols=a.cols,
        erode=a.erode, label_frac=a.label_frac, max_frames=a.max)


if __name__ == "__main__":
    main()
