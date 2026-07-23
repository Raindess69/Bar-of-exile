"""Drops: chance, rarity, gold. Rolling is v2: game.item_roller.ItemRoller."""
from __future__ import annotations

import random

from game.core import Item, Monster, Rarity, Slot

from game.item_roller import (BOSS_UNIQUE_WEIGHT,  # noqa: F401 (re-export)
                              RARITY_WEIGHTS, ItemRoller, maybe_overlay)
from game.sets import roll_set_item
from game.mythics import roll_mythic, MYTHIC_MIN_ILVL

# 10-tier ladder injection (tiers 6 & 9). SET and MYTHIC are NOT part of the
# item_roller weighted pick (that would perturb the calibrated normal..unique
# shares); the loot layer injects them as independent pre-empt rolls after the
# base drop is decided. Chances are per-drop:
#   SET   — spec base_weight 5 vs ~130 total ground weight ≈ 3.8%; min_ilvl 25.
#           A set roll REPLACES a would-be non-unique drop (uniques out-rank it).
#   MYTHIC— boss-source only (act/rift boss), min_ilvl 60; a rare 4% boss roll
#           that supersedes one of the boss's drops.
SET_DROP_CHANCE = 0.038
SET_MIN_ILVL = 25
MYTHIC_DROP_CHANCE = 0.04

# Rarity ladder for lifting a drop's floor by N tiers (6.4 champion bonus). Uses
# the canonical core ladder but only the classic contiguous run scrap..unique is
# meaningful for champion lifts (set/mythic are injected by dedicated modules).
_RARITY_LADDER = [Rarity.NORMAL, Rarity.MAGIC, Rarity.RARE]


def _lift_rarity(base: Rarity | None, tiers: int) -> Rarity | None:
    """Raise a min-rarity floor by `tiers` steps along the ladder (capped at RARE
    so champions can't hand out guaranteed uniques)."""
    if tiers <= 0:
        return base
    start = _RARITY_LADDER.index(base) if base in _RARITY_LADDER else 0
    idx = min(start + tiers, _RARITY_LADDER.index(Rarity.RARE))
    return _RARITY_LADDER[idx]

try:
    from game.items import random_base as _random_base
except ImportError:
    _random_base = None

DROP_CHANCE = 0.10

_FALLBACK_BASES = [
    ("fallback_sword", "Sword", Slot.WEAPON),
    ("fallback_helm", "Helmet", Slot.HELMET),
    ("fallback_ring", "Ring", Slot.RING),
]


def _fallback_base(ilvl: int, rng: random.Random) -> Item:
    bid, bname, slot = rng.choice(_FALLBACK_BASES)
    return Item(base_id=bid, base_name=bname, slot=slot, rarity=Rarity.NORMAL,
                ilvl=ilvl, req_level=max(1, ilvl - 2))


def _make_base(ilvl: int, rng: random.Random, class_id: str | None = None) -> Item:
    if _random_base is not None:
        return _random_base(ilvl, rng, class_id=class_id)
    return _fallback_base(ilvl, rng)


def make_item(ilvl: int, rng: random.Random, magic_find: float = 0.0,
              min_rarity: Rarity | None = None, class_id: str | None = None,
              unique_weight: float | None = None) -> Item:
    return ItemRoller(rng).roll(ilvl, class_id=class_id, magic_find=magic_find,
                                min_rarity=min_rarity, unique_weight=unique_weight)


def roll_drop(monster: Monster, ilvl: int, rng: random.Random,
              magic_find: float = 0.0, class_id: str | None = None,
              item_quantity: float = 0.0,
              unique_weight: float | None = None) -> Item | None:
    # E.3: item_quantity (0..IQ_CAP %) multiplies the base drop chance, stacking
    # multiplicatively with the monster's own loot_bonus. MF (item_rarity) is a
    # SEPARATE axis and only shifts rarity weights inside make_item — quantity
    # governs whether an item drops at all.
    iq = max(0.0, item_quantity)
    # E.6: Rare-tier mobs guarantee at least one drop (bypasses the chance gate).
    guaranteed = bool(getattr(monster, "guaranteed_drop", False))
    if not guaranteed and rng.random() >= DROP_CHANCE * (1.0 + monster.loot_bonus) * (1.0 + iq / 100.0):
        return None
    # 6.4: champions/elites lift the drop's rarity floor by rarity_tier_bonus.
    tiers = int(getattr(monster, "rarity_tier_bonus", 0) or 0)
    min_rarity = _lift_rarity(None, tiers)
    item = make_item(ilvl, rng, magic_find, min_rarity=min_rarity, class_id=class_id,
                     unique_weight=unique_weight)
    # SET injection (tier 6): a set piece supersedes a non-unique roll. Uniques
    # out-rank sets, so a rolled unique is kept. MF nudges the set chance the same
    # way it lifts the high end of the weighted pick.
    if item.rarity is not Rarity.UNIQUE and ilvl >= SET_MIN_ILVL:
        if rng.random() < SET_DROP_CHANCE * (1.0 + magic_find / 200.0):
            piece = roll_set_item(ilvl, rng)
            if piece is not None:
                return piece
    return item


def roll_boss_drops(monster: Monster, ilvl: int, rng: random.Random,
                    magic_find: float = 0.0, class_id: str | None = None) -> list[Item]:
    count = rng.randint(2, 4)
    # LE-4: bosses keep the pre-nerf unique weight (3.0) while trash mobs use
    # the reduced ground weight — boss unique rates are intentionally unchanged.
    # Stage 6.2: the first drop is a guaranteed RARE minimum (a boss should
    # never disappoint), the rest are MAGIC minimum. A UNIQUE roll on any drop
    # still wins (min_rarity only lifts the floor), so boss-only unique pity
    # via BOSS_UNIQUE_WEIGHT is untouched.
    drops = [make_item(ilvl, rng, magic_find + monster.loot_bonus * 100,
                       min_rarity=Rarity.RARE if i == 0 else Rarity.MAGIC,
                       class_id=class_id, unique_weight=BOSS_UNIQUE_WEIGHT)
             for i in range(count)]
    # MYTHIC injection (tier 9): boss-source only (this IS a boss path), gated to
    # ilvl >= MYTHIC_MIN_ILVL. A hit supersedes the boss's first (best) drop.
    if ilvl >= MYTHIC_MIN_ILVL and rng.random() < MYTHIC_DROP_CHANCE:
        myth = roll_mythic(ilvl, rng)
        if myth is not None:
            drops[0] = maybe_overlay(myth, ilvl, rng)
    # SET injection (tier 6): each non-unique/non-mythic boss drop can convert to
    # a set piece, same per-drop chance as the ground path.
    if ilvl >= SET_MIN_ILVL:
        for i, it in enumerate(drops):
            if it.rarity in (Rarity.UNIQUE, Rarity.MYTHIC):
                continue
            if rng.random() < SET_DROP_CHANCE * (1.0 + magic_find / 200.0):
                piece = roll_set_item(ilvl, rng)
                if piece is not None:
                    drops[i] = piece
    return drops


def roll_gold(monster: Monster, rng: random.Random, gold_find: float = 0.0) -> int:
    lo = 1 + monster.level
    hi = 4 + monster.level * 3
    gold = rng.randint(lo, hi)
    if monster.is_boss:
        gold *= rng.randint(5, 10)
    # Stage 6.2 loot pass: fewer trash item drops (DROP_CHANCE 0.25->0.10), so
    # raw gold is raised +30% to keep economy targets (gamble, respec) reachable.
    gold *= 1.30
    return int(gold * (1 + gold_find / 100.0))


if __name__ == "__main__":
    import sys

    from game.core import Stats

    # demo prints starred (★) affix lines; force UTF-8 so a non-UTF8 Windows
    # console (cp1251) doesn't choke on the star glyph. Game/UI use Qt, not this.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    def _affix_lines(it: Item) -> list[str]:
        return [a.lines[0] if a.lines else "; ".join(m.describe() for m in a.mods)
                for a in it.affixes]

    rng = random.Random(7)
    mobs = [
        Monster(name="Zombie", stats=Stats(), monster_id="zombie", level=3),
        Monster(name="Skeleton Archer", stats=Stats(), monster_id="skeleton", level=12,
                loot_bonus=0.2),
        Monster(name="Blood Golem", stats=Stats(), monster_id="golem", level=30,
                loot_bonus=0.5),
    ]
    drops = 0
    for i in range(20):
        mob = mobs[i % len(mobs)]
        ilvl = mob.level + rng.randint(0, 3)
        it = roll_drop(mob, ilvl, rng, magic_find=30.0)
        gold = roll_gold(mob, rng)
        if it is None:
            print(f"{mob.name} (lvl {mob.level}): no drop, +{gold} gold")
            continue
        drops += 1
        print(f"{mob.name} (lvl {mob.level}): [{it.rarity.value}] {it.display_name()} "
              f"({it.base_name}, ilvl {it.ilvl}) +{gold} gold")
        for line in _affix_lines(it):
            print("   " + line)
    boss = Monster(name="Merv, Lord of the Mire", stats=Stats(), monster_id="boss_merv",
                   level=15, is_boss=True, loot_bonus=0.5)
    print("\n=== BOSS ===")
    loot = roll_boss_drops(boss, 18, rng, magic_find=30.0)
    assert 2 <= len(loot) <= 4
    print(f"{boss.name}: {len(loot)} items, +{roll_gold(boss, rng)} gold")
    for it in loot:
        assert it.rarity != Rarity.NORMAL
        print(f" [{it.rarity.value}] {it.display_name()} ({it.base_name}, ilvl {it.ilvl})")
        for line in _affix_lines(it):
            print("   " + line)

    # smart loot: class_id biases weapon bases toward the hero's class on 25%
    # of drops (v2 spec: the other 75% are fully random), so compare the
    # warrior-usable share against an unbiased control run.
    def _usable_share(class_id: str | None) -> float:
        r = random.Random(555)
        usable = total = 0
        for _ in range(4000):
            it = make_item(25, r, class_id=class_id)
            if it.slot is not Slot.WEAPON:
                continue
            total += 1
            usable += 1 if (not it.class_req or "warrior" in it.class_req) else 0
        return usable / total

    biased, control = _usable_share("warrior"), _usable_share(None)
    assert biased > control, f"smart loot failed: {biased:.1%} vs {control:.1%}"
    print(f"smart loot: {biased:.1%} warrior-usable weapons vs {control:.1%} unbiased")
    print(f"\nloot OK ({drops}/20 drops)")
