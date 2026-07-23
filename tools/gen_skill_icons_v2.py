"""Assign a themed spell icon to every Skills V2 skill (80) from the
pixel_art_rpg_spell_icons pack (1013 icons, 24x44 grid), and write the result
into assets/icons/skills_map.json.

Strategy: classify each icon by the dominant hue of its non-dark pixels into a
colour bucket (fire/cold/lightning/poison/arcane/holy/steel), then hand each
skill an icon from the bucket that fits its damage type + tags. Deterministic:
sorted iteration, no RNG, no game/* imports. Icons are never reused across
skills. Re-run:  python tools/gen_skill_icons_v2.py
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = ROOT / "assets" / "icons"
PACK = "pixel_art_rpg_spell_icons"
PACK_DIR = ICON_DIR / PACK
SKILLS_JSON = ROOT / "data" / "skills_v2.json"
OUT = ICON_DIR / "skills_map.json"

_app = QApplication.instance() or QApplication([])


def classify(path: Path) -> str | None:
    """Colour bucket of an icon from the average of its bright pixels."""
    img = QImage(str(path))
    if img.isNull():
        return None
    w, h = img.width(), img.height()
    tr = tg = tb = cnt = 0
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            c = img.pixelColor(x, y)
            r, g, b = c.red(), c.green(), c.blue()
            if max(r, g, b) < 50:  # background
                continue
            tr += r; tg += g; tb += b; cnt += 1
    if cnt < 20:
        return None
    r, g, b = tr / cnt, tg / cnt, tb / cnt
    mx = max(r, g, b)
    # normalized channel dominance
    warm = r - b            # >0 warm, <0 cool
    if g > r * 0.95 and g > b * 1.15 and r < g * 0.9:
        return "poison"      # green dominant
    if b > r * 1.15 and b > g * 1.05:
        return "cold"        # blue dominant
    if r > 130 and g > 110 and b < g * 0.75 and abs(r - g) < 60:
        return "holy"        # gold: high r+g, low b, r~g
    if r > 150 and g > 120 and b < 90 and r - g < 90 and g > b * 1.3:
        return "lightning"   # yellow: r,g high, b low, r~g
    if r > b and g < r * 0.75 and b < r * 0.7:
        return "fire"        # orange/red: r>>g>=b
    if b > g and r > g and abs(r - b) < 60 and b > 80:
        return "arcane"      # purple: r+b high, g low
    if warm > 15 and g < r:
        return "fire"
    return "steel"           # grey / neutral / weapon


def load_buckets() -> dict[str, list[str]]:
    files = sorted(f for f in os.listdir(PACK_DIR)
                   if re.match(r"icon_r\d+_c\d+\.png", f))
    buckets: dict[str, list[str]] = {}
    for f in files:
        b = classify(PACK_DIR / f)
        if b:
            buckets.setdefault(b, []).append(f)
    return buckets


def _col_cells(cols: list[int]) -> list[str]:
    """Every existing icon in the given grid columns, top-to-bottom then
       left-to-right — used to hand-curate weapon/bow pools the colour
       classifier can't distinguish (a steel sword vs a grey butterfly)."""
    out = []
    for c in cols:
        for r in range(24):
            f = f"icon_r{r:02d}_c{c:02d}.png"
            if (PACK_DIR / f).exists():
                out.append(f)
    return out


# curated physical-weapon columns (read off the contact sheet):
#   c06/c08 = steel swords, c05/c09 = more blades  -> warrior
#   c22/c37/c38 = red & heavy blades/axes          -> barbarian
#   c10/c40 = bows & crossbows                      -> archer
WEAPON_STEEL_COLS = [8, 6, 5, 9]
WEAPON_HEAVY_COLS = [22, 37, 38, 39]
BOW_COLS = [40, 10, 41]


# damage_type + tag -> ordered list of buckets to draw from (first non-empty).
# Physical skills route to curated weapon pools by class so warriors get swords,
# barbarians get axes and archers get bows instead of colour-guessed junk.
def preferred_buckets(skill: dict) -> list[str]:
    dt = skill["damage_type"]
    tags = set(skill["tags"])
    cid = skill["class"]
    if "heal" in tags or skill["id"] in ("heal", "second_wind"):
        return ["holy", "poison", "steel"]
    if "poison" in tags or (dt == "chaos" and "arcane" not in tags):
        return ["poison", "arcane", "steel"]
    if "holy" in tags:
        return ["holy", "lightning", "steel"]
    if "arcane" in tags:
        return ["arcane", "cold", "steel"]
    if dt == "fire":
        return ["fire", "lightning", "steel"]
    if dt == "cold":
        return ["cold", "arcane", "steel"]
    if dt == "lightning":
        return ["lightning", "arcane", "steel"]
    # physical: buffs/auras stay neutral-holy (banners/roars), attacks get weapons
    if "buff" in tags or skill["type"] == "aura":
        return ["holy", "steel"]
    if cid == "archer":
        return ["bow", "steel"]
    if cid == "barbarian":
        return ["weapon_heavy", "weapon_steel", "steel"]
    return ["weapon_steel", "weapon_heavy", "steel"]  # warrior + phys cleric


def main() -> None:
    raw = json.loads(SKILLS_JSON.read_text(encoding="utf-8"))
    skills = raw["skills"]
    buckets = load_buckets()
    # inject curated weapon pools (deterministic, column-ordered)
    buckets["weapon_steel"] = _col_cells(WEAPON_STEEL_COLS)
    buckets["weapon_heavy"] = _col_cells(WEAPON_HEAVY_COLS)
    buckets["bow"] = _col_cells(BOW_COLS)
    print("bucket sizes:", {k: len(v) for k, v in sorted(buckets.items())})

    # deterministic cursor per bucket so icons are never reused
    cursor = {k: 0 for k in buckets}
    used: set[str] = set()

    def take(bucket: str) -> str | None:
        lst = buckets.get(bucket, [])
        while cursor[bucket] < len(lst):
            f = lst[cursor[bucket]]
            cursor[bucket] += 1
            if f not in used:
                used.add(f)
                return f
        return None

    mapping: dict[str, str] = {}
    misses: list[str] = []
    # stable order: class, then unlock order as in json
    for s in skills:
        for bucket in preferred_buckets(s):
            f = take(bucket)
            if f:
                mapping[s["id"]] = f"{PACK}/{f}"
                break
        else:
            misses.append(s["id"])

    # fallback: any leftover icon for anything that missed
    leftovers = [f for lst in buckets.values() for f in lst if f not in used]
    for sid in misses:
        if leftovers:
            f = leftovers.pop()
            mapping[sid] = f"{PACK}/{f}"

    mapping = dict(sorted(mapping.items()))
    OUT.write_text(json.dumps(mapping, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"wrote {len(mapping)}/80 skill icons to {OUT.relative_to(ROOT)}")
    if len(mapping) < len(skills):
        print("MISSING:", set(s["id"] for s in skills) - set(mapping))


if __name__ == "__main__":
    main()
