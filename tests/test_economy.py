"""Tests for game.economy (spec V2 step 6.1).

Runnable both ways:
    python tests/test_economy.py
    pytest tests/test_economy.py
"""
from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game import statmap
from game.core import Affix, Item, Rarity, Slot
from game.economy import bulk_sell_threshold, gamble_cost, item_value
from game.item_roller import POOL, ItemRoller


def _pool_affix(entry: dict, rolled: int) -> Affix:
    """Build an Affix from a POOL entry with an exact single-value roll."""
    assert not statmap.is_pair_stat(entry["stat"]), entry["id"]
    return Affix(id=entry["id"], name=entry["name"],
                 is_prefix=entry["type"] == "prefix", tier=entry["_tier"],
                 mods=statmap.mods_for(entry["stat"], rolled))


def _rare(ilvl: int, affixes: list[Affix]) -> Item:
    return Item(base_id="t", base_name="T", slot=Slot.HELMET,
                rarity=Rarity.RARE, ilvl=ilvl, affixes=affixes)


def test_min_value():
    it = Item(base_id="t", base_name="T", slot=Slot.HELMET,
              rarity=Rarity.NORMAL, ilvl=1)
    assert item_value(it) >= 1, item_value(it)


def test_monotonic():
    """Better roll and better tier of the same stat -> strictly higher value."""
    # two tiers of the same single-value stat, different ids
    by_stat: dict[str, list[dict]] = {}
    for a in POOL:
        if not statmap.is_pair_stat(a["stat"]):
            by_stat.setdefault(a["stat"], []).append(a)
    pair = next(sorted(v, key=lambda a: a["_tier"])
                for v in by_stat.values() if len({a["_tier"] for a in v}) >= 2)
    best, worse = pair[0], pair[-1]
    assert best["_tier"] < worse["_tier"]

    # same affix, min vs max roll
    lo_roll = _rare(20, [_pool_affix(worse, worse["roll_min"])])
    hi_roll = _rare(20, [_pool_affix(worse, worse["roll_max"])])
    assert item_value(hi_roll) > item_value(lo_roll), \
        (item_value(lo_roll), item_value(hi_roll))

    # same roll fraction, better tier
    lo_tier = _rare(20, [_pool_affix(worse, worse["roll_max"])])
    hi_tier = _rare(20, [_pool_affix(best, best["roll_max"])])
    assert item_value(hi_tier) > item_value(lo_tier), \
        (item_value(lo_tier), item_value(hi_tier))


def test_rarity_ordering():
    """Rare > magic > normal for the same base/ilvl (direct construction)."""
    entry = next(a for a in POOL if not statmap.is_pair_stat(a["stat"]))
    aff = _pool_affix(entry, entry["roll_max"])
    base = dict(base_id="t", base_name="T", slot=Slot.HELMET, ilvl=20)
    normal = Item(rarity=Rarity.NORMAL, **base)
    magic = Item(rarity=Rarity.MAGIC, affixes=[aff], **base)
    rare = Item(rarity=Rarity.RARE, affixes=[aff], **base)
    assert item_value(rare) > item_value(magic) > item_value(normal)

    # and statistically, over rolled items
    roller = ItemRoller(random.Random(6))
    sums = {Rarity.NORMAL: [], Rarity.MAGIC: [], Rarity.RARE: []}
    for rar in sums:
        while len(sums[rar]) < 200:
            it = roller.roll(20, min_rarity=rar)
            if it.rarity is rar:
                sums[rar].append(item_value(it))
    avg = {r: sum(v) / len(v) for r, v in sums.items()}
    assert avg[Rarity.RARE] > avg[Rarity.MAGIC] > avg[Rarity.NORMAL], avg


def test_rare_value_vs_gamble():
    """Selling rares must not out-earn gambling: avg rare @40 < half a gamble."""
    roller = ItemRoller(random.Random(40))
    vals = []
    while len(vals) < 500:
        it = roller.roll(40, min_rarity=Rarity.RARE)
        if it.rarity is Rarity.RARE:
            vals.append(item_value(it))
    avg = sum(vals) / len(vals)
    cap = gamble_cost(40) * 0.5
    print(f"avg rare value @ ilvl 40: {avg:.0f} (cap {cap:.0f})")
    assert avg < cap, (avg, cap)


def test_deterministic():
    roller = ItemRoller(random.Random(123))
    for _ in range(100):
        it = roller.roll(30, magic_find=60.0)
        assert item_value(it) == item_value(it)


def test_helpers():
    assert gamble_cost(1) == 55
    assert gamble_cost(1, jewelry=True) == 82
    assert gamble_cost(40) < gamble_cost(41)
    assert bulk_sell_threshold(1) == 2
    assert bulk_sell_threshold(3) == 2
    assert bulk_sell_threshold(7) == 2
    assert bulk_sell_threshold(11) == 6
    assert bulk_sell_threshold(40) == 35


def test_bulk_sell_condition():
    """Bulk-sell junk = ilvl < threshold OR rarity NORMAL (normals always go)."""
    def is_junk(item: Item, level: int) -> bool:
        # mirrors ui.vendor_panel.VendorPanel._on_bulk_sell
        return item.ilvl < bulk_sell_threshold(level) or item.rarity is Rarity.NORMAL

    base = dict(base_id="t", base_name="T", slot=Slot.HELMET)
    # level 3 -> threshold 2: a normal item with ilvl 10 is still junk
    assert bulk_sell_threshold(3) == 2
    assert is_junk(Item(rarity=Rarity.NORMAL, ilvl=10, **base), 3)
    # low-ilvl magic falls under the threshold at higher level
    assert is_junk(Item(rarity=Rarity.MAGIC, ilvl=1, **base), 20)
    # rare/magic at or above the threshold are kept
    assert not is_junk(Item(rarity=Rarity.MAGIC, ilvl=10, **base), 3)
    assert not is_junk(Item(rarity=Rarity.RARE, ilvl=40, **base), 40)
    assert not is_junk(Item(rarity=Rarity.UNIQUE, ilvl=40, **base), 40)


if __name__ == "__main__":
    test_min_value()
    print("min value OK")
    test_monotonic()
    print("monotonic OK")
    test_rarity_ordering()
    print("rarity ordering OK")
    test_rare_value_vs_gamble()
    print("rare vs gamble OK")
    test_deterministic()
    print("determinism OK")
    test_helpers()
    print("helpers OK")
    test_bulk_sell_condition()
    print("bulk sell condition OK")
    print("test_economy: ALL OK")
