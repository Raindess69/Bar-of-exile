#!/usr/bin/env python
"""Cut assets/items/*.jpeg icon sheets into assets/icons/<sheet>/<i>.png
and write assets/icons/map.json (base_id -> icon path relative to assets/icons).

Usage: python tools/cut_icons.py [sheet ...]
       (no args = all sheets; e.g. `python tools/cut_icons.py helms boots`)
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.cut_sprites import background_mask, cut

SRC = ROOT / "assets" / "items"
DST = ROOT / "assets" / "icons"
TARGET_H = 26

# Sheets drawn as a uniform grid of cells (cols, rows, inset_px). The generic
# contour cutter breaks on these: helms has ~20px gray gutter lines that
# connect everything into one blob, body/boots have sprites so large that the
# dilation pass merges neighbouring cells. inset_px trims the cell border
# (must cover half the gutter width on helms).
GRIDS = {
    "helms": (5, 5, 14),
    "body": (5, 5, 6),
    "boots": (4, 4, 6),
}


def grid_cut(in_path, out_dir: Path, prefix: str, target_h: int,
             cols: int, rows: int, inset: int, tol: int = 22,
             erode: int = 1) -> list[Path]:
    """Cut a uniform cols x rows grid sheet: one sprite per cell, row-major.

    Each cell is cropped (minus inset), the near-white background is removed
    by flood-fill from the cell border, small specks are dropped, and the
    remaining foreground bbox is saved as a transparent PNG scaled to target_h.
    """
    img = Image.open(in_path).convert("RGB")
    rgb = np.asarray(img)
    h, w = rgb.shape[:2]
    cw, ch = w / cols, h / rows

    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for r in range(rows):
        for c in range(cols):
            x0, x1 = int(c * cw) + inset, int((c + 1) * cw) - inset
            y0, y1 = int(r * ch) + inset, int((r + 1) * ch) - inset
            cell = rgb[y0:y1, x0:x1]
            fg = ~background_mask(cell, tol)
            labels, n = ndimage.label(fg)
            if n == 0:
                print(f"  WARN: empty cell r{r} c{c} in {in_path}", file=sys.stderr)
                continue
            sizes = ndimage.sum_labels(fg, labels, np.arange(1, n + 1))
            keep_ids = np.nonzero(sizes >= max(50.0, 0.005 * sizes.max()))[0] + 1
            fg &= np.isin(labels, keep_ids)
            ys, xs = np.nonzero(fg)
            if ys.size < 50:
                print(f"  WARN: empty cell r{r} c{c} in {in_path}", file=sys.stderr)
                continue
            alpha = fg
            if erode > 0:  # shave the white JPEG halo off sprite edges
                alpha = ndimage.binary_erosion(fg, iterations=erode, border_value=1) & fg
            by0, by1, bx0, bx1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
            rgba = np.dstack([
                cell[by0:by1, bx0:bx1],
                (alpha[by0:by1, bx0:bx1] * 255).astype(np.uint8),
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

# base_id -> icon path, hand-matched by looking at the cut sheets
MAP = {
    # swords / melee
    "rusted_sword": "melee/0.png",
    "long_sword": "melee/1.png",
    "vaal_blade": "melee/3.png",
    # bows
    "crude_bow": "bows/0.png",
    "hunter_bow": "bows/6.png",
    "imperial_bow": "bows/11.png",
    # staves
    "gnarled_staff": "staves/5.png",
    "runic_staff": "staves/1.png",
    "vaal_staff": "staves/4.png",
    # helmets ("helms" cut is broken -> armor sheet)
    "leather_cap": "pixel_art_rpg_armor_icons/icon_r00_c15.png",
    "chain_coif": "pixel_art_rpg_armor_icons/icon_r00_c05.png",
    "great_helm": "pixel_art_rpg_armor_icons/icon_r02_c04.png",
    # body armour (body/0.png has TWO items in one sprite -> armor sheet)
    "leather_vest": "pixel_art_rpg_armor_icons/icon_r04_c14.png",
    "scale_mail": "pixel_art_rpg_armor_icons/icon_r04_c02.png",
    "plate_mail": "body/2.png",
    # boots
    "leather_boots": "pixel_art_rpg_armor_icons/icon_r09_c15.png",
    "chain_boots": "pixel_art_rpg_armor_icons/icon_r08_c00.png",
    "plate_greaves": "pixel_art_rpg_armor_icons/icon_r09_c04.png",
    # gloves
    "leather_gloves": "gloves/0.png",
    "chain_gloves": "gloves/8.png",
    "plate_gauntlets": "gloves/2.png",
    # belts
    "rope_belt": "belts/0.png",
    "studded_belt": "belts/1.png",
    "heavy_belt": "belts/2.png",
    # amulets
    "bone_amulet": "gems/0.png",
    "jade_amulet": "gems/1.png",
    "onyx_amulet": "gems/2.png",
    # rings
    "coral_ring": "rings/0.png",
    "azure_ring": "rings/1.png",
    "ruby_ring": "rings/2.png",
}


def sheet_name(path: Path) -> str:
    """Sheet name from filename: known slot keyword if present, else the
    part before the timestamp (Pixel_art_RPG_icons_<name>_<ts>.jpeg)."""
    parts = [p.lower() for p in path.stem.split("_")]
    known = {"belts", "body", "boots", "bows", "gems", "gloves", "helms",
             "melee", "potions", "rings", "shields", "staves", "white"}
    for p in parts:
        if p in known:
            return p
    return parts[-2]


def main() -> None:
    only = {s.lower() for s in sys.argv[1:]}
    total = 0
    seen: dict[str, int] = {}
    for jpeg in sorted(SRC.glob("*.jpeg")):
        base = sheet_name(jpeg)
        seen[base] = seen.get(base, 0) + 1
        name = base if seen[base] == 1 else f"{base}{seen[base]}"
        if only and name not in only:
            continue
        out = DST / name
        if out.exists():
            for old in out.glob("*.png"):
                old.unlink()
        print(f"[{name}] <- {jpeg.name}")
        if base in GRIDS:
            cols, rows, inset = GRIDS[base]
            saved = grid_cut(jpeg, out, name, TARGET_H, cols, rows, inset)
        else:
            saved = cut(str(jpeg), out, name, TARGET_H)
        for i, p in enumerate(saved):
            p.replace(out / f"{i}.png")
        total += len(saved)

    kept = {k: v for k, v in sorted(MAP.items()) if (DST / v).exists()}
    missing = [k for k in MAP if k not in kept]
    (DST / "map.json").write_text(json.dumps(kept, indent=2) + "\n")
    print(f"\n{total} icons cut, {len(kept)} bases mapped -> {DST / 'map.json'}")
    if missing:
        print("WARN: mapped icons missing on disk:", ", ".join(missing))


if __name__ == "__main__":
    main()
