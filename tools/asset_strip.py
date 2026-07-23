"""Read-only: build animation strips for chosen folders in `new assets`.
Usage: python tools/asset_strip.py folderA folderB ...
Each folder -> one row of up to 10 evenly-sampled frames on checkerboard.
Writes docs/_asset_strip.png. No game files touched.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEW = os.path.join(ROOT, "new assets")

CELL = 120
PAD = 3
LABEL_W = 130
NFR = 9


def frames(folder):
    pngs = sorted(f for f in os.listdir(folder) if f.lower().endswith(".png"))
    if not pngs:
        return []
    if len(pngs) <= NFR:
        pick = pngs
    else:
        step = (len(pngs) - 1) / (NFR - 1)
        pick = [pngs[round(i * step)] for i in range(NFR)]
    return [os.path.join(folder, p) for p in pick]


def main():
    names = sys.argv[1:]
    rows = []
    for n in names:
        fp = os.path.join(NEW, n)
        if os.path.isdir(fp):
            rows.append((n, frames(fp)))
    ncol = max((len(f) for _, f in rows), default=0)
    W = LABEL_W + ncol * (CELL + PAD) + PAD
    H = len(rows) * (CELL + PAD) + PAD
    sheet = Image.new("RGBA", (W, H), (24, 24, 30, 255))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 13)
    except Exception:
        font = ImageFont.load_default()
    for r, (name, fs) in enumerate(rows):
        y = PAD + r * (CELL + PAD)
        draw.text((4, y + CELL // 2 - 6), name, fill=(255, 220, 120, 255),
                  font=font)
        for c, f in enumerate(fs):
            x = LABEL_W + c * (CELL + PAD)
            for by in range(0, CELL, 15):
                for bx in range(0, CELL, 15):
                    if (bx // 15 + by // 15) % 2 == 0:
                        draw.rectangle([x + bx, y + by, x + bx + 14, y + by + 14],
                                       fill=(44, 44, 52, 255))
            im = Image.open(f).convert("RGBA")
            im.thumbnail((CELL, CELL), Image.LANCZOS)
            sheet.alpha_composite(im, (x + (CELL - im.width) // 2,
                                       y + (CELL - im.height) // 2))
    out = os.path.join(ROOT, "docs", "_asset_strip.png")
    sheet.convert("RGB").save(out)
    print("wrote", out, sheet.size)


if __name__ == "__main__":
    main()
