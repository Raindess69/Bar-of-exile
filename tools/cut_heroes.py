#!/usr/bin/env python
"""Hero sheet cutter, hybrid of cut_rows.py (row/col gutter detect + flood-fill
alpha, good on white-bg JPEG sheets) and cut_sprites_v2.py ideas (ONE scale per
hero, ONE canvas per animation, bottom-center anchor -> no jitter/pulsing).

Two phases so a human/agent eyeballs frames between them:

  scan:  python tools/cut_heroes.py scan "assets/WARRIOR MAIN.jpeg" --work _tmp_cut_warrior
         Cuts every row into native-resolution candidate crops
         _tmp_cut_warrior/frames/r<R>_<NN>.png, writes meta.json (sheet coords)
         and montage_r<R>.png per row for eyeball review.
         Per row: gutter-based column detect; if it finds < --min-cols columns
         (frames touching), falls back to uniform --cols split.

  build: python tools/cut_heroes.py build _tmp_cut_warrior/spec.json
         spec.json (written by the reviewer):
           {"id": "warrior", "target_h": 40,
            "walk":   ["r0_00", "r0_01", ...],
            "attack": ["r2_00", "r2_03", ...]}
         Computes ONE scale = target_h / max(bbox height over ALL kept frames),
         renders every frame onto a per-animation shared canvas (height =
         target_h), feet on the bottom edge, x anchored by SHEET CELL center
         (preserves the artist's registration, swooshes stay offset correctly).
         Writes assets/sprites/<id>/walk_NN.png + atk_NN.png,
         assets/sprites/_entries/<id>.json, and QA into the work dir:
         final_montage.png + preview_walk.gif + preview_attack.gif.
         DO NOT accept the cut until the previews look smooth.
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from cut_grid import _bands, _cells_from_gutters, _sprite_alpha

BLANK = 196          # min-channel >= BLANK counts as background-ish (white JPEG)
MIN_PIXELS = 200     # drop specks smaller than this


def _detect_rows(blankish, H):
    gut = _bands(blankish.mean(axis=1), 0.98, max(6, H // 300))
    return _cells_from_gutters(H, gut)


def _detect_cols(strip_blank, W, col_thr, min_cols, force_cols):
    gut = _bands(strip_blank.mean(axis=0), col_thr, 4)
    spans = _cells_from_gutters(W, gut)
    if force_cols or len(spans) < min_cols:
        n = force_cols or 16
        w = W / n
        spans = [(round(i * w), round((i + 1) * w)) for i in range(n)]
    return spans


def scan(sheet, work, col_thr, min_cols, force_cols):
    img = Image.open(sheet).convert("RGB")
    rgb8 = np.asarray(img)
    rgb = rgb8.astype(np.int16)
    H, W = rgb.shape[:2]
    blankish = rgb.min(axis=2) >= BLANK
    work = Path(work)
    fdir = work / "frames"
    fdir.mkdir(parents=True, exist_ok=True)
    meta = {"sheet": str(sheet), "frames": {}}
    for r, (y0, y1) in enumerate(_detect_rows(blankish, H)):
        spans = _detect_cols(blankish[y0:y1], W, col_thr, min_cols, force_cols)
        kept = []
        for (x0, x1) in spans:
            fg = _sprite_alpha(rgb[y0:y1, x0:x1], erode=0, label_frac=0.03)
            if fg is None:
                continue
            ys, xs = np.nonzero(fg)
            if ys.size < MIN_PIXELS:
                continue
            name = f"r{r}_{len(kept):02d}"
            by0, by1 = int(ys.min()), int(ys.max()) + 1
            bx0, bx1 = int(xs.min()), int(xs.max()) + 1
            cell = rgb8[y0:y1, x0:x1]
            rgba = np.dstack([cell[by0:by1, bx0:bx1],
                              (fg[by0:by1, bx0:bx1] * 255).astype(np.uint8)])
            Image.fromarray(rgba, "RGBA").save(fdir / f"{name}.png")
            meta["frames"][name] = {
                "row": r,
                "cell": [int(x0), int(y0), int(x1), int(y1)],
                "bbox": [int(x0 + bx0), int(y0 + by0), int(x0 + bx1), int(y0 + by1)],
            }
            kept.append(name)
        if kept:
            _montage([fdir / f"{n}.png" for n in kept], work / f"montage_r{r}.png",
                     labels=[n.split("_")[1] for n in kept])
        print(f"row {r}: {len(kept)} frames (y {y0}-{y1})")
    with open(work / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    print(f"scan done -> {work}/frames + montage_r*.png ; review, write spec.json, run build")


def _montage(paths, out, labels=None, scale_h=96, bg=(40, 40, 46)):
    imgs = []
    for p in paths:
        im = Image.open(p)
        s = scale_h / im.height
        imgs.append(im.resize((max(1, round(im.width * s)), scale_h), Image.NEAREST))
    W = sum(i.width for i in imgs) + 4 * len(imgs) + 4
    canvas = Image.new("RGB", (W, scale_h + 20), bg)
    x = 4
    from PIL import ImageDraw
    d = ImageDraw.Draw(canvas)
    for k, im in enumerate(imgs):
        canvas.paste(im, (x, 16), im)
        if labels:
            d.text((x + 2, 2), labels[k], fill=(255, 220, 120))
        d.line([(x - 2, 16 + scale_h), (x + im.width + 2, 16 + scale_h)], fill=(200, 60, 60))
        x += im.width + 4
    canvas.save(out)


def build(spec_path):
    spec_path = Path(spec_path)
    work = spec_path.parent
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    meta = json.loads((work / "meta.json").read_text(encoding="utf-8"))["frames"]
    hero, target_h = spec["id"], int(spec.get("target_h", 40))
    anims = {a: spec[a] for a in ("walk", "attack") if spec.get(a)}
    if not anims.get("walk"):
        raise SystemExit("spec must keep at least walk frames")

    kept_all = [n for names in anims.values() for n in names]
    missing = [n for n in kept_all if n not in meta]
    if missing:
        raise SystemExit(f"spec names not in meta.json: {missing}")
    # ONE scale for the whole hero: walk and attack must not change body size
    max_h = max(meta[n]["bbox"][3] - meta[n]["bbox"][1] for n in kept_all)
    s = target_h / max_h

    out_root = Path(spec.get("out", f"assets/sprites/{hero}"))
    if not out_root.is_absolute():
        # resolve against project root, not CWD (script is usually run from tools/)
        out_root = Path(__file__).resolve().parent.parent / out_root
    out_root.mkdir(parents=True, exist_ok=True)
    entry = {"walk": [], "attack": [], "h": target_h}
    prefix = {"walk": "walk", "attack": "atk"}
    for anim, names in anims.items():
        # shared canvas: x-anchor = sheet cell center, y-anchor = bbox bottom
        left = right = 1
        for n in names:
            b, c = meta[n]["bbox"], meta[n]["cell"]
            cx = (c[0] + c[2]) / 2
            left = max(left, math.ceil((cx - b[0]) * s))
            right = max(right, math.ceil((b[2] - cx) * s))
        Wc, Hc = left + right + 2, target_h
        frames = []
        for i, n in enumerate(names):
            b, c = meta[n]["bbox"], meta[n]["cell"]
            cx = (c[0] + c[2]) / 2
            crop = Image.open(work / "frames" / f"{n}.png")
            fw = max(1, round(crop.width * s))
            fh = max(1, round(crop.height * s))
            crop = crop.resize((fw, fh), Image.NEAREST)
            canvas = Image.new("RGBA", (Wc, Hc), (0, 0, 0, 0))
            px = round(1 + left - (cx - b[0]) * s)
            canvas.paste(crop, (px, Hc - fh), crop)
            fname = f"{prefix[anim]}_{i:02d}.png"
            canvas.save(out_root / fname)
            entry[anim].append(fname)
            frames.append(canvas)
        gif = [Image.new("RGB", f.size, (40, 40, 46)) for f in frames]
        for g, f in zip(gif, frames):
            g.paste(f, (0, 0), f)
        gif[0].save(work / f"preview_{anim}.gif", save_all=True,
                    append_images=gif[1:], duration=125, loop=0)
        print(f"{anim}: {len(frames)} frames, canvas {Wc}x{Hc}")

    entries = out_root.parent / "_entries"
    entries.mkdir(exist_ok=True)
    with open(entries / f"{hero}.json", "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=1)
    _montage([out_root / f for a in anims for f in entry[a]],
             work / "final_montage.png",
             labels=[f.split(".")[0] for a in anims for f in entry[a]])
    print(f"build done -> {out_root} + _entries/{hero}.json ; "
          f"CHECK {work}/final_montage.png and preview_*.gif before accepting")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scan")
    sc.add_argument("sheet")
    sc.add_argument("--work", required=True)
    sc.add_argument("--col-thr", type=float, default=0.97)
    sc.add_argument("--min-cols", type=int, default=12,
                    help="fewer detected columns than this -> uniform split")
    sc.add_argument("--cols", type=int, default=0,
                    help="force uniform N-column split for every row")
    bd = sub.add_parser("build")
    bd.add_argument("spec")
    a = ap.parse_args()
    if a.cmd == "scan":
        scan(a.sheet, a.work, a.col_thr, a.min_cols, a.cols)
    else:
        build(a.spec)


if __name__ == "__main__":
    main()
