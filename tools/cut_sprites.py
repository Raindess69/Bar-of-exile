#!/usr/bin/env python
"""Cut AI-generated sprite sheets (JPEG, near-white background) into transparent PNG frames.

Pipeline:
  1. Threshold near-white pixels (tolerant of JPEG artifacts), then keep only the
     components of that mask that touch the image border (flood-fill from borders).
     This protects white highlights *inside* sprites from being punched out.
  2. Connected components on the foreground (with a dilation pass so loose bits
     like sparks/drips merge into their parent sprite) -> bounding boxes.
     Tiny noise boxes and text-label boxes (short relative to the main sprites,
     or wide+short) are dropped.
  3. Boxes are sorted row-by-row, left-to-right; each frame is cropped, given an
     alpha channel, downscaled with NEAREST to the target height and saved as
     <out_dir>/<prefix>_<i>.png.

Usage:
  python tools/cut_sprites.py <input.jpeg> <out_dir> <prefix> <target_h>
                              [--max-frames N] [--tol T] [--merge PX] [--erode PX]
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


def background_mask(rgb: np.ndarray, tol: int) -> np.ndarray:
    """True where pixel is near-white AND connected to the image border,
    plus large enclosed near-white pockets (e.g. inside a drawn bow).
    Small white highlights inside sprites are preserved."""
    near_white = np.all(rgb >= 255 - tol, axis=2)
    labels, n = ndimage.label(near_white)
    border_ids = np.unique(np.concatenate([
        labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]
    ]))
    border_ids = border_ids[border_ids != 0]
    bg = np.isin(labels, border_ids)

    # enclosed pockets: large + very close to pure white -> background too
    enclosed = np.setdiff1d(np.arange(1, n + 1), border_ids)
    if enclosed.size:
        areas = ndimage.sum_labels(near_white, labels, enclosed)
        very_white = np.all(rgb >= 244, axis=2)
        whiteness = ndimage.mean(very_white, labels, enclosed)
        pockets = enclosed[(areas >= 250) & (whiteness > 0.85)]
        if pockets.size:
            bg |= np.isin(labels, pockets)
    return bg


def find_frames(fg: np.ndarray, merge_px: int):
    """Group foreground pixels into frames; return list of (x0, y0, x1, y1, npix)."""
    if merge_px > 0:
        size = 2 * merge_px + 1
        merged = ndimage.grey_dilation(fg.astype(np.uint8), size=(size, size)) > 0
    else:
        merged = fg
    labels, n = ndimage.label(merged)
    boxes = []
    for i, slc in enumerate(ndimage.find_objects(labels), start=1):
        if slc is None:
            continue
        comp = (labels[slc] == i) & fg[slc]
        ys, xs = np.nonzero(comp)
        if ys.size == 0:
            continue
        y_off, x_off = slc[0].start, slc[1].start
        boxes.append((
            x_off + xs.min(), y_off + ys.min(),
            x_off + xs.max() + 1, y_off + ys.max() + 1,
            int(ys.size),
        ))
    return boxes


def filter_boxes(boxes, img_h):
    """Drop tiny noise and text-label boxes."""
    if not boxes:
        return []
    max_pix = max(b[4] for b in boxes)
    # noise: tiny pixel count or tiny height
    boxes = [b for b in boxes
             if b[4] >= 0.004 * max_pix and (b[3] - b[1]) >= 0.03 * img_h]
    if not boxes:
        return []
    max_h = max(b[3] - b[1] for b in boxes)
    kept = []
    for b in boxes:
        w, h = b[2] - b[0], b[3] - b[1]
        if h < 0.32 * max_h:            # short relative to main sprites -> label
            continue
        if w > 2.8 * h and h < 0.5 * max_h:  # wide+short strip -> label
            continue
        kept.append(b)
    return kept


def refine_split(boxes, fg):
    """Split boxes that contain several sprites bridged by thin projectiles.

    Re-label each box's foreground with a small merge radius; if 2+ "major"
    components remain (big and tall), split the box, assigning minor bits
    (arrows, bolts, debris) to the horizontally nearest major.
    """
    small = max(3, fg.shape[1] // 600)
    out = []
    for b in boxes:
        x0, y0, x1, y1, _ = b
        sub = fg[y0:y1, x0:x1]
        subs = find_frames(sub, small)
        if len(subs) < 2:
            out.append(b)
            continue
        box_h = y1 - y0
        max_pix = max(s[4] for s in subs)
        majors = [s for s in subs
                  if s[4] >= 0.22 * max_pix and (s[3] - s[1]) >= 0.55 * box_h]
        if len(majors) < 2:
            out.append(b)
            continue
        groups = {id(m): [m] for m in majors}
        for s in subs:
            if s in majors:
                continue
            cx = (s[0] + s[2]) / 2
            nearest = min(majors, key=lambda m: abs((m[0] + m[2]) / 2 - cx))
            groups[id(nearest)].append(s)
        for grp in groups.values():
            out.append((
                x0 + min(g[0] for g in grp), y0 + min(g[1] for g in grp),
                x0 + max(g[2] for g in grp), y0 + max(g[3] for g in grp),
                sum(g[4] for g in grp),
            ))
    return out


def sort_boxes(boxes):
    """Row-major order: group by vertical overlap of centers, then left-to-right."""
    if not boxes:
        return []
    med_h = float(np.median([b[3] - b[1] for b in boxes]))
    rows = []  # list of [row_cy, [boxes]]
    for b in sorted(boxes, key=lambda b: (b[1] + b[3]) / 2):
        cy = (b[1] + b[3]) / 2
        for row in rows:
            if abs(cy - row[0]) < 0.5 * med_h:
                row[1].append(b)
                row[0] = float(np.mean([(x[1] + x[3]) / 2 for x in row[1]]))
                break
        else:
            rows.append([cy, [b]])
    out = []
    for _, row_boxes in sorted(rows, key=lambda r: r[0]):
        out.extend(sorted(row_boxes, key=lambda b: b[0]))
    return out


def cut(in_path, out_dir, prefix, target_h, max_frames=None,
        tol=22, merge_px=None, erode=1, split=True):
    img = Image.open(in_path).convert("RGB")
    rgb = np.asarray(img)
    h, w = rgb.shape[:2]
    if merge_px is None:
        merge_px = max(8, w // 120)

    bg = background_mask(rgb, tol)
    fg = ~bg

    boxes = filter_boxes(find_frames(fg, merge_px), h)
    if split:
        boxes = filter_boxes(refine_split(boxes, fg), h)
    if max_frames is not None and len(boxes) > max_frames:
        boxes = sorted(boxes, key=lambda b: -b[4])[:max_frames]
    boxes = sort_boxes(boxes)
    if not boxes:
        print(f"WARN: no frames found in {in_path}", file=sys.stderr)
        return []

    alpha_full = fg
    if erode > 0:  # shave the white JPEG halo off sprite edges
        alpha_full = ndimage.binary_erosion(fg, iterations=erode, border_value=1)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, (x0, y0, x1, y1, _) in enumerate(boxes):
        a = (alpha_full[y0:y1, x0:x1] & fg[y0:y1, x0:x1])
        ys, xs = np.nonzero(a)
        if ys.size == 0:
            continue
        ty0, ty1 = ys.min(), ys.max() + 1
        tx0, tx1 = xs.min(), xs.max() + 1
        rgba = np.dstack([
            rgb[y0 + ty0:y0 + ty1, x0 + tx0:x0 + tx1],
            (a[ty0:ty1, tx0:tx1] * 255).astype(np.uint8),
        ])
        frame = Image.fromarray(rgba, "RGBA")
        scale = target_h / frame.height
        frame = frame.resize(
            (max(1, round(frame.width * scale)), target_h), Image.NEAREST)
        path = out_dir / f"{prefix}_{len(saved)}.png"
        frame.save(path)
        saved.append(path)
        print(f"  {path}  {frame.width}x{frame.height}")
    return saved


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("input")
    p.add_argument("out_dir")
    p.add_argument("prefix")
    p.add_argument("target_h", type=int)
    p.add_argument("--max-frames", type=int, default=None)
    p.add_argument("--tol", type=int, default=22,
                   help="near-white tolerance (default 22)")
    p.add_argument("--merge", type=int, default=None,
                   help="dilation px to merge loose sprite bits (default w//120)")
    p.add_argument("--erode", type=int, default=1,
                   help="alpha erosion px to cut white halo (default 1)")
    p.add_argument("--no-split", action="store_true",
                   help="disable splitting of frames bridged by projectiles")
    a = p.parse_args()
    saved = cut(a.input, a.out_dir, a.prefix, a.target_h,
                max_frames=a.max_frames, tol=a.tol,
                merge_px=a.merge, erode=a.erode, split=not a.no_split)
    print(f"{len(saved)} frame(s) from {a.input}")


if __name__ == "__main__":
    main()
