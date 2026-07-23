#!/usr/bin/env python3
"""Plain-assert tests for game/gamble.py. Run: python tests/test_gamble.py"""
import os
import random
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
from game.core import Rarity, Slot
from game.gamble import (BASE_UNIQUE_RATE, RARE_CHANCE, GambleVendor,
                         gamble_cost, make_gambled_item, unique_chance)


def test_unique_chance_curve():
    assert unique_chance(0) == 0.006
    assert unique_chance(71) == 0.006          # roll 72: still base
    assert abs(unique_chance(72) - 0.126) < 1e-9   # roll 73: 0.006+0.12
    assert abs(unique_chance(73) - 0.246) < 1e-9
    assert abs(unique_chance(78) - 0.846) < 1e-9   # roll 79
    assert unique_chance(79) == 1.0            # roll 80: hard pity
    assert unique_chance(200) == 1.0


def test_costs():
    for lv in (1, 10, 35, 60, 100):
        expected = max(1, int(round(40.0 * lv + 15.0 * lv ** 1.35)))
        assert gamble_cost(lv, "weapon") == expected
        assert gamble_cost(lv, "ring") == max(1, int(round((40.0 * lv + 15.0 * lv ** 1.35) * 1.5)))
    assert gamble_cost(10, "weapon", {"ks_house_rules"}) == max(1, int(round((40.0 * 10 + 15.0 * 10 ** 1.35) * 0.8)))


def test_keystone_hooks():
    assert unique_chance(0, {"ks_house_rules"}) == 0.003
    # singularity: hard pity 60, soft pity disabled
    assert unique_chance(59, {"ks_singularity_of_want"}) == 1.0
    assert unique_chance(58, {"ks_singularity_of_want"}) == BASE_UNIQUE_RATE
    assert unique_chance(74, {"ks_singularity_of_want"}) == 1.0


class HighRng:
    """random() always 0.99 -> never unique (until hard pity), never natural rare."""
    def random(self):
        return 0.99


def test_loaded_dice_and_pity_flow():
    v = GambleVendor(rng=HighRng())
    for i in range(1, 21):
        res = v.roll(10, "weapon", keystones={"ks_loaded_dice"})
        assert res["ok"]
        expected = "rare" if i % 10 == 0 else "magic"
        assert res["rarity"] == expected, (i, res)
    assert v.pity == 20


def test_hard_pity_and_reset():
    v = GambleVendor(rng=HighRng())
    rarities = [v.roll(10)["rarity"] for _ in range(80)]
    assert rarities[:79] == ["magic"] * 79
    assert rarities[79] == "unique"
    assert v.pity == 0
    # gilded grudge: reset to 20
    v2 = GambleVendor(rng=HighRng())
    for _ in range(79):
        v2.roll(10, keystones={"aks_gilded_grudge"})
    res = v2.roll(10, keystones={"aks_gilded_grudge"})
    assert res["rarity"] == "unique" and v2.pity == 20


def test_simulation_expected_pulls():
    rng = random.Random(20260715)
    v = GambleVendor(rng=rng)
    pulls, uniques, since = [], 0, 0
    while uniques < 500:
        since += 1
        if v.roll(30)["rarity"] == "unique":
            pulls.append(since)
            since = 0
            uniques += 1
    mean = sum(pulls) / len(pulls)
    assert 58 < mean < 67, mean  # expected ~62.3; acceptance band [61,64] ± sim noise


def test_rare_floor_distribution():
    rng = random.Random(42)
    v = GambleVendor(rng=rng)
    n = 20000
    for _ in range(n):
        v.roll(20)
    rare_share = v.stats["rare"] / n
    assert abs(rare_share - RARE_CHANCE * (1 - 0.016)) < 0.02, rare_share
    assert v.stats["magic"] + v.stats["rare"] + v.stats["unique"] == n


def test_not_enough_gold_and_serialization():
    v = GambleVendor(rng=HighRng())
    res = v.roll(50, "ring", gold=1)
    assert not res["ok"] and res["reason"] == "not_enough_gold"
    v.roll(10)
    d = v.to_dict()
    v2 = GambleVendor.from_dict(d, rng=HighRng())
    assert v2.pity == v.pity and v2.lifetime_rolls == v.lifetime_rolls and v2.stats == v.stats


def test_item_generation_v2_pipeline():
    """Repo integration: roll() rarity -> real Item via item_roller/uniques."""
    rng = random.Random(7)
    for _ in range(60):
        it = make_gambled_item("magic", 30, "weapon", rng, class_id="warrior")
        assert it.rarity is Rarity.MAGIC and it.slot is Slot.WEAPON
        assert 1 <= len(it.affixes) <= 2
    for _ in range(60):
        it = make_gambled_item("rare", 40, "ring", rng)
        assert it.rarity is Rarity.RARE and it.slot is Slot.RING
        assert 3 <= len(it.affixes) <= 6  # spec E.4: rare 3-6 affixes
    it = make_gambled_item("unique", 30, "boots", rng)
    assert it.rarity in (Rarity.UNIQUE, Rarity.RARE)  # unique_gate fallback
    # unique at ilvl 1 may gate down to rare — must still return a valid Item
    it = make_gambled_item("unique", 1, "belt", rng)
    assert it.rarity in (Rarity.UNIQUE, Rarity.RARE)
    # roll_item: one-call convenience for main.py / gamble_panel
    v = GambleVendor(rng=random.Random(99))
    res = v.roll_item(25, slot="amulet", class_id="mage")
    assert res["ok"] and res["item"].rarity.value == res["rarity"]
    # determinism: same seed -> same sequence of items
    v1, v2 = GambleVendor(random.Random(5)), GambleVendor(random.Random(5))
    for _ in range(30):
        a = v1.roll_item(35, slot="helmet")
        b = v2.roll_item(35, slot="helmet")
        assert a["rarity"] == b["rarity"] and a["item"].name == b["item"].name


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("OK", name)
    print("ALL GAMBLE TESTS PASSED")
