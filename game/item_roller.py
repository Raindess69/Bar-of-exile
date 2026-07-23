"""Itemization v2: ItemRoller — data-driven drops from data/affixes_v2.json.

Pipeline per ITEMS_TREE_V2.md 1.2: base -> rarity (magic find shifts weight out
of normal) -> affix counts -> weighted pick with tier bias -> value roll ->
naming. Deterministic: same rng state -> same items. The old game.affixes
module stays in place for legacy imports; new drops route through here.
"""
from __future__ import annotations

import json
import os
import random

from game import statmap
from game.affixes import RARE_FIRST, RARE_SECOND
from game.core import (Affix, Item, Rarity, RARITY_RANK, Slot, StatMod,
                       MOD_RELIC, MOD_PRIMAL)
from game.greater_affix import star_mark, star_mult, star_roll
from game.items import random_base
from game.uniques import roll_unique

_DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "data", "affixes_v2.json")

# data says "chest" for the body slot; "shield" has no engine slot (never matches)
_SLOT_ALIAS = {"chest": Slot.BODY.value}

# spec 1.2 step 3 (before magic find); weights are relative shares fed to
# rng.choices, so they need not sum to 100. Stage 6.2 loot pass: NORMAL/MAGIC/
# RARE retuned 55/30/12 -> 100/55/8 so RARE ≈ 4.9% of drops (yellow = event).
# LE-4: ground unique weight kept at 3.0 -> 0.4 so ground drops stop
# undercutting Ferek's gamble pity (0.6%/roll).
# 10-tier ladder drop weights (spec base_weight column). SCRAP is the new low-end
# fodder; EXALTED sits between rare and unique. SET and MYTHIC are injected by the
# loot layer (game.sets / game.mythics), not the base weighted pick here, so they
# are absent from this table. RELIC/PRIMAL are post-roll overlays on unique/mythic.
RARITY_WEIGHTS: dict[Rarity, float] = {
    Rarity.SCRAP: 220.0, Rarity.NORMAL: 100.0, Rarity.MAGIC: 55.0,
    Rarity.RARE: 8.0, Rarity.EXALTED: 1.5, Rarity.UNIQUE: 0.4,
}
# boss drops keep the old, pre-nerf unique weight (loot.roll_boss_drops passes
# it as unique_weight override) so boss unique rates are unchanged by LE-4
BOSS_UNIQUE_WEIGHT = 3.0
# spec relic/primal roll: post-roll upgrade chance on a UNIQUE (relic) or a
# unique/mythic past ilvl 75 (primal). Applied by _apply_modifier at roll time.
RELIC_ROLL_CHANCE = 0.04
PRIMAL_ROLL_CHANCE = 0.006
PRIMAL_MIN_ILVL = 75
EXALTED_MIN_ILVL = 30
_RANK = dict(RARITY_RANK)  # single source of truth: core.RARITY_RANK

SMART_LOOT_CHANCE = 0.25   # spec 1.2 step 8: 25% of drops are class-biased
SMART_AFFIX_MULT = 1.5     # +50% weight for affixes the class "wants"

# Smart-loot favourites: v2 stat keys per class (+50% affix weight on the 25%
# of drops that are class-biased). Hand-picked from the affixes_v2.json pool.
# block_chance_pct is deliberately absent: it only rolls on "shield" slots,
# which the game does not have.
CLASS_STATS: dict[str, frozenset[str]] = {
    # sword-and-board bruiser: phys damage, armour, life
    "warrior": frozenset({
        "physical_damage_inc_pct", "damage_flat_physical", "armor_flat",
        "armor_inc_pct", "life_flat", "life_inc_pct", "all_res_flat_pct",
    }),
    # two-handed berserker: raw damage, speed, leech/on-kill sustain
    "barbarian": frozenset({
        "physical_damage_inc_pct", "damage_flat_physical", "attack_speed_inc_pct",
        "crit_multi_flat", "life_flat", "life_leech_pct", "life_on_kill_flat",
    }),
    # bow crit: speed, crit, evasion (v3 dropped projectile damage)
    "archer": frozenset({
        "damage_inc_pct", "attack_speed_inc_pct", "crit_chance_inc_pct",
        "crit_multi_flat", "evasion_flat", "evasion_inc_pct", "move_speed_inc_pct",
    }),
    # elementalist: elemental damage, cast speed, life
    "mage": frozenset({
        "elemental_damage_inc_pct", "fire_damage_inc_pct", "cold_damage_inc_pct",
        "lightning_damage_inc_pct", "cast_speed_inc_pct", "life_flat", "life_inc_pct",
    }),
    # holy support-fighter: healing/regen, life, holy fire, defences
    "cleric": frozenset({
        "healing_inc_pct", "life_regen_flat", "life_flat", "fire_damage_inc_pct",
        "armor_flat", "all_res_flat_pct", "life_inc_pct",
    }),
}


def _load_pool() -> tuple[list[dict], dict[str, list[dict]], dict[str, str]]:
    with open(_DATA_PATH, encoding="utf-8") as f:
        raw = json.load(f)["affixes"]
    pool: list[dict] = []
    by_slot: dict[str, list[dict]] = {}
    family_of: dict[str, str] = {}
    for src in raw:
        a = dict(src)
        a["_tier"] = int(a["tier"][1:])  # "T5" -> 5 (engine convention: 1 best)
        a["_slots"] = frozenset(_SLOT_ALIAS.get(s, s) for s in a["slots"])
        pool.append(a)
        family_of[a["id"]] = a["family"]
        for s in a["_slots"]:
            by_slot.setdefault(s, []).append(a)
    return pool, by_slot, family_of


POOL, _BY_SLOT, _FAMILY_OF = _load_pool()


def _tier_bias(tier: int, ilvl: int) -> float:
    """spec 1.2 step 5: at high ilvl push down the worst tiers (D2 feel kept)."""
    if ilvl >= 60:
        if tier == 5:
            return 0.35
        if tier == 4:
            return 0.6
    elif ilvl >= 45:
        if tier == 5:
            return 0.6
    return 1.0


def _make_affix(a: dict, rng: random.Random) -> Affix:
    """Roll value(s), build engine mods via statmap, pre-render the display line.

    E.5: after the base value roll, star_roll() may grant 1-4 ★ (rng-only, never
    magic-find-scaled). A star multiplies the rolled magnitude past roll_max
    (breaks the tier cap) and marks the line with ★.
    """
    stat = a["stat"]
    if statmap.is_pair_stat(stat):
        x = rng.randint(a["roll_min"], a["roll_max"])
        y = rng.randint(a["roll_min"], a["roll_max"])
        lo, hi = min(x, y), max(x, y)
        stars = star_roll(rng)
        if stars:
            mult = star_mult(stars)
            lo, hi = max(1, round(lo * mult)), max(1, round(hi * mult))
        mods = statmap.mods_for_pair(stat, lo, hi)
        line = a["display"].replace("{lo}", str(lo)).replace("{hi}", str(hi))
    else:
        v = rng.randint(a["roll_min"], a["roll_max"])
        stars = star_roll(rng)
        if stars:
            v = max(1, round(v * star_mult(stars)))
        mods = statmap.mods_for(stat, v)
        line = a["display"].replace("{v}", str(v))
    return Affix(id=a["id"], name=a["name"], is_prefix=a["type"] == "prefix",
                 tier=a["_tier"], mods=mods, lines=[star_mark(stars) + line],
                 stars=stars)


def _roll_affix_set(item: Item, rng: random.Random,
                    class_id: str | None = None) -> None:
    """Fill item.affixes + item.name for the item's CURRENT rarity (v2 pool)."""
    item.affixes = []
    if item.rarity not in (Rarity.MAGIC, Rarity.RARE, Rarity.EXALTED):
        # mirror the old game.affixes.roll_affixes contract for scrap/normal/unique
        item.name = item.base_name
        return
    tier_floor = 0
    if item.rarity is Rarity.MAGIC:
        count = 1 if rng.random() < 0.40 else 2   # spec: 40% one / 60% two
        max_p = max_s = 1
    elif item.rarity is Rarity.EXALTED:
        # spec tier 5: 4-6 affixes, affix_tier_floor=3 (never rolls T4/T5 junk)
        r = rng.random()
        count = 4 if r < 0.45 else (5 if r < 0.80 else 6)
        max_p = max_s = 3
        tier_floor = 3
    else:
        r = rng.random()
        # spec E.4: Rare 3-6 affixes, weights 40/35/18/7
        count = 3 if r < 0.40 else (4 if r < 0.75 else (5 if r < 0.93 else 6))
        max_p = max_s = 3
    fav = CLASS_STATS.get(class_id or "", frozenset())
    slot_pool = _BY_SLOT.get(item.slot.value, [])
    used_families: set[str] = set()
    n_pre = n_suf = 0
    for _ in range(count):
        cands: list[dict] = []
        weights: list[float] = []
        for a in slot_pool:
            if item.ilvl < a["ilvl_req"] or a["family"] in used_families:
                continue
            if tier_floor and a["_tier"] > tier_floor:
                continue  # exalted: skip low tiers (engine convention: 1 = best)
            if (n_pre >= max_p) if a["type"] == "prefix" else (n_suf >= max_s):
                continue
            w = a["weight"] * _tier_bias(a["_tier"], item.ilvl)
            if a["stat"] in fav:
                w *= SMART_AFFIX_MULT
            cands.append(a)
            weights.append(w)
        if not cands:
            break
        pick = rng.choices(cands, weights=weights, k=1)[0]
        used_families.add(pick["family"])
        if pick["type"] == "prefix":
            n_pre += 1
        else:
            n_suf += 1
        item.affixes.append(_make_affix(pick, rng))
    # spec 1.3: stable display order by (type, family) — prefixes first
    item.affixes.sort(key=lambda a: (not a.is_prefix, _FAMILY_OF.get(a.id, a.id)))
    if item.rarity is Rarity.MAGIC:
        pre = next((a for a in item.affixes if a.is_prefix), None)
        suf = next((a for a in item.affixes if not a.is_prefix), None)
        parts = ([pre.name] if pre else []) + [item.base_name] + ([suf.name] if suf else [])
        item.name = " ".join(parts)
    else:
        item.name = f"{rng.choice(RARE_FIRST)} {rng.choice(RARE_SECOND)}"


# EXALTED implicit pool (spec tier 5 "+1 implicit"): one flat defensive/life mod
# picked by slot so the bonus always fits the piece. Rolls are fixed magnitudes —
# the exalted "premium" is the tier-floor on its affixes, not a random implicit.
_EXALTED_IMPLICIT = {
    Slot.WEAPON: StatMod("crit_multi", flat=15),
    Slot.HELMET: StatMod("life", flat=25),
    Slot.BODY: StatMod("life", flat=40),
    Slot.GLOVES: StatMod("attack_speed", flat=0.05),
    Slot.BOOTS: StatMod("move_speed", inc=8),
    Slot.BELT: StatMod("life", flat=30),
    Slot.AMULET: StatMod("crit_multi", flat=12),
    Slot.RING: StatMod("life", flat=18),
}
# spec tier 1: scrap items carry x0.7 stat penalty on their (rolled) mods. Scrap
# has no affixes, so the penalty bites the base implicit — the reason it is salvage
# fodder, not gear.
SCRAP_STAT_MULT = 0.7


def _apply_exalted_implicit(item: Item, rng: random.Random) -> None:
    extra = _EXALTED_IMPLICIT.get(item.slot)
    if extra is not None:
        item.implicit = list(item.implicit) + [
            StatMod(extra.stat, flat=extra.flat, inc=extra.inc)]


def _apply_scrap(item: Item) -> None:
    item.implicit = [StatMod(m.stat, flat=m.flat * SCRAP_STAT_MULT,
                             inc=m.inc * SCRAP_STAT_MULT,
                             more=m.more * SCRAP_STAT_MULT) for m in item.implicit]


# --- tier 8 & 10 overlays (RELIC / PRIMAL): modifiers on a unique/mythic base ---
# Relic (foil unique): every mod magnitude x[1.15,1.30] + one extra rare-tier
# affix. Primal (perfect roll): every mod magnitude at the primal ceiling and each
# line forced to >= 3 stars. Both set Item.modifier so render/serialization know to
# draw the foil / rainbow frame; neither changes Item.rarity (spec: overlays, not
# lut rows).
RELIC_ROLL_LO = 1.15
RELIC_ROLL_HI = 1.30
PRIMAL_MULT = 1.40          # spec tier 10 "all rolls max" premium over base
PRIMAL_STAR_FLOOR = 3


def _scale_mod(m: StatMod, mult: float) -> StatMod:
    return StatMod(m.stat, flat=m.flat * mult, inc=m.inc * mult, more=m.more * mult)


def _scale_affix(a: Affix, mult: float, star_floor: int = 0) -> Affix:
    stars = max(a.stars, star_floor) if star_floor else a.stars
    mods = [_scale_mod(m, mult) for m in a.mods]
    # re-render the ★ prefix; the numeric text on unique/mythic lines is baked so
    # leave the body, only refresh the star marker to match the new star count.
    lines = a.lines
    if star_floor and stars != a.stars:
        body = [ln.lstrip("★ ") for ln in a.lines]
        lines = [star_mark(stars) + b for b in body]
    return Affix(id=a.id, name=a.name, is_prefix=a.is_prefix, tier=a.tier,
                 mods=mods, lines=lines, stars=stars)


def apply_relic(item: Item, rng: random.Random) -> Item:
    """Upgrade a UNIQUE into a Relic (tier 8): scale mods, add one rare affix."""
    mult = rng.uniform(RELIC_ROLL_LO, RELIC_ROLL_HI)
    item.affixes = [_scale_affix(a, mult) for a in item.affixes]
    item.implicit = [_scale_mod(m, mult) for m in item.implicit]
    # one extra rolled rare-tier affix from the live pool for this slot
    slot_pool = _BY_SLOT.get(item.slot.value, [])
    used = {_FAMILY_OF.get(a.id, a.id) for a in item.affixes}
    cands = [a for a in slot_pool
             if item.ilvl >= a["ilvl_req"] and a["family"] not in used]
    if cands:
        weights = [a["weight"] * _tier_bias(a["_tier"], item.ilvl) for a in cands]
        pick = rng.choices(cands, weights=weights, k=1)[0]
        item.affixes.append(_make_affix(pick, rng))
    item.modifier = MOD_RELIC
    return item


def apply_primal(item: Item, rng: random.Random) -> Item:
    """Upgrade a UNIQUE/MYTHIC into a Primal (tier 10): max rolls + star floor 3."""
    item.affixes = [_scale_affix(a, PRIMAL_MULT, PRIMAL_STAR_FLOOR)
                    for a in item.affixes]
    item.implicit = [_scale_mod(m, PRIMAL_MULT) for m in item.implicit]
    item.modifier = MOD_PRIMAL
    return item


def maybe_overlay(item: Item, ilvl: int, rng: random.Random) -> Item:
    """Post-roll overlay pass (spec tiers 8 & 10). Primal takes precedence over
    relic when both would fire. PRIMAL: unique or mythic past PRIMAL_MIN_ILVL, tiny
    chance. RELIC: unique only. No-op on every other rarity — safe to call on any
    drop before it reaches the player."""
    if item.rarity is Rarity.MYTHIC:
        if ilvl >= PRIMAL_MIN_ILVL and rng.random() < PRIMAL_ROLL_CHANCE:
            return apply_primal(item, rng)
        return item
    if item.rarity is not Rarity.UNIQUE:
        return item
    if ilvl >= PRIMAL_MIN_ILVL and rng.random() < PRIMAL_ROLL_CHANCE:
        return apply_primal(item, rng)
    if rng.random() < RELIC_ROLL_CHANCE:
        return apply_relic(item, rng)
    return item


def reroll_affixes(item: Item, rng: random.Random,
                   class_id: str | None = None) -> None:
    """Drop-in replacement for game.affixes.roll_affixes (cube reforge, vendor)."""
    _roll_affix_set(item, rng, class_id)


class ItemRoller:
    """v2 drop generator; spec: 'ItemRoller takes rng' — same state, same items."""

    def __init__(self, rng: random.Random):
        self.rng = rng

    def roll(self, ilvl: int, class_id: str | None = None, magic_find: float = 0.0,
             min_rarity: Rarity | None = None,
             unique_weight: float | None = None) -> Item:
        rng = self.rng
        # step 8: 25% of drops are smart (class-biased base AND affixes);
        # the other 75% are fully random — no class bias anywhere.
        smart = class_id is not None and rng.random() < SMART_LOOT_CHANCE
        item = random_base(ilvl, rng, class_id=class_id if smart else None)
        # SCRAP is trash-mob fodder only: any rarity floor (boss/champion lift)
        # means "not trash", so scrap is excluded there. This keeps the calibrated
        # boss/ground unique rates (LE-4 gamble-pity balance) untouched — scrap
        # weight can't steal probability mass from a floored drop.
        rarity = self._roll_rarity(ilvl, magic_find, unique_weight,
                                   allow_scrap=min_rarity is None)
        if rarity is Rarity.UNIQUE:
            uniq = roll_unique(ilvl, rng)
            if uniq is not None:
                return maybe_overlay(uniq, ilvl, rng)
            rarity = Rarity.RARE  # unique_gate: no unique for this ilvl -> rare
        if min_rarity is not None and _RANK[rarity] < _RANK[min_rarity]:
            rarity = min_rarity if min_rarity is not Rarity.UNIQUE else Rarity.RARE
        item.rarity = rarity
        _roll_affix_set(item, rng, class_id if smart else None)
        if rarity is Rarity.SCRAP:
            _apply_scrap(item)
        elif rarity is Rarity.EXALTED:
            _apply_exalted_implicit(item, rng)
        return item

    def _roll_rarity(self, ilvl: int, magic_find: float,
                     unique_weight: float | None = None,
                     allow_scrap: bool = True) -> Rarity:
        # IR multiplies magic/rare/exalted/unique weights; scrap+normal stay ->
        # the high end grows its share as MF climbs. SCRAP is the low-end fodder
        # tier (spec base_weight 220) and only enters the pick on un-floored trash
        # drops; EXALTED sits between RARE and UNIQUE, gated to ilvl >=
        # EXALTED_MIN_ILVL (30) — below the gate its weight is 0 so the pick
        # collapses to the classic distribution.
        ir = magic_find
        uw = RARITY_WEIGHTS[Rarity.UNIQUE] if unique_weight is None else unique_weight
        exw = RARITY_WEIGHTS[Rarity.EXALTED] if ilvl >= EXALTED_MIN_ILVL else 0.0
        tiers = [Rarity.NORMAL, Rarity.MAGIC, Rarity.RARE, Rarity.EXALTED, Rarity.UNIQUE]
        weights = [
            RARITY_WEIGHTS[Rarity.NORMAL],
            RARITY_WEIGHTS[Rarity.MAGIC] * (1 + ir / 100),
            RARITY_WEIGHTS[Rarity.RARE] * (1 + ir / 100),
            exw * (1 + ir / 150),
            uw * (1 + ir / 200),
        ]
        if allow_scrap:
            tiers.insert(0, Rarity.SCRAP)
            weights.insert(0, RARITY_WEIGHTS[Rarity.SCRAP])
        return self.rng.choices(tiers, weights=weights, k=1)[0]


if __name__ == "__main__":
    # pool sanity: pair stats always use {lo}/{hi} templates, others {v}
    for a in POOL:
        assert ("{lo}" in a["display"]) == statmap.is_pair_stat(a["stat"]), a["id"]
        assert a["type"] in ("prefix", "suffix") and 1 <= a["_tier"] <= 5, a["id"]
        assert a["roll_min"] <= a["roll_max"], a["id"]
    pool_stats = {a["stat"] for a in POOL}
    for cls, stats in CLASS_STATS.items():
        assert stats <= pool_stats, (cls, stats - pool_stats)

    rng = random.Random(42)
    roller = ItemRoller(rng)
    for ilvl in (5, 30, 70):
        print(f"=== ilvl {ilvl} ===")
        for _ in range(5):
            it = roller.roll(ilvl, class_id="mage", magic_find=40.0)
            print(f"[{it.rarity.value}] {it.display_name()} "
                  f"({it.base_name}, {it.slot.value}, ilvl {it.ilvl})")
            for a in it.affixes:
                tag = "P" if a.is_prefix else "S"
                line = a.lines[0] if a.lines else "; ".join(m.describe() for m in a.mods)
                print(f"   {tag}T{a.tier} {line}")
            if it.rarity is Rarity.UNIQUE:
                continue
            fams = [_FAMILY_OF[a.id] for a in it.affixes]
            assert len(fams) == len(set(fams)), fams
            for a in it.affixes:
                meta = next(x for x in POOL if x["id"] == a.id)
                assert meta["ilvl_req"] <= ilvl, (a.id, ilvl)
                assert a.lines and "{" not in a.lines[0], a.lines
            if it.rarity is Rarity.MAGIC:
                assert 1 <= len(it.affixes) <= 2
            elif it.rarity is Rarity.RARE:
                assert 4 <= len(it.affixes) <= 6

    # determinism: same seed -> identical sequences
    r1, r2 = ItemRoller(random.Random(7)), ItemRoller(random.Random(7))
    for _ in range(50):
        a1 = r1.roll(33, class_id="archer", magic_find=25.0)
        b1 = r2.roll(33, class_id="archer", magic_find=25.0)
        assert a1.name == b1.name and len(a1.affixes) == len(b1.affixes)
        assert [x.lines for x in a1.affixes] == [x.lines for x in b1.affixes]

    # reroll contract (cube reforge / vendor stock)
    it = roller.roll(40)
    it.rarity = Rarity.RARE
    reroll_affixes(it, rng)
    assert 3 <= len(it.affixes) <= 6 and it.name != it.base_name  # spec E.4: 3-6
    it.rarity = Rarity.NORMAL
    reroll_affixes(it, rng)
    assert it.affixes == [] and it.name == it.base_name
    print(f"\nitem_roller OK: {len(POOL)} affixes in pool")
