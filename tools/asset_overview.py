"""Read-only: build a contact-sheet overview of every folder in `new assets`.
One representative (middle) frame per folder, downscaled, labelled with the
folder name and whether a matching vfx already exists. No game files touched.
"""
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEW = os.path.join(ROOT, "new assets")
VFX = os.path.join(ROOT, "assets", "vfx")

CELL_W, CELL_H = 150, 150
PAD = 4
LABEL_H = 26
COLS = 6


def existing_vfx_names():
    if not os.path.isdir(VFX):
        return set()
    return {d for d in os.listdir(VFX) if os.path.isdir(os.path.join(VFX, d))}


def mid_frame(folder):
    pngs = sorted(f for f in os.listdir(folder)
                  if f.lower().endswith(".png"))
    if not pngs:
        return None
    return os.path.join(folder, pngs[len(pngs) // 2])


def main():
    vfx = existing_vfx_names()
    folders = sorted(d for d in os.listdir(NEW)
                     if os.path.isdir(os.path.join(NEW, d))
                     and not d.startswith("_"))
    rows = (len(folders) + COLS - 1) // COLS
    W = COLS * (CELL_W + PAD) + PAD
    H = rows * (CELL_H + LABEL_H + PAD) + PAD
    sheet = Image.new("RGBA", (W, H), (24, 24, 30, 255))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 12)
    except Exception:
        font = ImageFont.load_default()

    for i, name in enumerate(folders):
        r, c = divmod(i, COLS)
        x = PAD + c * (CELL_W + PAD)
        y = PAD + r * (CELL_H + LABEL_H + PAD)
        fp = mid_frame(os.path.join(NEW, name))
        # checkerboard so transparent regions are visible
        for by in range(0, CELL_H, 16):
            for bx in range(0, CELL_W, 16):
                if (bx // 16 + by // 16) % 2 == 0:
                    draw.rectangle([x + bx, y + by, x + bx + 15, y + by + 15],
                                   fill=(44, 44, 52, 255))
        if fp:
            im = Image.open(fp).convert("RGBA")
            im.thumbnail((CELL_W, CELL_H), Image.LANCZOS)
            ox = x + (CELL_W - im.width) // 2
            oy = y + (CELL_H - im.height) // 2
            sheet.alpha_composite(im, (ox, oy))
        # classify
        base = name
        for suf in ("_v2", "_v3", "_v4"):
            if base.endswith(suf):
                base = base[: -len(suf)]
                break
        has_vfx = f"skill_{base}" in vfx
        tag = "REPL" if (has_vfx and base != name) else (
            "src" if has_vfx else "NEW?")
        color = {"REPL": (120, 200, 255, 255), "src": (150, 150, 150, 255),
                 "NEW?": (255, 180, 90, 255)}[tag]
        draw.rectangle([x, y, x + CELL_W, y + CELL_H], outline=color, width=2)
        draw.text((x + 2, y + CELL_H + 2), f"{name}", fill=(235, 235, 235, 255),
                  font=font)
        draw.text((x + 2, y + CELL_H + 14), f"[{tag}]", fill=color, font=font)

    out = os.path.join(ROOT, "docs", "_asset_overview.png")
    sheet.convert("RGB").save(out)
    print("wrote", out, sheet.size, "folders:", len(folders))


if __name__ == "__main__":
    main()
