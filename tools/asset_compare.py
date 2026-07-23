"""Read-only: side-by-side CURRENT vfx vs NEW candidate for REPL folders.
For each `new assets/<name>` whose base skill has existing assets/vfx/skill_<base>,
draw two mid-frames: current (left) vs new (right). Lets a human pick upgrades.
Writes docs/_asset_compare.png. No game files touched.
"""
import os
import re

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEW = os.path.join(ROOT, "new assets")
VFX = os.path.join(ROOT, "assets", "vfx")

CELL = 96
PAD = 3
LABEL_W = 150
ROW_H = CELL + PAD


def mid_png(folder, prefix=""):
    if not os.path.isdir(folder):
        return None
    pngs = sorted(f for f in os.listdir(folder) if f.lower().endswith(".png"))
    if not pngs:
        return None
    return os.path.join(folder, pngs[len(pngs) // 2])


def draw_img(sheet, draw, path, x, y):
    for by in range(0, CELL, 12):
        for bx in range(0, CELL, 12):
            if (bx // 12 + by // 12) % 2 == 0:
                draw.rectangle([x + bx, y + by, x + bx + 11, y + by + 11],
                               fill=(44, 44, 52, 255))
    if path:
        im = Image.open(path).convert("RGBA")
        im.thumbnail((CELL, CELL), Image.LANCZOS)
        sheet.alpha_composite(im, (x + (CELL - im.width) // 2,
                                   y + (CELL - im.height) // 2))


def main():
    repl = []
    for d in sorted(os.listdir(NEW)):
        fp = os.path.join(NEW, d)
        if not os.path.isdir(fp) or d.startswith("_"):
            continue
        base = re.sub(r"_v[234]$", "", d)
        cur = os.path.join(VFX, f"skill_{base}")
        if d != base and os.path.isdir(cur):
            repl.append((d, base, cur, fp))

    H = PAD + len(repl) * ROW_H
    W = LABEL_W + 2 * (CELL + PAD) + PAD + 60
    sheet = Image.new("RGBA", (W, H), (24, 24, 30, 255))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 12)
        small = ImageFont.truetype("arial.ttf", 10)
    except Exception:
        font = small = ImageFont.load_default()

    hx1 = LABEL_W
    hx2 = LABEL_W + CELL + PAD
    for i, (name, base, cur, new) in enumerate(repl):
        y = PAD + i * ROW_H
        draw.text((4, y + CELL // 2 - 10), name, fill=(255, 220, 120, 255),
                  font=font)
        draw.text((4, y + CELL // 2 + 4), f"→ skill_{base}",
                  fill=(150, 150, 150, 255), font=small)
        draw_img(sheet, draw, mid_png(cur), hx1, y)
        draw_img(sheet, draw, mid_png(new), hx2, y)
        draw.rectangle([hx1, y, hx1 + CELL, y + CELL],
                       outline=(120, 120, 120, 255), width=1)
        draw.rectangle([hx2, y, hx2 + CELL, y + CELL],
                       outline=(120, 200, 255, 255), width=1)
    # column headers
    draw.text((hx1, 1), "CURRENT", fill=(180, 180, 180, 255), font=small)
    draw.text((hx2, 1), "NEW", fill=(120, 200, 255, 255), font=small)
    out = os.path.join(ROOT, "docs", "_asset_compare.png")
    sheet.convert("RGB").save(out)
    print("wrote", out, sheet.size, "pairs:", len(repl))


if __name__ == "__main__":
    main()
