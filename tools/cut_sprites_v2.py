#!/usr/bin/env python3
"""
cut_sprites_v2.py - Bar of Exile: sprite sheet cutter without animation jitter.

Why animations look crooked after naive cutting:
  1) tight-crop per frame -> every frame gets its own size/origin -> sprite jitters
  2) gutters/margins between frames not detected -> frames cut shifted
  3) sheets without alpha (white/magenta bg) -> bbox detection grabs the bg

This tool fixes all three:
  - auto-detects the frame grid from transparency projections (or takes an exact
    grid via --cols/--rows/--frame/--margin/--spacing)
  - NEVER tight-crops: every frame is placed on ONE uniform canvas,
    anchored bottom-center (characters) or center (fx/projectiles)
  - no-alpha sheets: background color is taken from the corner and keyed out
  - writes preview.gif + contact_sheet.png so you can SEE the result before the game
  - writes manifest.json (canvas, anchor, per-frame source cells) for the loader

Usage:
  python cut_sprites_v2.py sheet.png --out out_dir
  python cut_sprites_v2.py sheet.png --out out_dir --cols 8 --rows 4
  python cut_sprites_v2.py sheet.png --out out_dir --frame 64x64 --margin 2 --spacing 1
  python cut_sprites_v2.py assets_dir --out cut_dir            # every *.png in dir
Options:
  --anchor bottom|center   (default bottom: feet stay planted)
  --canvas WxH             force output canvas size
  --raw                    cut raw cells without normalization (debug)
  --fps N                  preview gif speed (default 10)
  --alpha-threshold N      alpha > N counts as content (default 8)
  --bg-tol N               color distance from corner bg for no-alpha sheets (default 48)
  --min-gutter N           merge content segments separated by gaps < N px (default 2)
Requires: Pillow, numpy (pip install pillow numpy)
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw


def build_mask(img, alpha_threshold, bg_tol):
    """Returns (bool mask HxW of content, RGBA image with proper transparency)."""
    rgba = img.convert("RGBA")
    arr = np.asarray(rgba)
    alpha = arr[:, :, 3]
    if alpha.min() < 255:
        return alpha > alpha_threshold, rgba
    # No alpha channel in use: key out background = corner pixel color
    rgb = arr[:, :, :3].astype(int)
    corners = [rgb[0, 0], rgb[0, -1], rgb[-1, 0], rgb[-1, -1]]
    bg = np.median(np.stack(corners), axis=0)
    mask = np.abs(rgb - bg).sum(axis=2) > bg_tol
    out = arr.copy()
    out[:, :, 3] = np.where(mask, 255, 0).astype(np.uint8)
    return mask, Image.fromarray(out, "RGBA")


def segments(any_1d, min_gutter):
    """Runs of True in a 1D projection -> [(start, end)), gaps < min_gutter merged."""
    segs, start = [], None
    for i, v in enumerate(any_1d):
        if v and start is None:
            start = i
        elif not v and start is not None:
            segs.append([start, i])
            start = None
    if start is not None:
        segs.append([start, len(any_1d)])
    merged = []
    for s in segs:
        if merged and s[0] - merged[-1][1] < min_gutter:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    return [tuple(s) for s in merged]


def auto_cells(mask, min_gutter):
    xsegs = segments(mask.any(axis=0), min_gutter)
    ysegs = segments(mask.any(axis=1), min_gutter)
    cells = []
    for (y0, y1) in ysegs:
        for (x0, x1) in xsegs:
            if mask[y0:y1, x0:x1].any():
                cells.append((x0, y0, x1, y1))
    return cells, len(xsegs), len(ysegs)


def fixed_cells(w, h, cols, rows, frame, margin, spacing):
    if frame:
        fw, fh = frame
        cols = cols or (w - 2 * margin + spacing) // (fw + spacing)
        rows = rows or (h - 2 * margin + spacing) // (fh + spacing)
    else:
        fw = (w - 2 * margin - (cols - 1) * spacing) // cols
        fh = (h - 2 * margin - (rows - 1) * spacing) // rows
    cells = []
    for r in range(rows):
        for c in range(cols):
            x0 = margin + c * (fw + spacing)
            y0 = margin + r * (fh + spacing)
            cells.append((x0, y0, min(x0 + fw, w), min(y0 + fh, h)))
    return cells, cols, rows


def cut_sheet(path, out_dir, args):
    img = Image.open(path)
    mask, rgba = build_mask(img, args.alpha_threshold, args.bg_tol)
    w, h = rgba.size

    if args.cols or args.rows or args.frame:
        cells, cols, rows = fixed_cells(w, h, args.cols, args.rows, args.frame, args.margin, args.spacing)
        mode = f"fixed grid {cols}x{rows}"
    else:
        cells, cols, rows = auto_cells(mask, args.min_gutter)
        mode = f"auto grid {cols}x{rows}"
    if not cells:
        print(f"[!] {os.path.basename(path)}: no content found, skipped")
        return

    # content bbox per cell (skip empty cells of fixed grids)
    boxes = []
    for (x0, y0, x1, y1) in cells:
        sub = mask[y0:y1, x0:x1]
        if not sub.any():
            continue
        ys, xs = np.where(sub)
        boxes.append({"cell": [x0, y0, x1, y1],
                      "bbox": [int(x0 + xs.min()), int(y0 + ys.min()),
                               int(x0 + xs.max() + 1), int(y0 + ys.max() + 1)]})

    if args.raw:
        W = max(b["cell"][2] - b["cell"][0] for b in boxes)
        H = max(b["cell"][3] - b["cell"][1] for b in boxes)
    else:
        W = max(b["bbox"][2] - b["bbox"][0] for b in boxes)
        H = max(b["bbox"][3] - b["bbox"][1] for b in boxes)
    if args.canvas:
        W, H = max(W, args.canvas[0]), max(H, args.canvas[1])
        W, H = args.canvas

    os.makedirs(out_dir, exist_ok=True)
    frames, manifest_frames = [], []
    for i, b in enumerate(boxes):
        src = b["cell"] if args.raw else b["bbox"]
        crop = rgba.crop(tuple(src))
        fw, fh = crop.size
        px = (W - fw) // 2
        py = (H - fh) if args.anchor == "bottom" else (H - fh) // 2
        frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        frame.paste(crop, (px, py))
        name = f"frame_{i:03d}.png"
        frame.save(os.path.join(out_dir, name))
        frames.append(frame)
        manifest_frames.append({"file": name, "source_cell": b["cell"],
                                "source_bbox": b["bbox"], "paste_offset": [px, py]})

    # ---- QA artifacts ----
    frames[0].save(os.path.join(out_dir, "preview.gif"), save_all=True,
                   append_images=frames[1:], duration=int(1000 / args.fps), loop=0, disposal=2)
    sheet_qa = rgba.copy()
    d = ImageDraw.Draw(sheet_qa)
    for b in boxes:
        d.rectangle(b["cell"], outline=(255, 0, 0, 255))
        d.rectangle(b["bbox"], outline=(0, 255, 0, 255))
    sheet_qa.save(os.path.join(out_dir, "contact_sheet.png"))

    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"source": os.path.basename(path), "mode": mode,
                   "canvas": [W, H], "anchor": args.anchor,
                   "frame_count": len(frames), "fps_preview": args.fps,
                   "frames": manifest_frames}, f, indent=1)

    print(f"[+] {os.path.basename(path)}: {mode}, {len(frames)} frames -> {out_dir} "
          f"(canvas {W}x{H}, anchor {args.anchor}). CHECK preview.gif BEFORE using in game!")


def parse_wh(s):
    a, b = s.lower().split("x")
    return int(a), int(b)


def main():
    p = argparse.ArgumentParser(description="Jitter-free sprite sheet cutter")
    p.add_argument("input", help="sheet.png or a directory of *.png")
    p.add_argument("--out", required=True)
    p.add_argument("--cols", type=int)
    p.add_argument("--rows", type=int)
    p.add_argument("--frame", type=parse_wh, help="WxH exact frame size")
    p.add_argument("--margin", type=int, default=0)
    p.add_argument("--spacing", type=int, default=0)
    p.add_argument("--anchor", choices=["bottom", "center"], default="bottom")
    p.add_argument("--canvas", type=parse_wh)
    p.add_argument("--raw", action="store_true")
    p.add_argument("--fps", type=int, default=10)
    p.add_argument("--alpha-threshold", type=int, default=8)
    p.add_argument("--bg-tol", type=int, default=48)
    p.add_argument("--min-gutter", type=int, default=2)
    args = p.parse_args()

    if os.path.isdir(args.input):
        pngs = sorted(f for f in os.listdir(args.input) if f.lower().endswith(".png"))
        if not pngs:
            sys.exit("no .png files in " + args.input)
        for f in pngs:
            cut_sheet(os.path.join(args.input, f), os.path.join(args.out, os.path.splitext(f)[0]), args)
    else:
        cut_sheet(args.input, args.out, args)


if __name__ == "__main__":
    main()
