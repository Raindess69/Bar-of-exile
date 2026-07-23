"""Tests for the 10-tier rarity ladder wiring (ROADMAP «ПЛАН B»).

Covers the pieces the ladder added on top of the classic 4 rarities:
  - SCRAP / EXALTED emerge from ItemRoller with their gates + affix contracts
  - SET / MYTHIC injection through the loot layer (ground vs boss source)
  - RELIC / PRIMAL post-roll overlays (Item.modifier) and serialization

Runnable both ways:
    python tests/test_rarity_ladder.py
    pytest tests/test_rarity_ladder.py
"""
from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.core import MOD_PRIMAL, MOD_RELIC, Monster, Rarity, Stats
from game.item_roller import (
    EXALTED_MIN_ILVL,
    ItemRoller,
    apply_primal,
    apply_relic,
)
from game.loot import (
    MYTHIC_MIN_ILVL,
    SET_MIN_ILVL,
    roll_boss_drops,
    roll_drop,
)
from game.mythics import roll_mythic
from game.save import item_from_dict, item_to_dict
from game.uniques import roll_unique


def _mob(level: int) -> Monster:
    return Monster(name="mob", stats=Stats(), monster_id="mob", level=level)


def test_scrap_and_exalted_emerge():
    """Both new roller tiers actually drop at a high ilvl with high MF."""
    r = ItemRoller(random.Random(1))
    seen = set()
    for _ in range(40_000):
        seen.add(r.roll(70, magic_find=40.0).rarity)
    assert Rarity.SCRAP in seen, "scrap never dropped"
    assert Rarity.EXALTED in seen, "exalted never dropped"


def test_exalted_gate_and_contract():
    """Below EXALTED_MIN_ILVL exalted never rolls; above it, every exalted item
    has 4-6 affixes all at tier <= 3 (affix_tier_floor) and a bonus implicit."""
    r = ItemRoller(random.Random(2))
    for _ in range(20_000):
        assert r.roll(EXALTED_MIN_ILVL - 1, magic_find=60.0).rarity is not Rarity.EXALTED
    r2 = ItemRoller(random.Random(3))
    checked = 0
    for _ in range(60_000):
        it = r2.roll(70, magic_find=60.0)
        if it.rarity is not Rarity.EXALTED:
            continue
        checked += 1
        assert 4 <= len(it.affixes) <= 6, len(it.affixes)
        assert all(a.tier <= 3 for a in it.affixes), [a.tier for a in it.affixes]
        assert it.implicit, "exalted lost its bonus implicit"
    assert checked > 0, "no exalted sampled"


def test_scrap_excluded_when_floored():
    """A rarity floor (boss/champion lift) must never yield SCRAP."""
    r = ItemRoller(random.Random(4))
    for _ in range(20_000):
        it = r.roll(70, magic_find=40.0, min_rarity=Rarity.MAGIC)
        assert it.rarity is not Rarity.SCRAP


def _ground_rarities(mob_level: int, ilvl: int, seed: int, n: int,
                     magic_find: float = 0.0) -> set:
    """roll_drop gates on DROP_CHANCE and returns None on a miss; collect the
    rarities of the drops that actually land."""
    r = random.Random(seed)
    out = set()
    for _ in range(n):
        it = roll_drop(_mob(mob_level), ilvl, r, magic_find=magic_find)
        if it is not None:
            out.add(it.rarity)
    return out


def test_set_injection_ground_and_boss():
    ground = _ground_rarities(70, 70, 5, 40_000, magic_find=40.0)
    assert Rarity.SET in ground, "set never dropped on the ground"
    r = random.Random(55)
    boss = _mob(70)
    boss.is_boss = True
    boss_rar = set()
    for _ in range(8_000):
        for it in roll_boss_drops(boss, 70, r, magic_find=40.0):
            boss_rar.add(it.rarity)
    assert Rarity.SET in boss_rar


def test_set_gated_by_ilvl():
    low = _ground_rarities(10, 10, 6, 40_000)
    assert Rarity.SET not in low, f"set dropped below ilvl {SET_MIN_ILVL}"


def test_mythic_boss_only_and_gated():
    """MYTHIC comes only from the boss path, and only at/above its ilvl gate."""
    # ground never yields mythic
    ground = _ground_rarities(80, 80, 7, 40_000, magic_find=60.0)
    assert Rarity.MYTHIC not in ground
    r = random.Random(77)
    boss = _mob(80)
    boss.is_boss = True
    hi = set()
    for _ in range(20_000):
        for it in roll_boss_drops(boss, 80, r, magic_find=40.0):
            hi.add(it.rarity)
    assert Rarity.MYTHIC in hi, "boss never dropped a mythic at ilvl 80"
    # below the gate the boss cannot roll a mythic
    lo = set()
    for _ in range(6_000):
        for it in roll_boss_drops(boss, MYTHIC_MIN_ILVL - 1, r):
            lo.add(it.rarity)
    assert Rarity.MYTHIC not in lo


def test_relic_overlay():
    rng = random.Random(8)
    # find a unique carrying at least one numeric (flat) mod so scaling is visible
    for _ in range(60):
        u = roll_unique(80, rng)
        if u and any(m.flat for a in u.affixes for m in a.mods):
            break
    n_before = len(u.affixes)
    before = [m.flat for a in u.affixes for m in a.mods if m.flat]
    apply_relic(u, random.Random(1))
    after = [m.flat for a in u.affixes for m in a.mods if m.flat]
    assert u.modifier == MOD_RELIC
    assert u.rarity is Rarity.UNIQUE, "relic must not change rarity"
    assert len(u.affixes) == n_before + 1, "relic must add exactly one affix"
    # the shared scale factor lifted the original mods (1.15..1.30)
    assert sum(after[: len(before)]) > sum(before)


def test_primal_overlay():
    rng = random.Random(9)
    u = roll_unique(80, rng)
    apply_primal(u, rng)
    assert u.modifier == MOD_PRIMAL
    assert u.rarity is Rarity.UNIQUE
    assert all(a.stars >= 3 for a in u.affixes), [a.stars for a in u.affixes]
    # mythic can also become primal
    m = roll_mythic(80, rng)
    apply_primal(m, rng)
    assert m.modifier == MOD_PRIMAL and m.rarity is Rarity.MYTHIC


def test_modifier_round_trips():
    """Item.modifier survives save serialization; absent -> empty string."""
    rng = random.Random(10)
    u = roll_unique(80, rng)
    apply_relic(u, rng)
    back = item_from_dict(item_to_dict(u))
    assert back.modifier == MOD_RELIC
    plain = roll_unique(80, rng)
    assert item_from_dict(item_to_dict(plain)).modifier == ""


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name} OK")
    print("rarity ladder OK")
