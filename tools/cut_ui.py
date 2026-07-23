#!/usr/bin/env python
"""Cut the UI-kit JPEG sheets (white background) into per-element PNGs.

Two phases:
  cut    - flood-fill white bg, connected components, save numbered crops to
           assets/ui/_tmp/<kit>/ plus an indexed contact sheet for eyeballing.
  apply  - move crops to their final folder/name per the hand-filled MAPS
           below, write index.json per target folder. Crops not in a map are
           garbage (text labels, duplicates) and are discarded.

Reuses background_mask / find_frames / sort_boxes from cut_sprites.py.

Usage:
  python tools/cut_ui.py cut
  python tools/cut_ui.py apply
"""
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).parent))
from cut_sprites import background_mask, find_frames, sort_boxes  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
TMP = ASSETS / "ui" / "_tmp"

SHEETS = {
    "buttons": dict(
        src="Pixel_art_UI_buttons_dark_202607150202.jpeg",
        merge=4, tol=24, min_area=400),
    "elements": dict(
        src="Pixel_art_UI_elements_Diablo_202607150203.jpeg",
        merge=6, tol=24, min_area=400),
    "iconscursors": dict(
        src="Pixel_art_UI_icons_cursors_202607150204.jpeg",
        merge=10, tol=24, min_area=400),
    "frames": dict(
        src="Pixel_art_inventory_frames_and_202607150203.jpeg",
        merge=8, tol=24, min_area=150),
}

# kit -> [crop indices]: crops that hold several welded elements (e.g. the
# orb strips); re-split with merge=0 into <kit>_<idx>s<j>.png sub-crops.
SPLITS = {"elements": [4, 5]}

# kit -> {crop_index: ("<subdir>/<final_name>.png", "description")}
# Filled in by hand after reviewing the contact sheets. Subdir is relative
# to assets/ui/. Indices absent here are discarded as garbage.
MAPS: dict[str, dict[int, tuple[str, str]]] = {}


def cut_sheet(kit, cfg):
    img = Image.open(ASSETS / cfg["src"]).convert("RGB")
    rgb = np.asarray(img)
    bg = background_mask(rgb, cfg["tol"])
    fg = ~bg
    boxes = [b for b in find_frames(fg, cfg["merge"]) if b[4] >= cfg["min_area"]]
    boxes = sort_boxes(boxes)
    # re-split welded strips (e.g. orb rows) with a tiny merge radius
    final = []
    for i, b in enumerate(boxes):
        if i in SPLITS.get(kit, []):
            x0, y0, x1, y1, _ = b
            subs = [s for s in find_frames(fg[y0:y1, x0:x1], 2)
                    if s[4] >= cfg["min_area"]]
            for s in sort_boxes(subs):
                final.append((x0 + s[0], y0 + s[1], x0 + s[2], y0 + s[3], s[4]))
        else:
            final.append(b)
    boxes = final
    out = TMP / kit
    out.mkdir(parents=True, exist_ok=True)
    alpha_full = ndimage.binary_erosion(fg, iterations=1, border_value=1)
    crops = []
    for i, (x0, y0, x1, y1, _) in enumerate(boxes):
        a = alpha_full[y0:y1, x0:x1] & fg[y0:y1, x0:x1]
        ys, xs = np.nonzero(a)
        if ys.size == 0:
            continue
        ty0, ty1, tx0, tx1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        rgba = np.dstack([
            rgb[y0 + ty0:y0 + ty1, x0 + tx0:x0 + tx1],
            (a[ty0:ty1, tx0:tx1] * 255).astype(np.uint8),
        ])
        p = out / f"{kit}_{len(crops):03d}.png"
        Image.fromarray(rgba, "RGBA").save(p)
        crops.append(p)
    print(f"{kit}: {len(crops)} crops")
    montage(kit, crops)


def montage(kit, crops, thumb=150, cols=8):
    if not crops:
        return
    pad, label_h = 6, 14
    rows = (len(crops) + cols - 1) // cols
    cw, ch = thumb + pad * 2, thumb + label_h + pad * 2
    sheet = Image.new("RGB", (cols * cw, rows * ch), (235, 235, 235))
    d = ImageDraw.Draw(sheet)
    for i, p in enumerate(crops):
        im = Image.open(p)
        s = min(thumb / im.width, thumb / im.height, 1.0)
        im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))),
                       Image.NEAREST)
        cx, cy = (i % cols) * cw, (i // cols) * ch
        sheet.paste(im, (cx + pad + (thumb - im.width) // 2,
                         cy + pad + (thumb - im.height) // 2),
                    im if im.mode == "RGBA" else None)
        d.text((cx + pad, cy + thumb + pad + 1), str(i), fill=(180, 0, 0))
    dest = TMP / f"_montage_{kit}.png"
    sheet.save(dest)
    print(f"  montage -> {dest}")


def apply_maps():
    indexes: dict[Path, dict] = {}
    for kit, mapping in MAPS.items():
        for idx, (rel, desc) in mapping.items():
            src = TMP / kit / f"{kit}_{idx:03d}.png"
            dst = ASSETS / "ui" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            indexes.setdefault(dst.parent, {})[dst.name] = desc
    for folder, files in indexes.items():
        data = {"files": dict(sorted(files.items()))}
        (folder / "index.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{folder.relative_to(ASSETS)}: {len(files)} files + index.json")


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "cut"
    if phase == "cut":
        for kit, cfg in SHEETS.items():
            cut_sheet(kit, cfg)
    elif phase == "apply":
        apply_maps()
    else:
        sys.exit(f"unknown phase {phase!r}")
