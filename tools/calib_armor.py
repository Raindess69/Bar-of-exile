"""READ-ONLY armor-formula calibrator. Imports the real curves and reports
mitigation / effective-EHP / TTK at the melee death-wall points (ml42, ml48)
for candidate values of the K coefficient in armor/(armor+K*raw).

Does NOT modify any game code. Prints a table so we pick K on numbers, not vibes.
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from game import classes, world

def mitig(raw, armor, K):
    if raw <= 0:
        return 0.0
    red = armor / (armor + K * raw)
    return min(red, 0.9)

def hero_stats_at(class_id, level):
    h = classes.make_hero(class_id)
    h.level = level
    classes.apply_level_growth(h)
    return h.stats

# --- monster raw phys per hit at a given mlvl for a template ---
def mob_raw(tpl, mlvl):
    m = mlvl - 1
    dm = world.mob_dmg_mult(m)
    avg = (tpl.base_dmin + tpl.base_dmax) / 2 * dm
    return avg

def mob_armor(tpl, mlvl):
    return tpl.armor * (1 + 0.10 * (mlvl - 1))

WARLORD = world.TEMPLATES["orc_warlord"]
# a representative a3 trash mob at ml42 for deep_canopy
TRASH = world.TEMPLATES.get("blood_ape") or WARLORD

CASES = [
    ("deep_canopy trash", TRASH, 42),
    ("Orc Warlord",       WARLORD, 48),
]
MELEE = [("warrior", 47), ("barbarian", 45), ("cleric", 49)]
Ks = [10.0, 6.0, 4.0, 3.0, 2.0]

print("=== HERO SURVIVAL: mitigation of incoming phys & hits-to-die (no gear) ===")
for cname, tpl, mlvl in CASES:
    raw = mob_raw(tpl, mlvl)
    aps = tpl.attack_speed
    print(f"\n-- {cname} @ ml{mlvl}: raw≈{raw:.0f}/hit, {aps} aps --")
    print(f"{'class(lv)':<14}{'armor':>7}{'life':>7} | " +
          "".join(f"K={k:<4g}dmg/hit  hits  ttl(s)   ".ljust(26) for k in Ks))
    for cid, lv in MELEE:
        s = hero_stats_at(cid, lv)
        row = f"{cid+'('+str(lv)+')':<14}{s.armor:>7.0f}{s.life:>7.0f} | "
        for k in Ks:
            d = raw * (1 - mitig(raw, s.armor, k))
            hits = s.life / d if d > 0 else 999
            ttl = hits / aps
            row += f"{d:>6.0f}  {hits:>4.1f}  {ttl:>5.1f}      "
        print(row)

print("\n\n=== HERO OFFENSE SANITY: does the hero still punch through mob armor? ===")
print("(hero raw phys vs mob armor at ml48; want mitigation to stay LOW)")
for cid, lv in MELEE:
    s = hero_stats_at(cid, lv)
    hero_raw = (s.damage_min + s.damage_max) / 2  # base weapon, pre-skill
    war_arm = mob_armor(WARLORD, 48)
    print(f"\n{cid}(lv{lv}) base weapon raw≈{hero_raw:.0f} vs Warlord armor {war_arm:.0f}:")
    for k in Ks:
        red = mitig(hero_raw, war_arm, k) * 100
        print(f"   K={k:<4g} -> mob mitigates {red:>4.1f}% of hero phys")
