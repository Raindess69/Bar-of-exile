"""Unique special-mechanic wiring (single source of truth).

Uniques carry a `special` tuple of (special_id, display_text) — see
game.uniques.UniqueDef. The roller stores each unique's specials on a
zero-mod display Affix whose id is ``<unique_id>_special`` (game.uniques._build).
This module is the ONE place that turns those ids back into live engine effects,
so the effect survives save/load (the affix id is serialised) without minting a
single new raw stat key.

Two kinds of effect:

  * STAT specials fold into the existing damage pipeline as ordinary StatMods on
    live Stats fields (boss_damage -> boss_damage_inc, kael_tax -> xp_gain_inc).
    game.core.Hero.recalc adds these to `mods` BEFORE apply_mods, so they obey
    the immutable damage formula like any other mod.

  * FLAG specials become boolean build flags in hero.flags, each read at its own
    call site (combat / gamble / loot). The flag string IS the special_id, so
    gamble keystones (double_pity, gamble_cost_up) flow straight through
    ui.gamble_panel._keystones(), which already forwards hero.flags.

Numeric constants that a call site needs (low-life fire %, phys->fire %,
knockback, stagger, rare-mod-steal) live here too, so balance lives in one file.
"""
from __future__ import annotations

try:
    from game.core import StatMod
    from game.uniques import UNIQUES
except ImportError:  # direct script run: python game/unique_specials.py
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from game.core import StatMod
    from game.uniques import UNIQUES

# --- tunables (single source; call sites import these) ---
BOSS_DAMAGE_PCT = 25.0          # grommkars_answer: +% damage vs bosses
KAEL_TAX_PCT = -10.0            # the_emperors_ledger: xp_gain_inc delta

LOW_LIFE_THRESHOLD = 0.35       # heartstone: "Low Life" = hp/max below this
LOW_LIFE_FIRE_PCT = 30.0        # ...grants +30% Fire Damage while Low Life

PHYS_TO_FIRE_PCT = 30.0         # the_smiths_regret: 30% of phys dealt as fire

KNOCKBACK_CHANCE = 0.15         # galewind: 15% chance on hit
KNOCKBACK_DIST = 36.0           # px shoved away from the hero

STAGGER_PCT = 0.10              # ashfall_mantle: 10% of a hit becomes...
STAGGER_DURATION = 2.0          # ...burning to the hero over 2s (delayed)

DOUBLE_PITY_STEP = 2            # gamblers_paradox: pity +2 instead of +1
GAMBLE_COST_MULT = 1.25         # the_unbought_victory: gamble costs +25%
UNIQUE_DROP_MULT = 0.5          # gamblers_paradox: monster unique weight x0.5

STEAL_MAX = 3                   # covenant_of_the_hunt: up to 3 stolen affixes...
STEAL_DURATION = 20.0           # ...each lasting 20s
STEAL_LIFE_FRAC = 0.05          # "steal vitality": +5% of the rare's max hp as flat life
STEAL_DMG_FRAC = 0.30           # "steal its bite": +30% of the rare's hit as added dmg
STEAL_ARMOR_FRAC = 0.50         # "steal its hide": +50% of the rare's armour as flat armour


def steal_mod_from(mob, rng):
    """Pick ONE StatMod to steal from a slain Rare monster (covenant_of_the_hunt).

    Mobs carry no item affixes, so the "stolen affix" is derived from the rare's
    own power: a slice of its vitality, its hit (as its own damage type), its
    attack speed, or its armour. Balance lives here (single source). Returns a
    plain StatMod; the caller owns its 20s expiry. rng makes the pick, so a fixed
    seed is reproducible in the sim/harness.
    """
    from game.core import DamageType
    s = mob.stats
    hp = getattr(mob, "max_hp", 0.0) or s.life
    avg_hit = (s.damage_min + s.damage_max) / 2.0
    dmg_key = {
        DamageType.FIRE: "added_fire", DamageType.COLD: "added_cold",
        DamageType.LIGHTNING: "added_lightning", DamageType.CHAOS: "added_chaos",
    }.get(getattr(mob, "damage_type", DamageType.PHYS), "damage_max")

    pool: list[StatMod] = []
    if hp > 0:
        pool.append(StatMod("life", flat=round(hp * STEAL_LIFE_FRAC)))
    if avg_hit > 0:
        pool.append(StatMod(dmg_key, flat=round(avg_hit * STEAL_DMG_FRAC)))
    if s.attack_speed > 0:
        pool.append(StatMod("attack_speed", inc=10.0))
    if s.armor > 0:
        pool.append(StatMod("armor", flat=round(s.armor * STEAL_ARMOR_FRAC)))
    if not pool:  # a statless rare (shouldn't happen) still yields something
        pool.append(StatMod("attack_speed", inc=10.0))
    return pool[rng.randrange(len(pool))]

# --- stat specials: special_id -> StatMod folded into recalc ---
_SPECIAL_MODS: dict[str, StatMod] = {
    "boss_damage": StatMod("boss_damage_inc", flat=BOSS_DAMAGE_PCT),
    "kael_tax": StatMod("xp_gain_inc", flat=KAEL_TAX_PCT),
}

# --- flag specials: special_id becomes a boolean build flag in hero.flags ---
_SPECIAL_FLAGS: frozenset[str] = frozenset({
    "low_life_fire", "phys_to_fire", "knockback", "stagger",
    "corrosion_immune", "double_pity", "gamble_cost_up",
    "unique_drop_penalty", "rare_mod_steal",
})

# special-affix id (<unique_id>_special) -> the special ids it grants
_BY_AFFIX_ID: dict[str, tuple[str, ...]] = {
    u.id + "_special": tuple(sid for sid, _ in u.special)
    for u in UNIQUES if u.special
}


def active_special_ids(hero) -> set[str]:
    """Special ids granted by every unique the hero currently has equipped."""
    ids: set[str] = set()
    for it in getattr(hero, "equipment", {}).values():
        if not it:
            continue
        for aff in it.affixes:
            extra = _BY_AFFIX_ID.get(aff.id)
            if extra:
                ids.update(extra)
    return ids


def mods_for(special_ids) -> list[StatMod]:
    """StatMods contributed by the given special ids (stat specials only)."""
    return [_SPECIAL_MODS[sid] for sid in special_ids if sid in _SPECIAL_MODS]


def flags_for(special_ids) -> set[str]:
    """Build flags contributed by the given special ids (flag specials only)."""
    return {sid for sid in special_ids if sid in _SPECIAL_FLAGS}


if __name__ == "__main__":
    # every declared special is wired as either a stat mod or a flag (no orphans)
    declared = {sid for u in UNIQUES for sid, _ in u.special}
    wired = set(_SPECIAL_MODS) | set(_SPECIAL_FLAGS)
    # drop_only is a roller-side tag (handled in roll_unique), not a hero effect
    orphans = declared - wired - {"drop_only", "life_leech"}
    assert not orphans, f"unwired unique specials: {orphans}"
    ids = flags_for(declared) | {m.stat for m in mods_for(declared)}
    assert "boss_damage_inc" in ids and "knockback" in ids
    print(f"unique_specials OK: {len(_SPECIAL_MODS)} stat, "
          f"{len(_SPECIAL_FLAGS)} flag, {len(_BY_AFFIX_ID)} carriers")
