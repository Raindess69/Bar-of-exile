#!/usr/bin/env python3
"""Plain-assert tests for game/idle_upgrades.py (spec E.1).

Run from repo root:
    python tests/test_idle_upgrades.py
    python -m pytest tests/test_idle_upgrades.py -q
"""
import math
import os
import sys

sys.path.insert(0, os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from game import idle_upgrades as IU


def _expected_cost(base, growth, lvl):
    return int(math.ceil(base * growth ** lvl / 10.0)) * 10


# --- 1. geometric cost, rounds up to 10 ----------------------------------- #
def test_cost_geometric_round_up():
    for up in IU.UPGRADES.values():
        for lvl in range(0, up.max_lvl):
            c = IU.cost(up.id, lvl)
            assert c == _expected_cost(up.base, up.growth, lvl), (up.id, lvl, c)
            assert c % 10 == 0, (up.id, lvl, c)
            assert c > 0
        # no next level at/over max
        assert IU.cost(up.id, up.max_lvl) == 0
        assert IU.cost(up.id, up.max_lvl + 5) == 0
    # unknown id -> 0, garbage lvl clamps to 0
    assert IU.cost("nope", 3) == 0
    assert IU.cost("up_xp", -7) == IU.cost("up_xp", 0)


# --- 2. last-level cost matches spec approximations ----------------------- #
def test_last_level_cost_matches_spec():
    # spec "Цена посл. ур." (≈, fuzzy): the final purchase, cost(max-1).
    # The spec's own numbers mix cost(max-1) and cost(max) conventions, so use
    # a generous band that still catches a formula/magnitude error.
    bands = {"up_xp": 2.1e6, "up_gold": 6.3e6, "up_sxp": 192e3, "up_offline": 267e3}
    for uid, target in bands.items():
        up = IU.UPGRADES[uid]
        last = IU.cost(uid, up.max_lvl - 1)
        assert abs(last - target) / target < 0.15, (uid, last, target)


# --- 3. buy: atomic gold/level changes, blocked at max/broke -------------- #
def test_buy_atomic():
    ups = {}
    gold = 10_000
    ups, gold, ok = IU.buy(ups, "up_xp", gold)
    assert ok and ups["up_xp"] == 1 and gold == 10_000 - IU.cost("up_xp", 0)

    # exact-cost purchase leaves gold >= 0, decrement is exact
    price1 = IU.cost("up_xp", 1)
    ups2, gold2, ok2 = IU.buy(ups, "up_xp", price1)
    assert ok2 and ups2["up_xp"] == 2 and gold2 == 0

    # broke: no change, ok False
    ups3, gold3, ok3 = IU.buy(ups, "up_xp", 0)
    assert not ok3 and gold3 == 0 and ups3 == ups

    # input dict not mutated
    original = {"up_xp": 1}
    snapshot = dict(original)
    IU.buy(original, "up_xp", 999_999)
    assert original == snapshot, "buy must not mutate input"

    # maxed: cannot buy
    maxed = {"up_offline": IU.UPGRADES["up_offline"].max_lvl}
    m2, mg, mok = IU.buy(maxed, "up_offline", 10 ** 12)
    assert not mok and mg == 10 ** 12
    assert not IU.can_buy(maxed, "up_offline", 10 ** 12)
    assert IU.is_maxed(maxed, "up_offline")

    # unknown id
    u2, ug, uok = IU.buy({}, "bogus", 10 ** 9)
    assert not uok and not IU.can_buy({}, "bogus", 10 ** 9)


# --- 4. effect getters: zero empty, correct at cap ----------------------- #
def test_effect_getters():
    assert IU.xp_gain_bonus_pct({}) == 0.0
    assert IU.gold_find_bonus_pct({}) == 0.0
    assert IU.skill_xp_bonus_pct({}) == 0.0
    assert IU.offline_efficiency_mult({}) == 1.0

    cap = {"up_xp": 100, "up_gold": 100, "up_sxp": 50, "up_offline": 40}
    assert abs(IU.xp_gain_bonus_pct(cap) - 50.0) < 1e-9
    assert abs(IU.gold_find_bonus_pct(cap) - 40.0) < 1e-9
    assert abs(IU.skill_xp_bonus_pct(cap) - 25.0) < 1e-9
    assert abs(IU.offline_efficiency_mult(cap) - 1.20) < 1e-9

    # linear mid-values
    assert abs(IU.gold_find_bonus_pct({"up_gold": 50}) - 20.0) < 1e-9


# --- 5. sanitize: drop unknown, clamp over-max, garbage -> {} ------------ #
def test_sanitize():
    assert IU.sanitize(None) == {}
    assert IU.sanitize("garbage") == {}
    assert IU.sanitize(42) == {}
    assert IU.sanitize([]) == {}
    # unknown ids dropped, over-max clamped, floats coerced, zero/neg dropped
    raw = {"up_xp": 200, "up_gold": 3.0, "bogus": 5, "up_sxp": 0, "up_offline": -4}
    clean = IU.sanitize(raw)
    assert clean == {"up_xp": 100, "up_gold": 3}
    # non-int garbage value dropped, not raised
    assert IU.sanitize({"up_xp": "abc"}) == {}
    # old save (empty) -> {}
    assert IU.sanitize({}) == {}


# --- 6. gold never goes negative through a buy loop ----------------------- #
def test_gold_never_negative_loop():
    ups = {}
    gold = 100_000
    for _ in range(500):
        ups, gold, ok = IU.buy(ups, "up_xp", gold)
        assert gold >= 0, gold
        if not ok:
            break
    # sanity: some levels were actually bought
    assert ups.get("up_xp", 0) > 0
    # after loop stops, buying again with that gold is a no-op if unaffordable
    lvl = ups.get("up_xp", 0)
    if IU.cost("up_xp", lvl) > gold:
        _, g2, ok2 = IU.buy(ups, "up_xp", gold)
        assert not ok2 and g2 == gold


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("OK", name)
    print("ALL IDLE_UPGRADES TESTS PASSED")
