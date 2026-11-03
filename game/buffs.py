"""Bar of Exile — SK-H3 buff layer: aura / cast-buff params -> Stats mods.

Auras and buff skills (war_cry, defiance, archmage, avatar_of_war, …) used to
only do ``hero.flags.add(skill.id)`` — but combat reads only KEYSTONE flags, so
every aura and every buff utility/ultimate was purely cosmetic (audit SK-H3).

This module turns a buff skill's ``params`` into real StatMods (and a small set
of build flags). game.skills_v2 collects the active auras + timed buffs each
tick into ``hero.buff_mods`` / ``hero._buff_flags``; core.Hero.recalc folds them
into stats alongside gear and passives. No import of skills_v2/combat here — it
sits at the core+StatMod layer so anything can use it without a cycle.

Param keys understood (all optional, silently ignored if absent):

  buff_dmg_pct / buff_damage_inc / ele_dmg_pct / more_dmg_pct -> damage_inc (add %)
  buff_as_pct        -> attack_speed (inc %)
  armor_pct / buff_armor_inc -> armor (inc %)
  crit_chance_pct    -> crit_chance (flat)
  crit_multi_pct     -> crit_multi (flat)
  lifesteal_pct      -> life_leech (flat)
  evade_pct          -> evasion (inc %)   (audit H1 made evasion live)
  life_regen_pct     -> life_regen (flat, per hero level so it scales)
  dmg_taken_pct / debuff_taken_pct / absorb_pct -> defensive (see notes)
  immune_stun / cannot_die -> build flags (returned separately)

Notes:
  * ``debuff_taken_pct`` (mark_for_death) is a DEBUFF ON ENEMIES, not a self
    buff — it is NOT converted to a self stat here (would be wrong-signed). Left
    for a future enemy-debuff pass; documented so it isn't silently "hooked".
  * ``dmg_taken_pct`` negative (sanctuary -12%) reduces incoming damage; there is
    no single "damage taken" self stat, so it is approximated as extra armor.
"""
from __future__ import annotations

from game.core import StatMod

# param key -> (Stats field, bucket). "inc" = percent-increase bucket, "flat" =
# flat add. Percent-damage buffs all funnel into the additive damage_inc bucket.
_DAMAGE_INC_KEYS = ("buff_dmg_pct", "buff_damage_inc", "ele_dmg_pct", "more_dmg_pct")

# defensive approximation: -X% damage taken ~ +ARMOR_PER_DMG_TAKEN*X armor
_ARMOR_PER_DMG_TAKEN = 8.0


def buff_mods_for(params: dict, hero_level: int = 1) -> list[StatMod]:
    """StatMods a single buff skill's params contribute. Pure; empty if none."""
    mods: list[StatMod] = []
    if not params:
        return mods

    dmg_inc = 0.0
    for k in _DAMAGE_INC_KEYS:
        if k in params:
            dmg_inc += float(params[k])
    if dmg_inc:
        mods.append(StatMod("damage_inc", flat=dmg_inc))

    if "buff_as_pct" in params:
        mods.append(StatMod("attack_speed", inc=float(params["buff_as_pct"])))

    armor_inc = 0.0
    for k in ("armor_pct", "buff_armor_inc"):
        if k in params:
            armor_inc += float(params[k])
    # sanctuary: negative dmg_taken_pct -> approximate as bonus armor
    if params.get("dmg_taken_pct", 0) < 0:
        armor_inc += -float(params["dmg_taken_pct"]) * _ARMOR_PER_DMG_TAKEN
    if params.get("absorb_pct", 0) > 0:
        armor_inc += float(params["absorb_pct"]) * _ARMOR_PER_DMG_TAKEN
    if armor_inc:
        mods.append(StatMod("armor", inc=armor_inc))

    if "crit_chance_pct" in params:
        mods.append(StatMod("crit_chance", flat=float(params["crit_chance_pct"])))
    if "crit_multi_pct" in params:
        mods.append(StatMod("crit_multi", flat=float(params["crit_multi_pct"])))
    if "lifesteal_pct" in params:
        mods.append(StatMod("life_leech", flat=float(params["lifesteal_pct"])))
    if "evade_pct" in params:
        mods.append(StatMod("evasion", inc=float(params["evade_pct"])))
    if "life_regen_pct" in params:
        # % of level as flat regen/sec so it scales with the hero, min level 1
        mods.append(StatMod("life_regen",
                            flat=float(params["life_regen_pct"]) * max(1, hero_level) / 100.0))
    return mods


def buff_flags_for(params: dict) -> set[str]:
    """Build flags a buff skill's params set (immune_stun / cannot_die)."""
    out: set[str] = set()
    if not params:
        return out
    if params.get("immune_stun"):
        out.add("immune_stun")
    if params.get("cannot_die"):
        out.add("cannot_die")
    return out


if __name__ == "__main__":
    # smoke
    m = buff_mods_for({"buff_dmg_pct": 20, "buff_as_pct": 10}, 30)
    assert any(x.stat == "damage_inc" and x.flat == 20 for x in m), m
    assert any(x.stat == "attack_speed" and x.inc == 10 for x in m), m
    m2 = buff_mods_for({"reserve_pct": 25, "armor_pct": 25}, 30)
    assert any(x.stat == "armor" and x.inc == 25 for x in m2), m2
    m3 = buff_mods_for({"crit_chance_pct": 20}, 1)
    assert any(x.stat == "crit_chance" and x.flat == 20 for x in m3), m3
    f = buff_flags_for({"immune_stun": True, "cannot_die": True})
    assert f == {"immune_stun", "cannot_die"}, f
    assert buff_mods_for({"debuff_taken_pct": 25}, 1) == [], "enemy debuff must not self-buff"
    print("buffs OK")
