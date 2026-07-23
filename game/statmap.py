"""v2 stat-key -> engine StatMod mapping (shared by item_roller and tree).

The v2 data files (affixes_v2.json, passives_v2.json) use one stat-key space
(e.g. "physical_damage_inc_pct"). Keys with engine support map to real Stats
fields; the rest become inert StatMods carrying the raw key — apply_mods skips
unknown fields, and display comes from pre-rendered Affix.lines / node stats.
"""
from __future__ import annotations

from game.core import StatMod

# stat key -> (list of Stats fields, bucket "flat"|"inc")
_MAP: dict[str, tuple[list[str], str]] = {
    "life_flat": (["life"], "flat"),
    "life_inc_pct": (["life"], "inc"),
    "physical_damage_inc_pct": (["damage_min", "damage_max"], "inc"),
    "fire_damage_inc_pct": (["added_fire"], "inc"),
    "cold_damage_inc_pct": (["added_cold"], "inc"),
    "lightning_damage_inc_pct": (["added_lightning"], "inc"),
    "elemental_damage_inc_pct": (["added_fire", "added_cold", "added_lightning"], "inc"),
    "attack_speed_inc_pct": (["attack_speed"], "inc"),
    "crit_chance_inc_pct": (["crit_chance"], "inc"),
    "crit_multi_flat": (["crit_multi"], "flat"),
    "armor_flat": (["armor"], "flat"),
    "armor_inc_pct": (["armor"], "inc"),
    "evasion_flat": (["evasion"], "flat"),
    "evasion_inc_pct": (["evasion"], "inc"),
    "fire_res_pct": (["res_fire"], "flat"),
    "cold_res_pct": (["res_cold"], "flat"),
    "lightning_res_pct": (["res_lightning"], "flat"),
    "chaos_res_pct": (["res_chaos"], "flat"),
    "all_res_flat_pct": (["res_fire", "res_cold", "res_lightning", "res_chaos"], "flat"),
    "move_speed_inc_pct": (["move_speed"], "inc"),
    "life_regen_flat": (["life_regen"], "flat"),
    # v3 idle stats: percent values land in dedicated flat fields on Stats,
    # consumed by combat/skills/loot/progression hooks (test_stat_coverage.py)
    "damage_inc_pct": (["damage_inc"], "flat"),
    "aoe_damage_inc_pct": (["aoe_damage_inc"], "flat"),
    "boss_damage_inc_pct": (["boss_damage_inc"], "flat"),
    "dot_damage_inc_pct": (["dot_damage_inc"], "flat"),
    "healing_inc_pct": (["healing_inc"], "flat"),
    "cast_speed_inc_pct": (["cast_speed_inc"], "flat"),
    "cooldown_reduction_pct": (["cooldown_reduction"], "flat"),
    "life_leech_pct": (["life_leech"], "flat"),
    "life_on_kill_flat": (["life_on_kill"], "flat"),
    "gold_find_inc_pct": (["gold_find"], "flat"),
    "item_rarity_inc_pct": (["item_rarity"], "flat"),
    "item_quantity_inc_pct": (["item_quantity"], "flat"),
    "xp_gain_inc_pct": (["xp_gain_inc"], "flat"),
}

# damage_flat_* roll a (lo, hi) pair: physical maps onto the min/max damage
# fields; elemental collapses to the single added_* field (engine has no
# per-element ranges) using the pair average.
_PAIR_MAP: dict[str, tuple[str, str] | str] = {
    "damage_flat_physical": ("damage_min", "damage_max"),
    "damage_flat_fire": "added_fire",
    "damage_flat_cold": "added_cold",
    "damage_flat_lightning": "added_lightning",
    "damage_flat_chaos": "added_chaos",
}


def is_pair_stat(stat: str) -> bool:
    return stat in _PAIR_MAP


def has_engine_support(stat: str) -> bool:
    return stat in _MAP or stat in _PAIR_MAP


def mods_for(stat: str, value: float) -> list[StatMod]:
    """Single-value stat -> StatMods. Unknown keys become one inert raw-key mod."""
    hit = _MAP.get(stat)
    if hit is None:
        return [StatMod(stat, flat=float(value))]  # inert: apply_mods skips it
    fields, bucket = hit
    if bucket == "flat":
        return [StatMod(f, flat=float(value)) for f in fields]
    return [StatMod(f, inc=float(value)) for f in fields]


def mods_for_pair(stat: str, lo: float, hi: float) -> list[StatMod]:
    """damage_flat_* (lo, hi) pair -> StatMods (unknown keys -> inert raw mod)."""
    target = _PAIR_MAP.get(stat)
    if target is None:
        return [StatMod(stat, flat=(float(lo) + float(hi)) / 2)]
    if isinstance(target, tuple):
        lo_f, hi_f = target
        return [StatMod(lo_f, flat=float(lo)), StatMod(hi_f, flat=float(hi))]
    return [StatMod(target, flat=(float(lo) + float(hi)) / 2)]


if __name__ == "__main__":
    m = mods_for("physical_damage_inc_pct", 12)
    assert [x.stat for x in m] == ["damage_min", "damage_max"] and m[0].inc == 12
    m = mods_for("fire_res_pct", 20)
    assert m[0].stat == "res_fire" and m[0].flat == 20
    m = mods_for("bleed_chance_pct", 5)  # no engine support -> inert raw mod
    assert m[0].stat == "bleed_chance_pct"
    m = mods_for_pair("damage_flat_physical", 3, 7)
    assert {(x.stat, x.flat) for x in m} == {("damage_min", 3.0), ("damage_max", 7.0)}
    m = mods_for_pair("damage_flat_fire", 4, 8)
    assert m[0].stat == "added_fire" and m[0].flat == 6.0
    # inert mods must not crash apply_mods
    from game.core import Stats, apply_mods
    s = apply_mods(Stats(), mods_for("bleed_chance_pct", 5) + mods_for("life_flat", 10))
    assert s.life == 60.0
    print("statmap OK")
