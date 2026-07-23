"""Tests for game.item_roller (spec ITEMS_TREE_V2.md 1.4).

Runnable both ways:
    python tests/test_item_roller.py
    pytest tests/test_item_roller.py
"""
from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.core import Rarity
from game.item_roller import BOSS_UNIQUE_WEIGHT, POOL, ItemRoller
from game.save import item_to_dict

_META = {a["id"]: a for a in POOL}
N_ROLLS = 10_000


def _roll_batch(ilvl: int, seed: int = 1000):
    roller = ItemRoller(random.Random(seed + ilvl))
    return [roller.roll(ilvl, class_id="warrior", magic_find=30.0)
            for _ in range(N_ROLLS)]


def test_invariants():
    """No over-ilvl affixes, no duplicate families, prefix/suffix caps, rare counts."""
    for ilvl in (1, 30, 70):
        for it in _roll_batch(ilvl):
            if it.rarity is Rarity.UNIQUE:
                continue  # fixed mod sets, not from the v2 pool
            fams = []
            n_pre = n_suf = 0
            for a in it.affixes:
                meta = _META[a.id]
                assert meta["ilvl_req"] <= ilvl, \
                    f"ilvl {ilvl}: {a.id} needs ilvl {meta['ilvl_req']}"
                fams.append(meta["family"])
                n_pre += a.is_prefix
                n_suf += not a.is_prefix
                assert a.lines and "{" not in a.lines[0], (a.id, a.lines)
            assert len(fams) == len(set(fams)), f"duplicate family: {fams}"
            if it.rarity is Rarity.MAGIC:
                assert n_pre <= 1 and n_suf <= 1, (n_pre, n_suf)
                assert 1 <= len(it.affixes) <= 2, len(it.affixes)
            elif it.rarity is Rarity.RARE:
                assert n_pre <= 3 and n_suf <= 3, (n_pre, n_suf)
                assert 3 <= len(it.affixes) <= 6, len(it.affixes)  # spec E.4: 3-6
            elif it.rarity is Rarity.EXALTED:
                # spec tier 5: 4-6 affixes, all at tier <= 3 (affix_tier_floor)
                assert n_pre <= 3 and n_suf <= 3, (n_pre, n_suf)
                assert 4 <= len(it.affixes) <= 6, len(it.affixes)
                assert all(a.tier <= 3 for a in it.affixes), \
                    [a.tier for a in it.affixes]
            else:
                assert not it.affixes, it.rarity  # scrap/normal: 0 affixes


def test_tier_bias_at_70():
    """At ilvl 70 the T1+T2 share among rolled affix tiers must exceed 18%."""
    tiers: list[int] = []
    for it in _roll_batch(70, seed=2000):
        if it.rarity is Rarity.UNIQUE:
            continue
        tiers.extend(a.tier for a in it.affixes)
    share = sum(t <= 2 for t in tiers) / len(tiers)
    print(f"ilvl 70 T1+T2 share: {share:.1%} over {len(tiers)} affixes")
    assert share > 0.18, f"tier bias too weak: {share:.1%}"


def test_determinism():
    """Same seed -> byte-identical item sequences (via save.item_to_dict)."""
    r1 = ItemRoller(random.Random(777))
    r2 = ItemRoller(random.Random(777))
    for i in range(300):
        ilvl = 1 + (i * 7) % 70
        a = r1.roll(ilvl, class_id="mage", magic_find=15.0)
        b = r2.roll(ilvl, class_id="mage", magic_find=15.0)
        assert item_to_dict(a) == item_to_dict(b), f"divergence at roll {i}"


def test_ground_unique_rate():
    """LE-4: ground drops must yield uniques well under 1% (weight 0.4/97.4)
    so the gamble vendor (0.6%/roll pity) stays the unique-hunting path."""
    roller = ItemRoller(random.Random(4242))
    n = 20_000
    uniq = sum(roller.roll(70, magic_find=30.0).rarity is Rarity.UNIQUE
               for _ in range(n))
    share = uniq / n
    print(f"ground unique share @ ilvl 70, MF30: {share:.2%} ({uniq}/{n})")
    assert share < 0.01, f"ground unique rate too high: {share:.2%}"
    assert share > 0.0, "uniques never drop from the ground"


def test_boss_unique_weight_override():
    """Boss path (unique_weight=BOSS_UNIQUE_WEIGHT) keeps the old ~3-weight
    unique rate: clearly above the nerfed ground rate. The real boss path always
    sets a rarity floor (see loot.roll_boss_drops), which also excludes SCRAP from
    the pick, so the unique share is measured against the floored distribution."""
    assert BOSS_UNIQUE_WEIGHT == 3.0
    roller = ItemRoller(random.Random(9090))
    n = 20_000
    uniq = sum(roller.roll(70, magic_find=30.0, min_rarity=Rarity.MAGIC,
                           unique_weight=BOSS_UNIQUE_WEIGHT).rarity is Rarity.UNIQUE
               for _ in range(n))
    share = uniq / n
    print(f"boss-weight unique share @ ilvl 70, MF30: {share:.2%} ({uniq}/{n})")
    assert 0.015 < share < 0.06, f"boss unique rate off: {share:.2%}"


if __name__ == "__main__":
    test_invariants()
    print("invariants OK (10k rolls x ilvl 1/30/70)")
    test_tier_bias_at_70()
    print("tier bias OK")
    test_determinism()
    print("determinism OK")
    test_ground_unique_rate()
    print("ground unique rate OK")
    test_boss_unique_weight_override()
    print("boss unique weight OK")
    print("test_item_roller: ALL OK")
