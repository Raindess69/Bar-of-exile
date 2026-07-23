"""Compose btn_stash / btn_vendor / btn_zones for the strip from existing assets:
btn_minimize frame (dash erased) + a loot/marker icon. One-shot, idempotent."""
from __future__ import annotations

import os

from PIL import Image, ImageEnhance

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BTN = os.path.join(ROOT, "assets", "ui", "buttons")

SOURCES = {
    "btn_stash": os.path.join(ROOT, "assets", "icons",
                              "pixel_art_loot_economy_icons", "icon_r01_c00.png"),
    "btn_vendor": os.path.join(ROOT, "assets", "icons",
                               "pixel_art_loot_economy_icons", "icon_r00_c04.png"),
    "btn_zones": os.path.join(ROOT, "assets", "ui", "icons", "marker_waypoint.png"),
}


def blank_frame() -> Image.Image:
    im = Image.open(os.path.join(BTN, "btn_minimize.png")).convert("RGBA")
    w, h = im.size
    bg = im.getpixel((w // 2, h // 2 - 90))
    cx, cy = w // 2, h // 2
    for x in range(cx - 120, cx + 120):
        for y in range(cy - 60, cy + 60):
            im.putpixel((x, y), bg)
    return im


def main() -> None:
    for name, src in SOURCES.items():
        frame = blank_frame()
        w, h = frame.size
        icon = Image.open(src).convert("RGBA")
        target = int(min(w, h) * 0.55)
        k = target / max(icon.size)
        icon = icon.resize((max(1, int(icon.width * k)), max(1, int(icon.height * k))),
                           Image.LANCZOS)
        frame.alpha_composite(icon, ((w - icon.width) // 2, (h - icon.height) // 2))
        frame.save(os.path.join(BTN, f"{name}.png"))
        ImageEnhance.Brightness(frame).enhance(1.3).save(
            os.path.join(BTN, f"{name}_hover.png"))
        print(name, "ok")


if __name__ == "__main__":
    main()
