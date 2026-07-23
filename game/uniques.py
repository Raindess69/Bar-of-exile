"""Unique items: fixed mod sets with small random rolls, PoE/D2 style."""
from __future__ import annotations

import random
from dataclasses import dataclass

from game import statmap
from game.core import Affix, Item, Rarity, Slot, StatMod

from game.items import BASES, ItemBase, make_base_item


@dataclass(frozen=True)
class UniqueDef:
    id: str
    name: str
    base_id: str
    ilvl_req: int
    # (stats "a|b" — one roll shared by all, lo, hi, "flat"|"inc")
    mods: tuple[tuple[str, float, float, str], ...]
    flavor: str
    # (special_id, display text) — engine hooks land in step 2b.5; text-only for now
    special: tuple[tuple[str, str], ...] = ()


# unique-only weapon bases missing from game.items (never drop as normal loot)
_EXTRA_BASES: dict[str, ItemBase] = {}


UNIQUES: tuple[UniqueDef, ...] = (
    # --- weapons, one per class ---
    UniqueDef("the_goblins_grudge", "The Goblin's Grudge", "rusted_sword", 1, (
        ("damage_min|damage_max", 40, 60, "inc"),
        ("added_fire", 2, 4, "flat"),
        ("crit_chance", 15, 25, "inc"),
    ), "No grudge is too small to kill for."),
    UniqueDef("kinslayer", "Kinslayer", "broad_axe", 12, (
        ("damage_min|damage_max", 60, 80, "inc"),
        ("crit_multi", 25, 35, "flat"),
        ("attack_speed", 8, 12, "inc"),
    ), "Blood shared is blood owed."),
    UniqueDef("whisperwind", "Whisperwind", "hunter_bow", 12, (
        ("damage_min|damage_max", 25, 40, "inc"),
        ("attack_speed", 18, 25, "inc"),
        ("evasion", 30, 50, "flat"),
        ("move_speed", 8, 12, "inc"),
    ), "The last sound is no sound at all."),
    UniqueDef("stormherald", "Stormherald", "runic_staff", 14, (
        ("added_lightning", 15, 25, "flat"),
        # was mana inc (stat removed) -> caster staff identity: global %-damage
        # (statmap damage_inc_pct -> live Stats.damage_inc). Same 20-30 magnitude.
        ("damage_inc_pct", 20, 30, "flat"),
        ("crit_chance", 20, 30, "inc"),
    ), "It does not predict the storm. It brings it."),
    UniqueDef("the_penitents_toll", "The Penitent's Toll", "war_mace", 12, (
        ("added_fire", 10, 16, "flat"),
        ("life_regen", 2.0, 3.5, "flat"),
        ("life", 20, 35, "flat"),
    ), "Every sin weighs exactly one swing."),
    # --- armour ---
    UniqueDef("wolfpelt_hood", "Wolfpelt Hood", "leather_cap", 2, (
        ("evasion", 25, 40, "inc"),
        ("life", 10, 20, "flat"),
        ("res_cold", 10, 15, "flat"),
    ), "The wolf never minded the cold."),
    UniqueDef("crown_of_sorrows", "Crown of Sorrows", "great_helm", 26, (
        ("armor", 40, 60, "inc"),
        ("life", 40, 60, "flat"),
        ("res_chaos", 15, 20, "flat"),
    ), "Heavy is the head that outlived its kingdom."),
    UniqueDef("beggars_dignity", "Beggar's Dignity", "leather_vest", 3, (
        ("life", 20, 30, "flat"),
        ("res_fire|res_cold|res_lightning", 10, 15, "flat"),
    ), "Rags remember what silk forgets."),
    UniqueDef("the_iron_husk", "The Iron Husk", "plate_mail", 26, (
        ("armor", 80, 100, "inc"),
        ("life", 50, 70, "flat"),
        ("life_regen", 2.0, 3.0, "flat"),
    ), "Nothing gets in. Nothing gets out."),
    UniqueDef("grip_of_the_drowned", "Grip of the Drowned", "chain_gloves", 13, (
        ("attack_speed", 8, 12, "inc"),
        ("res_cold", 15, 25, "flat"),
        ("evasion", 20, 35, "flat"),
    ), "Cold hands hold hardest."),
    UniqueDef("wanderers_last_steps", "Wanderer's Last Steps", "leather_boots", 5, (
        ("move_speed", 20, 25, "inc"),
        ("evasion", 15, 25, "flat"),
        ("life_regen", 0.5, 1.5, "flat"),
    ), "He never stopped walking. Only breathing."),
    # --- jewellery and belt ---
    UniqueDef("the_leech_lords_band", "The Leech Lord's Band", "coral_ring", 8, (
        ("life", 25, 40, "flat"),
        ("life_regen", 1.0, 2.0, "flat"),
    ), "It gives back only what it drinks."),
    UniqueDef("eye_of_the_storm", "Eye of the Storm", "azure_ring", 15, (
        ("added_lightning", 8, 14, "flat"),
        ("res_lightning", 20, 30, "flat"),
        # was mana flat (stat removed) -> life on a caster ring, same defensive
        # role; 25-40 matches the leech lord's band ring tier.
        ("life", 25, 40, "flat"),
    ), "Calm is just lightning waiting."),
    UniqueDef("the_hangmans_knot", "The Hangman's Knot", "bone_amulet", 5, (
        ("damage_min|damage_max", 10, 20, "inc"),
        ("res_chaos", 8, 12, "flat"),
    ), "Tied once, tight forever."),
    UniqueDef("heart_of_the_ancients", "Heart of the Ancients", "onyx_amulet", 26, (
        ("crit_multi", 25, 35, "flat"),
        ("crit_chance", 20, 30, "inc"),
        ("life", 25, 40, "flat"),
    ), "Old hearts beat slow and hit hard."),
    UniqueDef("girdle_of_giants", "Girdle of Giants", "heavy_belt", 26, (
        ("life", 50, 70, "flat"),
        ("armor", 40, 60, "flat"),
        ("damage_min|damage_max", 15, 25, "inc"),
    ), "Cut for a waist no man was born with."),
    # --- opus pack (uniques_new.json): raw v2 keys are display-only until 2b.5 ---
    UniqueDef("covenant_of_the_hunt", "Covenant of the Hunt", "hunter_bow", 30, (  # Hunting Bow
        ("damage_min|damage_max", 40, 60, "inc"),
        ("attack_speed", 10, 15, "inc"),
    ), "The pact is simple: what the prey carried, the hunter keeps.", (
        ("rare_mod_steal", "Killing a Rare monster grants one of its affixes for 20s (max 3 stolen affixes)"),
    )),
    UniqueDef("sovereigns_seal", "Sovereign's Seal", "azure_ring", 25, (  # Gold Ring
        # was all_skill_ranks_flat +1 (DEAD, no skill-rank mechanic) -> live global
        # %-damage (statmap damage_inc_pct -> Stats.damage_inc); +1 rank ~ a big
        # power spike, 25-30 matches an endgame ring.
        ("damage_inc_pct", 25, 30, "flat"),
        # was mana inc (stat removed) -> gold find (statmap gold_find_inc_pct ->
        # Stats.gold_find); fits the mint/coin flavour of a Gold Ring.
        ("gold_find_inc_pct", 20, 25, "flat"),
    ), "Kael mints no coin it cannot reclaim. This ring was never minted."),
    UniqueDef("galewind", "Galewind", "imperial_bow", 45, (  # Longbow
        # was projectile_damage_inc_pct (DEAD, not in statmap) -> live attack
        # damage identity; same 50-70 magnitude keeps the bow's power.
        ("damage_min|damage_max", 50, 70, "inc"),
        ("attack_speed", 8, 12, "inc"),
        ("move_speed", 10, 10, "inc"),
    ), "The storm asked for nothing back.", (
        ("knockback", "15% chance to knock enemies back on hit"),
    )),
    UniqueDef("gamblers_paradox", "Gambler's Paradox", "jade_amulet", 35, (
        # was gamble_cost_red_pct (DEAD, no gamble-cost mechanic) -> live gold find
        # (statmap gold_find_inc_pct -> Stats.gold_find); fits the gambler flavour.
        ("gold_find_inc_pct", 25, 30, "flat"),
        ("item_rarity_inc_pct", 15, 20, "flat"),
    ), "Ferek swears he lost this amulet in a fair game. Ferek has never played a fair game.", (
        ("double_pity", "Gamble pity increases by 2 per roll instead of 1"),
        ("unique_drop_penalty", "Unique drop rate from monsters -50%"),
    )),
    UniqueDef("heartstone_of_the_firstborn", "Heartstone of the Firstborn", "onyx_amulet", 55, (
        ("life", 70, 90, "flat"),
        ("life_regen", 4, 6, "flat"),
        ("res_chaos", 15, 20, "flat"),
    ), "Vharos carved eight hearts before one kept beating.", (
        ("low_life_fire", "While on Low Life (<35%): +30% Fire Damage"),
    )),
    UniqueDef("grommkars_answer", "Gromm'kar's Answer", "vaal_axe", 40, (  # Great Axe
        ("damage_min|damage_max", 90, 110, "inc"),
        ("attack_speed", -10, -10, "inc"),
        # was stun_chance_pct (DEAD: stun is an ailment applied by skills, never
        # read as a Stats key) -> live global %-damage (statmap damage_inc_pct ->
        # Stats.damage_inc); a heavy-hitter identity, same 15-20 magnitude.
        ("damage_inc_pct", 15, 20, "flat"),
    ), "They asked the Warlord to surrender. This was his answer.", (
        ("boss_damage", "+25% damage during boss fights"),
    )),
    UniqueDef("the_quarantine_rolls", "The Quarantine Rolls", "heavy_belt", 30, (
        ("life", 35, 45, "flat"),
        ("res_chaos", 25, 30, "flat"),
    ), "The eighth batch was sealed, signed, and sunk. The ninth learned to read.", (
        ("corrosion_immune", "Immune to corrosion (Mother of Slimes and slime-type debuffs)"),
    )),
    UniqueDef("the_emperors_ledger", "The Emperor's Ledger", "plate_mail", 50, (  # Tower Shield (no shield slot)
        ("gold_find_inc_pct", 40, 50, "flat"),
        # was sell_price_inc_pct (DEAD, no sell-price mechanic) -> live item rarity
        # (statmap item_rarity_inc_pct -> Stats.item_rarity); keeps the economy
        # identity of a ledger.
        ("item_rarity_inc_pct", 15, 20, "flat"),
        # was block_chance_pct (DEAD, no block slot/mechanic) -> live life; body
        # armour defensive role, 40-60 matches a level-50 plate.
        ("life", 40, 60, "flat"),
    ), "Every exile is an entry. Every entry is owed.", (
        ("kael_tax", "-10% XP gained (the Empire always collects)"),
    )),
    UniqueDef("ashfall_mantle", "Ashfall Mantle", "plate_mail", 52, (  # Plate Armor
        ("armor", 100, 130, "inc"),
        ("res_fire", 35, 40, "flat"),
    ), "What the Lord of Ash burns, it also keeps warm.", (
        ("stagger", "10% of damage taken is dealt as Burning to you over 2s instead of instantly"),
    )),
    UniqueDef("flesh_forge_prototype", "Flesh-Forge Prototype", "chain_gloves", 38, (
        ("life", 25, 35, "flat"),
        ("attack_speed", 6, 8, "inc"),
        ("life_on_kill_flat", 8, 12, "flat"),
        # headline "Leech 2%" now numeric: life_leech_pct routes via statmap to
        # the live Stats.life_leech field (read combat.py:280).
        ("life_leech_pct", 2, 2, "flat"),
    ), "The Mother's early work. It still remembers being hungry.", (
        ("life_leech", "Leech 2% of damage as Life"),
    )),
    UniqueDef("the_smiths_regret", "The Smith's Regret", "war_mace", 48, (  # War Hammer
        ("damage_min|damage_max", 50, 70, "inc"),
        ("crit_chance", -20, -20, "inc"),
    ), "Vharos never unmade a single work. That is the regret.", (
        ("phys_to_fire", "30% of Physical Damage converted to Fire"),
    )),
    UniqueDef("wardens_quiet_fletch", "Warden's Quiet Fletch", "studded_belt", 33, (  # Quiver (no offhand slot)
        # was projectile_damage_inc_pct (DEAD) -> live attack damage identity,
        # same 20-25 magnitude preserves the item's power.
        ("damage_min|damage_max", 20, 25, "inc"),
        ("crit_chance", 12, 15, "inc"),
        ("evasion", 8, 10, "inc"),
    ), "Stolen herds, silent arrows. The Emperor never heard a thing."),
    UniqueDef("the_unbought_victory", "The Unbought Victory", "leather_boots", 44, (
        ("move_speed", 18, 20, "inc"),
        ("evasion", 25, 30, "inc"),
    ), "Won by winning. The duel was rigged; the run home was not.", (
        ("gamble_cost_up", "Gamble costs +25% Gold"),
        ("drop_only", "Cannot be obtained from gambling - drop only"),
    )),
)


def _make_base(base_id: str, ilvl: int) -> Item:
    if base_id in BASES:
        return make_base_item(base_id, ilvl)
    b = _EXTRA_BASES[base_id]
    implicit = [
        StatMod("damage_min", flat=b.damage_min),
        StatMod("damage_max", flat=b.damage_max),
        StatMod("attack_speed", flat=b.attack_speed - 1.0),
    ]
    return Item(base_id=b.id, base_name=b.name, slot=b.slot, rarity=Rarity.NORMAL,
                ilvl=ilvl, req_level=b.req_level, implicit=implicit)


def _roll_mods(u: UniqueDef, rng: random.Random) -> list[StatMod]:
    mods: list[StatMod] = []
    for stats, lo, hi, kind in u.mods:
        if float(lo).is_integer() and float(hi).is_integer():
            val: float = rng.randint(int(lo), int(hi))
        else:
            val = round(rng.uniform(lo, hi), 1)
        for stat in stats.split("|"):
            if statmap.has_engine_support(stat):
                # v2 keys with a real hook (item_rarity/gold_find/life_on_kill):
                # route through statmap so apply_mods sees a live Stats field.
                # statmap picks its own flat/inc bucket, ignoring `kind`.
                mods.extend(statmap.mods_for(stat, val))
            else:
                # direct engine fields (life, damage_min, ...) keep their kind.
                # LOOT-M1/M3: all previously-dead raw keys (mana, projectile_
                # damage_inc_pct, stun_chance_pct, block_chance_pct,
                # all_skill_ranks_flat, gamble_cost_red_pct, sell_price_inc_pct)
                # have been rerolled onto live keys; any future unknown field
                # still stays inert here — apply_mods skips it, no crash.
                mods.append(StatMod(stat, flat=val) if kind == "flat" else StatMod(stat, inc=val))
    return mods


def _build(u: UniqueDef, ilvl: int, rng: random.Random) -> Item:
    item = _make_base(u.base_id, ilvl)
    item.rarity = Rarity.UNIQUE
    item.name = u.name
    item.req_level = max(item.req_level, u.ilvl_req)
    item.affixes = [Affix(id=u.id, name=u.name, is_prefix=True, tier=0,
                          mods=_roll_mods(u, rng))]
    if u.special:
        # display-only until 2b.5 wires the hooks; tooltip renders Affix.lines
        item.affixes.append(Affix(id=u.id + "_special", name=u.name, is_prefix=False,
                                  tier=0, mods=[], lines=[t for _, t in u.special]))
    return item


def roll_unique(ilvl: int, rng: random.Random, exclude_drop_only: bool = False) -> Item | None:
    pool = [u for u in UNIQUES if u.ilvl_req <= ilvl]
    if exclude_drop_only:
        # drop-only uniques (special id "drop_only") must not appear from gambling
        pool = [u for u in pool if not any(sid == "drop_only" for sid, _ in u.special)]
    if not pool:
        return None
    return _build(rng.choice(pool), ilvl, rng)


if __name__ == "__main__":
    assert len(UNIQUES) == 29, len(UNIQUES)
    flavors = {u.id: u.flavor for u in UNIQUES}
    for u in UNIQUES:
        _make_base(u.base_id, u.ilvl_req)
    rng = random.Random(99)
    for i in range(10):
        ilvl = 1 + i * 4
        it = roll_unique(ilvl, rng)
        assert it is not None and it.rarity is Rarity.UNIQUE and it.affixes
        u = next(x for x in UNIQUES if x.id == it.affixes[0].id)
        assert u.ilvl_req <= ilvl
        print(f"ilvl {ilvl:2d}: {it.display_name()} [{it.base_name}, {it.slot.value}, req {it.req_level}]")
        for m in it.affixes[0].mods:
            print("   " + m.describe())
        print(f'   "{flavors[it.affixes[0].id]}"')
    # every def rolls into an item with display mods; special text rides Affix.lines
    for u in UNIQUES:
        it = _build(u, u.ilvl_req, rng)
        assert it.rarity is Rarity.UNIQUE and it.affixes[0].mods, u.id
        assert all(m.describe() for m in it.affixes[0].mods), u.id
        if u.special:
            spec = it.affixes[-1]
            assert spec.mods == [] and spec.lines == [t for _, t in u.special], u.id
    slots = {BASES[u.base_id].slot if u.base_id in BASES else _EXTRA_BASES[u.base_id].slot
             for u in UNIQUES}
    assert slots == set(Slot), slots
    # class-bound bases pass class_req through to uniques
    kin = next(u for u in UNIQUES if u.id == "kinslayer")
    kin_item = _make_base(kin.base_id, kin.ilvl_req)
    assert kin_item.class_req == ("barbarian",), kin_item.class_req
    print(f"\nuniques OK: {len(UNIQUES)} defs, all slots covered")
