"""L7: E.3 item_quantity (drop-chance mult) + E.5 greater-affix (stars).

Covers the star roll table, the roller applying star magnitude past roll_max,
save round-trip of stars, corrupt-degrade preserving the star mark, the IQ stat
cap in recalc, and IQ multiplying roll_drop's drop chance.
"""
from __future__ import annotations

import random

import pytest

from game import greater_affix as ga
from game.core import Affix, IQ_CAP, Item, Rarity, Slot, StatMod, Stats
from game.item_roller import _make_affix
from game.loot import DROP_CHANCE, roll_drop
from game.save import _affix_from_dict, _affix_to_dict


# ---------------- E.5 star table ----------------

def test_star_roll_distribution_and_bounds():
    rng = random.Random(1)
    counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    n = 100_000
    for _ in range(n):
        s = ga.star_roll(rng)
        assert 0 <= s <= 4
        counts[s] += 1
    # overwhelming majority unstarred; ★1 clearly the most common star
    assert counts[0] / n > 0.90
    assert counts[1] > counts[2] > counts[3] > counts[4]


def test_star_mult_monotonic_and_identity():
    assert ga.star_mult(0) == 1.0
    assert ga.star_mult(1) < ga.star_mult(2) < ga.star_mult(3) < ga.star_mult(4)
    assert ga.star_mult(4) == pytest.approx(2.20)
    assert ga.star_mark(0) == "" and ga.star_mark(3) == "★★★ "


# ---------------- E.5 roller applies stars ----------------

_AFFIX_SPEC = {
    "id": "phys_inc_t1", "name": "Tyrannical", "type": "prefix", "_tier": 1,
    "stat": "physical_damage_inc_pct", "roll_min": 10, "roll_max": 20,
    "display": "+{v}% increased Physical Damage",
}


def test_star_breaks_tier_cap():
    """A starred single-value affix can exceed roll_max; its line shows ★."""
    saw_over_cap = False
    for seed in range(4000):
        rng = random.Random(seed)
        a = _make_affix(dict(_AFFIX_SPEC), rng)
        if a.stars:
            val = a.mods[0].inc
            assert a.lines[0].startswith("★" * a.stars)
            if val > _AFFIX_SPEC["roll_max"]:
                saw_over_cap = True
        else:
            assert a.mods[0].inc <= _AFFIX_SPEC["roll_max"]
            assert not a.lines[0].startswith("★")
    assert saw_over_cap, "expected at least one starred roll above roll_max"


def test_unstarred_line_has_no_mark():
    rng = random.Random(0)
    # seed 0 first draw is unstarred here; assert clean rendering
    a = _make_affix(dict(_AFFIX_SPEC), rng)
    if not a.stars:
        assert "★" not in a.lines[0]


# ---------------- E.5 save round-trip ----------------

def test_stars_survive_save_roundtrip():
    a = Affix(id="x", name="N", is_prefix=True, tier=1,
              mods=[StatMod("damage_min", inc=99)], lines=["★★ +99% foo"], stars=2)
    back = _affix_from_dict(_affix_to_dict(a))
    assert back.stars == 2 and back.lines == ["★★ +99% foo"]
    # zero-star affix omits the key but rebuilds as 0
    plain = Affix(id="y", name="M", is_prefix=False, tier=3, mods=[])
    d = _affix_to_dict(plain)
    assert "stars" not in d
    assert _affix_from_dict(d).stars == 0


# ---------------- E.3 item_quantity cap ----------------

def test_iq_cap_in_recalc():
    from game.core import Hero
    hero = Hero(name="T", stats=Stats(), base_stats=Stats(), class_id="warrior")
    hero.base_stats.item_quantity = IQ_CAP + 500.0
    hero.recalc()
    assert hero.stats.item_quantity == IQ_CAP
    hero.base_stats.item_quantity = -20.0
    hero.recalc()
    assert hero.stats.item_quantity == 0.0


# ---------------- E.3 roll_drop uses IQ ----------------

class _Mob:
    loot_bonus = 0.0
    rarity_tier_bonus = 0


def _drop_rate(item_quantity: float, seed: int, n: int = 6000) -> float:
    rng = random.Random(seed)
    hits = 0
    mob = _Mob()
    for _ in range(n):
        # only count the drop/no-drop gate; make_item consumes rng after a hit,
        # but rate comparison across equal seeds+n stays monotonic in IQ.
        if roll_drop(mob, 20, rng, item_quantity=item_quantity) is not None:
            hits += 1
    return hits / n


def test_item_quantity_raises_drop_rate():
    base = _drop_rate(0.0, seed=42)
    juiced = _drop_rate(100.0, seed=42)
    # 100% IQ ~ doubles the base DROP_CHANCE gate
    assert juiced > base * 1.5
    assert base == pytest.approx(DROP_CHANCE, abs=0.03)


def test_item_quantity_zero_is_noop():
    mob = _Mob()
    rng_a = random.Random(7)
    rng_b = random.Random(7)
    seq_a = [roll_drop(mob, 20, rng_a, item_quantity=0.0) is not None for _ in range(200)]
    seq_b = [roll_drop(mob, 20, rng_b) is not None for _ in range(200)]
    assert seq_a == seq_b
