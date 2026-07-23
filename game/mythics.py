"""Mythic items (Tier 9 of the 10-tier rarity ladder).

A Mythic is a red (#e0483a) fixed "uber unique": a hand-designed chase item that
drops ONLY from act bosses and rift bosses (the caller gates the drop source).
Mechanically it mirrors a Unique — a fixed mod set with small random rolls — but
tuned stronger and carrying one EXTRA unique-tier mod (spec: "+1 unique mod").

This module MIRRORS game.uniques exactly so economy valuation and save round-trip
behave identically: same def-dataclass shape, same tuple mod format
(stat "a|b", lo, hi, "flat"|"inc"), same statmap routing, same _build that emits
a single tier-0 Affix with the fixed mods (plus an optional text-only special
Affix). Only the rarity (MYTHIC), the pool, and the boss gate differ.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from game import statmap
from game.core import Affix, Item, Rarity, Slot, StatMod
from game.items import BASES, make_base_item

# spec: Mythics are a boss-only endgame chase; nothing below this ilvl may roll one.
MYTHIC_MIN_ILVL = 60


@dataclass(frozen=True)
class MythicDef:
    id: str
    name: str
    base_id: str
    ilvl_req: int
    # (stats "a|b" — one roll shared by all, lo, hi, "flat"|"inc"); same format as UniqueDef
    mods: tuple[tuple[str, float, float, str], ...]
    flavor: str
    weight: float = 1.0  # relative drop weight within the mythic pool
    # (special_id, display text) — text-only tooltip lines, mirrors UniqueDef.special
    special: tuple[tuple[str, str], ...] = ()


# 12 hand-designed uber-uniques, one per weapon class + every armour/jewellery slot.
# Each carries a unique's worth of power PLUS one extra strong mod, gated to bosses.
MYTHICS: tuple[MythicDef, ...] = (
    # --- weapons, one per class ---
    MythicDef("ruin_the_world_ender", "Ruin, the World-Ender", "vaal_blade", 68, (
        ("damage_min|damage_max", 80, 100, "inc"),
        ("crit_multi", 40, 55, "flat"),
        ("attack_speed", 12, 18, "inc"),
        ("added_fire", 20, 30, "flat"),
        ("life", 40, 60, "flat"),          # +1 mythic mod (life on a weapon)
    ), "It was named after the last thing it did.", weight=1.0, special=(
        ("boss_damage", "+40% Damage during boss and rift-boss fights"),
    )),
    MythicDef("skyfall_the_horizons_end", "Skyfall, the Horizon's End", "imperial_bow", 66, (
        ("damage_min|damage_max", 70, 95, "inc"),
        ("attack_speed", 20, 28, "inc"),
        ("crit_chance", 25, 35, "inc"),
        ("move_speed", 12, 16, "inc"),
        ("added_cold", 18, 28, "flat"),    # +1 mythic mod
    ), "Every arrow is the horizon arriving early.", weight=1.0),
    MythicDef("oblivions_whisper", "Oblivion's Whisper", "vaal_staff", 70, (
        ("added_lightning", 30, 45, "flat"),
        ("damage_inc_pct", 30, 40, "flat"),   # statmap -> Stats.damage_inc
        ("crit_chance", 30, 40, "inc"),
        ("crit_multi", 30, 45, "flat"),
        ("life", 40, 60, "flat"),          # +1 mythic mod
    ), "It does not speak. It ends the need for speaking.", weight=0.9),
    MythicDef("godsplitter", "Godsplitter", "vaal_axe", 68, (
        ("damage_min|damage_max", 100, 130, "inc"),
        ("crit_multi", 45, 60, "flat"),
        ("boss_damage_inc_pct", 25, 35, "flat"),  # statmap -> Stats.boss_damage_inc
        ("life", 50, 70, "flat"),          # +1 mythic mod
    ), "The first god it met, it split. There was no second.", weight=0.9),
    MythicDef("dawnbringer_the_last_light", "Dawnbringer, the Last Light", "vaal_sceptre", 66, (
        ("added_fire", 25, 40, "flat"),
        ("life_regen", 5, 8, "flat"),
        ("life", 60, 80, "flat"),
        ("res_fire", 25, 30, "flat"),
        ("healing_inc_pct", 20, 30, "flat"),   # statmap -> Stats.healing_inc; +1 mythic mod
    ), "When the last sun died, someone kept one ember.", weight=1.0),
    # --- armour ---
    MythicDef("crown_of_the_fallen_god", "Crown of the Fallen God", "great_helm", 65, (
        ("armor", 100, 140, "inc"),
        ("life", 70, 90, "flat"),
        ("res_chaos", 20, 25, "flat"),
        ("crit_multi", 25, 35, "flat"),    # +1 mythic mod (offence on a helm)
    ), "A god fell. Someone kept the head.", weight=1.0),
    MythicDef("aegis_eternal", "Aegis Eternal", "plate_mail", 70, (
        ("armor", 150, 200, "inc"),
        ("life", 90, 120, "flat"),
        ("res_fire|res_cold|res_lightning", 20, 25, "flat"),
        ("life_regen", 4, 6, "flat"),      # +1 mythic mod
    ), "Nothing has ever reached the body beneath.", weight=0.85),
    MythicDef("grasp_of_annihilation", "Grasp of Annihilation", "plate_gauntlets", 64, (
        ("attack_speed", 12, 16, "inc"),
        ("damage_min|damage_max", 30, 45, "inc"),
        ("life", 40, 55, "flat"),
        ("life_leech_pct", 3, 3, "flat"),  # statmap -> Stats.life_leech; +1 mythic mod
    ), "It takes. That is the entire design.", weight=1.0, special=(
        ("life_leech", "Leech 3% of damage dealt as Life"),
    )),
    MythicDef("strides_of_the_titan", "Strides of the Titan", "plate_greaves", 62, (
        ("move_speed", 28, 35, "inc"),
        ("armor", 80, 110, "inc"),
        ("life", 45, 60, "flat"),
        ("evasion", 40, 60, "flat"),       # +1 mythic mod
    ), "Each step was a country. There were not many steps.", weight=1.0),
    # --- jewellery and belt ---
    MythicDef("girdle_of_the_world_serpent", "Girdle of the World Serpent", "heavy_belt", 64, (
        ("life", 90, 120, "flat"),
        ("armor", 60, 90, "flat"),
        ("damage_min|damage_max", 25, 35, "inc"),
        ("res_chaos", 20, 25, "flat"),     # +1 mythic mod
    ), "It once held the world together. It settles for your waist.", weight=1.0),
    MythicDef("heart_of_eternity", "Heart of Eternity", "onyx_amulet", 68, (
        ("crit_multi", 40, 55, "flat"),
        ("crit_chance", 30, 40, "inc"),
        ("life", 50, 70, "flat"),
        ("damage_inc_pct", 20, 30, "flat"),   # statmap -> Stats.damage_inc; +1 mythic mod
    ), "It has beaten longer than the word for 'always'.", weight=0.9),
    MythicDef("band_of_the_infinite", "Band of the Infinite", "ruby_ring", 60, (
        ("added_fire", 15, 25, "flat"),
        ("res_fire", 25, 30, "flat"),
        ("life", 40, 55, "flat"),
        ("item_rarity_inc_pct", 20, 30, "flat"),  # statmap -> Stats.item_rarity; +1 mythic mod
    ), "A circle has no end. Neither does what it draws to you.", weight=1.1),
)


def _make_base(base_id: str, ilvl: int) -> Item:
    # every mythic uses a real dropping base; mirror uniques' construction path.
    return make_base_item(base_id, ilvl)


def _roll_mods(m: MythicDef, rng: random.Random) -> list[StatMod]:
    """Identical mechanism to uniques._roll_mods: one roll per line, split '|'
    onto each stat, statmap-routed keys go through statmap (it picks its bucket),
    direct engine fields keep their flat/inc kind."""
    mods: list[StatMod] = []
    for stats, lo, hi, kind in m.mods:
        if float(lo).is_integer() and float(hi).is_integer():
            val: float = rng.randint(int(lo), int(hi))
        else:
            val = round(rng.uniform(lo, hi), 1)
        for stat in stats.split("|"):
            if statmap.has_engine_support(stat):
                mods.extend(statmap.mods_for(stat, val))
            else:
                mods.append(StatMod(stat, flat=val) if kind == "flat" else StatMod(stat, inc=val))
    return mods


def _build(mdef: MythicDef, ilvl: int, rng: random.Random) -> Item:
    """Construct a Rarity.MYTHIC Item exactly like uniques._build: a single
    tier-0 prefix Affix carrying the fixed mods, item.name set to the mythic name,
    plus an optional text-only special Affix (Affix.lines) when defined."""
    item = _make_base(mdef.base_id, ilvl)
    item.rarity = Rarity.MYTHIC
    item.name = mdef.name
    item.req_level = max(item.req_level, mdef.ilvl_req)
    item.affixes = [Affix(id=mdef.id, name=mdef.name, is_prefix=True, tier=0,
                          mods=_roll_mods(mdef, rng))]
    if mdef.special:
        item.affixes.append(Affix(id=mdef.id + "_special", name=mdef.name, is_prefix=False,
                                  tier=0, mods=[], lines=[t for _, t in mdef.special]))
    return item


def roll_mythic(ilvl: int, rng: random.Random, min_ilvl: int = MYTHIC_MIN_ILVL) -> Item | None:
    """Weighted pick among mythics whose ilvl_req <= ilvl, gated to ilvl >= min_ilvl.
    Returns None below the gate or when no mythic qualifies. The CALLER must gate the
    drop source (act boss / rift boss only) — no source gating happens here."""
    if ilvl < min_ilvl:
        return None
    pool = [m for m in MYTHICS if m.ilvl_req <= ilvl]
    if not pool:
        return None
    chosen = rng.choices(pool, weights=[m.weight for m in pool], k=1)[0]
    return _build(chosen, ilvl, rng)


if __name__ == "__main__":
    assert 8 <= len(MYTHICS) <= 12, len(MYTHICS)
    assert len({m.id for m in MYTHICS}) == len(MYTHICS), "duplicate mythic id"
    for m in MYTHICS:
        assert m.base_id in BASES, m.base_id
        assert m.ilvl_req >= 1
    rng = random.Random(7)
    for m in MYTHICS:
        it = _build(m, max(m.ilvl_req, MYTHIC_MIN_ILVL), rng)
        assert it.rarity is Rarity.MYTHIC and it.affixes[0].mods, m.id
        print(f"{it.display_name():32s} [{it.base_name}, {it.slot.value}, req {it.req_level}]")
        for mod in it.affixes[0].mods:
            print("   " + mod.describe())
    print(f"\nmythics OK: {len(MYTHICS)} defs")
