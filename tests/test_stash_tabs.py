"""Unit tests for game.stash_tabs (E.2 contract — Stash Tab Limit / Purchase).

Run from repo root:  python tests/test_stash_tabs.py
(NOT `python -m tests.x` — the environment has a conflicting site-packages `tests`.)
Also runnable via:    python -m pytest tests/test_stash_tabs.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game import stash_tabs as ST


# --- 1. price table matches spec; total ≈220M --------------------------- #
def test_tab_price_table_and_total():
    expected = {
        1: 1_000, 2: 5_000, 3: 20_000, 4: 75_000, 5: 250_000,
        6: 1_000_000, 7: 4_000_000, 8: 15_000_000, 9: 50_000_000, 10: 150_000_000,
    }
    for n, price in expected.items():
        assert ST.tab_price(n) == price, f"tab {n} price mismatch"
    total = sum(ST.tab_price(n) for n in range(1, ST.MAX_TABS + 1))
    # spec says the full 10-entry table sums to ≈220M
    assert abs(total - 220_000_000) <= 1_000_000, f"total {total} not ≈220M"
    # out-of-range guarded
    for bad in (0, 11, -1):
        try:
            ST.tab_price(bad)
            assert False, f"tab_price({bad}) should raise"
        except ValueError:
            pass
    print("1. tab_price table + total OK")


# --- 2. buy_tab: atomic, decrements, respects cap and broke ------------- #
def test_buy_tab_atomic():
    # own 1, plenty of gold -> buy tab 2 for exactly 5k
    owned, gold, ok = ST.buy_tab(1, 10_000)
    assert ok and owned == 2 and gold == 10_000 - 5_000, (owned, gold, ok)
    # broke: gold below next price -> unchanged, ok False
    owned, gold, ok = ST.buy_tab(1, 4_999)
    assert not ok and owned == 1 and gold == 4_999, (owned, gold, ok)
    # at MAX_TABS -> can't buy no matter how rich
    owned, gold, ok = ST.buy_tab(ST.MAX_TABS, 10 ** 12)
    assert not ok and owned == ST.MAX_TABS and gold == 10 ** 12
    # can_buy_tab agrees
    assert ST.can_buy_tab(1, 5_000) is True
    assert ST.can_buy_tab(1, 4_999) is False
    assert ST.can_buy_tab(ST.MAX_TABS, 10 ** 12) is False
    print("2. buy_tab atomic OK")


# --- 3. capacity + is_full boundary ------------------------------------- #
def test_capacity_and_full():
    assert ST.capacity(1) == 40
    assert ST.capacity(3) == 120
    assert ST.capacity(ST.MAX_TABS) == 400
    # boundary: full exactly at capacity, not before
    assert ST.is_full(39, 1) is False
    assert ST.is_full(40, 1) is True
    assert ST.is_full(41, 1) is True
    assert ST.is_full(119, 3) is False
    assert ST.is_full(120, 3) is True
    # tab_of_slot
    assert ST.tab_of_slot(0) == 0
    assert ST.tab_of_slot(39) == 0
    assert ST.tab_of_slot(40) == 1
    assert ST.tab_of_slot(81) == 2
    print("3. capacity + is_full OK")


# --- 4. migrate_unlimited: no item lost, order preserved ---------------- #
def test_migrate_no_loss():
    items = list(range(100))  # opaque objects; ints stand in
    # owned 2 tabs -> cap 80; 20 overflow
    fit, overflow = ST.migrate_unlimited(items, 2)
    assert len(fit) + len(overflow) == len(items), "no item may be lost"
    assert len(fit) == 80 and len(overflow) == 20
    assert fit == list(range(80)), "order preserved in fit"
    assert overflow == list(range(80, 100)), "order preserved in overflow"
    # fits entirely -> overflow empty
    fit, overflow = ST.migrate_unlimited(list(range(30)), 1)
    assert overflow == [] and fit == list(range(30))
    # empty stash
    fit, overflow = ST.migrate_unlimited([], 1)
    assert fit == [] and overflow == []
    print("4. migrate no-loss OK")


# --- 5. sanitize_owned clamps ------------------------------------------- #
def test_sanitize_owned():
    assert ST.sanitize_owned(1) == 1
    assert ST.sanitize_owned(10) == 10
    assert ST.sanitize_owned(0) == 1
    assert ST.sanitize_owned(-5) == 1
    assert ST.sanitize_owned(999) == 10
    assert ST.sanitize_owned(None) == 1
    assert ST.sanitize_owned("garbage") == 1
    assert ST.sanitize_owned("7") == 7   # coercible strings ok
    assert ST.sanitize_owned(3.9) == 3   # float coerced (truncates)
    print("5. sanitize_owned OK")


# --- 6. gold never negative through a full buy-all loop ----------------- #
def test_buy_all_gold_nonnegative():
    gold = sum(ST.tab_price(n) for n in range(2, ST.MAX_TABS + 1))  # exact funds
    owned = 1
    while ST.can_buy_tab(owned, gold):
        owned, gold, ok = ST.buy_tab(owned, gold)
        assert ok
        assert gold >= 0, "gold must never go negative"
    assert owned == ST.MAX_TABS, f"should own all tabs, got {owned}"
    assert gold == 0, f"exact funds should net to 0, got {gold}"
    # one more attempt does nothing
    owned2, gold2, ok = ST.buy_tab(owned, gold)
    assert not ok and owned2 == owned and gold2 == gold
    print("6. buy-all gold non-negative OK")


if __name__ == "__main__":
    test_tab_price_table_and_total()
    test_buy_tab_atomic()
    test_capacity_and_full()
    test_migrate_no_loss()
    test_sanitize_owned()
    test_buy_all_gold_nonnegative()
    print("\nALL STASH_TABS TESTS PASSED")
